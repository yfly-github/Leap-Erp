# app/services/uploader_service.py
import os
import random
import glob
import asyncio
import json
import time
import re
import shutil
import datetime
from pathlib import Path

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import settings
from app.repository.wb_product_repository import WBProductRepository
from app.utils.http_client import request_with_retry
from app.constants.wb_constants import CONTENT_API_URL


class WBUploaderService:
    def __init__(self, target_store: str, token: str):
        self.target_store = target_store

        self.token = token.strip() if token else ""
        if not self.token:
            raise ValueError(f"店铺 {target_store} 的 Token 为空，请检查数据库配置")

        self.headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.marketplace_url = "https://marketplace-api.wildberries.ru"
        self.discount_url = "https://discounts-prices-api.wildberries.ru"

        self.warehouse_id = self.fetch_warehouse_id()
        self.dynamic_rate = self.fetch_dynamic_rate(settings.PROFIT_MARGIN)

    def fetch_warehouse_id(self):
        url = f"{self.marketplace_url}/api/v3/warehouses"
        resp = request_with_retry(url, headers=self.headers)
        if resp and resp.status_code == 200:
            warehouses = resp.json()
            if warehouses: return warehouses[0]['id']
        return 0

    def fetch_dynamic_rate(self, profit_margin=0.95):
        url = "https://www.cbr-xml-daily.ru/daily_json.js"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                cny_value = resp.json()['Valute']['CNY']['Value']
                rub_to_cny = 1 / cny_value
                return rub_to_cny * profit_margin
        except:
            pass
        return 0.086 * profit_margin

    def _calc_price(self, rub_price):
        rate = self.dynamic_rate
        if rub_price < 500:
            return int(rub_price * rate * 1.5)
        elif rub_price < 2000:
            return int(rub_price * rate * 1.2)
        return int(rub_price * rate * 1.1)

    # ==========================================
    # 数据清洗与解析核心模块
    # ==========================================
    def _get_clean_label(self, raw_value: str) -> str:
        """清洗属性字符串，仅保留字母/数字/俄语/下划线，用于 SKU 组装"""
        if not raw_value:
            return ""
        clean_text = re.sub(r'[^\w\s-]', '', str(raw_value)).strip()
        return clean_text.replace(" ", "_")[:15]

    def _generate_base_spu(self, product) -> str:
        """生成唯一的基础 SPU 货号，格式：[前缀][年月]-[数据库自增ID]"""
        prefix = getattr(settings, "SKU_PREFIX", "LP")
        year_month = datetime.datetime.now().strftime("%y%m")
        return f"{prefix}{year_month}-{product.id:06d}"

    def _generate_smart_sku(self, base_spu: str, product, size_obj) -> str:
        """动态生成智能 SKU 条码，格式：SPU[-颜色][-尺码]"""
        color_segment = ""
        try:
            raw_attrs = product.attributes_json
            # 统一解析为 Python 对象，防止字符串误判
            attrs = json.loads(raw_attrs) if isinstance(raw_attrs, str) else raw_attrs

            raw_color = ""
            if isinstance(attrs, dict):
                raw_color = attrs.get("Цвет") or attrs.get("color")
            elif isinstance(attrs, list):
                item = next((i for i in attrs if i.get("name") in {"Цвет", "color"}), None)
                if item: raw_color = item.get("value")

            if raw_color:
                clean_color = self._get_clean_label(raw_color)
                if clean_color:
                    color_segment = f"-{clean_color}"
        except Exception as e:
            print(f"⚠️ 解析颜色属性时发生异常: {e}")

        size_segment = ""
        if size_obj:
            tech_size = str(size_obj.tech_size).strip()
            invalid_sizes = {"0", "no", "无", "один", "onesize", "none"}
            if tech_size and tech_size.lower() not in invalid_sizes:
                clean_size = self._get_clean_label(tech_size)
                if clean_size:
                    size_segment = f"-{clean_size}"

        return f"{base_spu}{color_segment}{size_segment}"

    def _extract_dimensions(self, raw_attrs) -> dict:
        """提取真实的包装尺寸，加入 200cm 防呆限制"""
        dims = {"length": 10, "width": 10, "height": 10}
        if not raw_attrs:
            return dims

        try:
            if isinstance(raw_attrs, str):
                attrs_dict = json.loads(raw_attrs)
            elif isinstance(raw_attrs, dict):
                attrs_dict = raw_attrs
            elif isinstance(raw_attrs, list):
                attrs_dict = {item['name']: item['value'] for item in raw_attrs if 'name' in item}
            else:
                attrs_dict = json.loads(raw_attrs) if isinstance(raw_attrs, str) else raw_attrs

            if isinstance(attrs_dict, list):
                attrs_dict = {item['name']: item['value'] for item in attrs_dict if 'name' in item}

            key_map = {
                "длина упаковки": "length",
                "ширина упаковки": "width",
                "высота упаковки": "height"
            }

            if isinstance(attrs_dict, dict):
                for k, v in attrs_dict.items():
                    k_lower = str(k).lower()
                    for ru_key, en_key in key_map.items():
                        if ru_key in k_lower:
                            match = re.search(r'\d+', str(v))
                            if match:
                                val = int(match.group())
                                if 0 < val <= 200:
                                    dims[en_key] = val
                                else:
                                    print(f"⚠️ 解析到异常尺寸 {val}，已重置为默认值 10")
        except Exception as e:
            print(f"⚠️ 解析包装尺寸时发生异常: {e}，将使用默认尺寸")

        return dims

    def _convert_attrs_to_wb_format(self, raw_attrs) -> list:
        """将数据库属性安全转为 WB 要求的特征列表"""
        try:
            if not raw_attrs: return []
            data = json.loads(raw_attrs) if isinstance(raw_attrs, str) else raw_attrs
            if isinstance(data, dict):
                return [{"name": str(k), "value": str(v)} for k, v in data.items()]
            return data if isinstance(data, list) else []
        except:
            return []

    # ==========================================
    # Wildberries API 交互模块
    # ==========================================
    def create_wb_card(self, product, sizes) -> bool:
        """提交建品任务，动态注入智能 SPU 和 SKU"""
        url = f"{CONTENT_API_URL}/content/v2/cards/upload"

        spu_vendor_code = self._generate_base_spu(product)

        sizes_payload = []
        for s in sizes:
            smart_sku = self._generate_smart_sku(spu_vendor_code, product, s)
            sizes_payload.append({
                "techSize": str(s.tech_size),
                "wbSize": str(getattr(s, 'wb_size', "") or ""),
                "price": self._calc_price(product.price_rub),
                "skus": [smart_sku]
            })

        if not sizes_payload:
            sizes_payload = [{
                "techSize": "0",
                "wbSize": "",
                "price": self._calc_price(product.price_rub),
                "skus": [f"{spu_vendor_code}-0"]
            }]

        payload = [{
            "subjectID": product.subject_id,
            "variants": [{
                "vendorCode": spu_vendor_code,
                "title": product.title,
                "description": product.description or product.title,
                "brand": product.brand or "Нет бренда",
                "dimensions": self._extract_dimensions(product.attributes_json),
                "characteristics": self._convert_attrs_to_wb_format(product.attributes_json),
                "sizes": sizes_payload
            }]
        }]

        print(f"📦 [发送请求] 正在提交建品数据: 货号 {spu_vendor_code}")

        try:
            resp = requests.post(url, headers=self.headers, json=payload, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if not data.get("error"):
                    print(f"✅ 建品任务提交成功！等待 WB 分配 nmID...")
                    return True
                else:
                    print(f"❌ WB 业务报错: {data.get('errorText')}")
            else:
                print(f"❌ 请求失败 (HTTP {resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"❌ 网络请求异常: {e}")

        return False

    def upload_images_concurrently(self, folder_rel_path, nm_id):
        folder_path = Path(settings.base_data_dir) / str(folder_rel_path)
        if not folder_path.exists() or not folder_path.is_dir():
            return

        images = [str(p) for p in folder_path.glob("*.webp")]
        if not images: return

        url = f"{CONTENT_API_URL}/content/v3/media/file"

        def _upload(img_path, idx):
            if os.path.getsize(img_path) == 0:
                print(f"⚠️ 图片 {os.path.basename(img_path)} 大小为 0 字节，已跳过！")
                return

            hdrs = self.headers.copy()
            hdrs.pop("Content-Type", None)
            hdrs.update({"X-Nm-Id": str(nm_id), "X-Photo-Number": str(idx)})

            with open(img_path, 'rb') as f:
                request_with_retry(
                    url, method="POST", headers=hdrs,
                    files={'uploadfile': (os.path.basename(img_path), f, "image/webp")}
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(_upload, img, i + 1) for i, img in enumerate(images)]
            for _ in as_completed(futures): pass

    def upload_video(self, folder_rel_path, nm_id):
        folder_path = Path(settings.base_data_dir) / str(folder_rel_path)
        videos = glob.glob(os.path.join(folder_path, "*.mp4")) + glob.glob(os.path.join(folder_path, "*.mov"))
        if not videos: return

        video_path = videos[0]
        filename = os.path.basename(video_path)

        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        if size_mb == 0:
            print(f"⚠️ 视频 {filename} 大小为 0 字节，跳过")
            return
        if size_mb > 50:
            print(f"⚠️ 视频 {filename} 超过 50MB 限制，跳过")
            return

        url = f"{CONTENT_API_URL}/content/v3/media/file"
        hdrs = self.headers.copy()
        hdrs.pop("Content-Type", None)
        hdrs.update({"X-Nm-Id": str(nm_id)})

        mime_type = "video/quicktime" if filename.lower().endswith(".mov") else "video/mp4"
        with open(video_path, 'rb') as f:
            request_with_retry(
                url, method="POST", headers=hdrs,
                files={'uploadfile': (filename, f, mime_type)}
            )

    def update_stocks(self, stocks_list):
        if not stocks_list or self.warehouse_id == 0: return
        url = f"{self.marketplace_url}/api/v3/stocks/{self.warehouse_id}"
        request_with_retry(url, method="PUT", headers=self.headers, json={"stocks": stocks_list})

    def set_discounts(self, discount_payload):
        if not discount_payload: return
        url = f"{self.discount_url}/api/v2/upload/task"
        request_with_retry(url, method="POST", headers=self.headers, json={"data": discount_payload})

    # ==========================================
    # 核心异步编排引擎
    # ==========================================
    async def process_publish(self, original_nm_ids, db_session: AsyncSession):
        repo = WBProductRepository(db_session)
        pending_products = {}

        print(f"\n🚀 [阶段 1] 开始批量提交 {len(original_nm_ids)} 个商品的建品请求...")
        for nm_id in original_nm_ids:
            if await repo.is_published(nm_id, self.target_store):
                print(f"⏭️ 商品 {nm_id} 已在该店铺刊登，自动跳过")
                continue

            product = await repo.get_product_by_nm(nm_id)
            if not product: continue

            sizes = await repo.get_sizes_by_product_id(product.id)

            print(f"   ▶️ 正在提交: {product.title} (源ID: {nm_id})")
            is_submitted = await asyncio.to_thread(self.create_wb_card, product, sizes)

            if is_submitted:
                spu_vendor_code = self._generate_base_spu(product)
                pending_products[spu_vendor_code] = product
            else:
                print(f"   ❌ 商品 {nm_id} 建品请求失败")

            await asyncio.sleep(1)

        if not pending_products:
            print("✅ 所有建品已提交完毕，暂无需要等待分配 nmID 的新商品。")
            return

        print(f"\n⏳ [阶段 2] 开始为 {len(pending_products)} 个商品批量查询真实 nmID...")
        real_nm_ids_map = {}
        url = f"{CONTENT_API_URL}/content/v2/get/cards/list"
        max_retries = 12

        for i in range(max_retries):
            unresolved_codes = [vc for vc in pending_products.keys() if vc not in real_nm_ids_map]
            if not unresolved_codes:
                print("   🎉 所有商品的 nmID 已全部获取完毕！")
                break

            payload = {
                "settings": {
                    "cursor": {"limit": 100},
                    "filter": {"withError": False, "vendorCodes": unresolved_codes}
                }
            }

            print(f"   🔄 第 {i + 1}/{max_retries} 次批量查询 (剩余 {len(unresolved_codes)} 个待分配)...")

            try:
                resp = await asyncio.to_thread(requests.post, url, headers=self.headers, json=payload, timeout=20)
                if resp.status_code == 200:
                    cards = resp.json().get("cards", [])
                    for card in cards:
                        vc = card.get("vendorCode")
                        if vc in pending_products and vc not in real_nm_ids_map:
                            real_nm_ids_map[vc] = card.get("nmID")
                            print(f"   ✅ 成功获取到 {vc} 的专属 nmID: {real_nm_ids_map[vc]}")
            except Exception as e:
                print(f"   ⚠️ 批量查询出错: {e}")

            if len(real_nm_ids_map) < len(pending_products):
                await asyncio.sleep(15)

        print(f"\n📸 [阶段 3] 开始为成功获取 nmID 的 {len(real_nm_ids_map)} 个商品同步物料...")
        for vendor_code, real_new_nm_id in real_nm_ids_map.items():
            product = pending_products[vendor_code]
            print(f"   ⚙️ 正在处理: {vendor_code} (目标 nmID: {real_new_nm_id})")

            sizes = await repo.get_sizes_by_product_id(product.id)
            stocks_to_update = []
            for s in sizes:
                smart_sku = self._generate_smart_sku(vendor_code, product, s)
                stocks_to_update.append({"sku": smart_sku, "amount": s.stock_qty})

            fake_price = self._calc_price(product.price_rub)
            discount_payload = [{"nmID": real_new_nm_id, "price": fake_price, "discount": random.randint(40, 70)}]

            try:
                print("      📥 正在上传媒体素材 (图片/视频)...")
                await asyncio.gather(
                    asyncio.to_thread(self.upload_images_concurrently, product.local_folder, real_new_nm_id),
                    asyncio.to_thread(self.upload_video, product.local_folder, real_new_nm_id)
                )

                # 缓冲时间，等待 WB 服务器激活 nmID 和卡片状态
                await asyncio.sleep(3)

                print("      💰 正在同步价格与库存...")
                await asyncio.gather(
                    asyncio.to_thread(self.update_stocks, stocks_to_update),
                    asyncio.to_thread(self.set_discounts, discount_payload)
                )

                # 安全落库
                await repo.record_publish(product.nm_id, self.target_store, real_new_nm_id, vendor_code)

                # 极度安全的文件重命名，防止二次运行导致任务链崩溃
                old_path = os.path.join(settings.base_data_dir, product.local_folder)
                new_path = f"{old_path}_已刊登"
                if os.path.exists(old_path):
                    if os.path.exists(new_path):
                        shutil.rmtree(new_path)
                    os.rename(old_path, new_path)

                print(f"   🎉 商品 {vendor_code} 全流程上架完成！\n")
            except Exception as e:
                print(f"   ❌ 商品 {vendor_code} 物料同步发生异常: {e}\n")

            await asyncio.sleep(2)

        print("🏁 本批次刊登任务全部结束。")