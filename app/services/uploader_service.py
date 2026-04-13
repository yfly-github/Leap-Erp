# app/services/uploader_service.py
import os
import random
import glob
import asyncio
import json
import time
import re
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

    def _extract_dimensions(self, raw_attrs) -> dict:
        """
        🌟 智能提取真实的包装尺寸，防止硬编码导致物流费亏损
        """
        dims = {"length": 10, "width": 10, "height": 10}

        if not raw_attrs:
            return dims

        try:
            attrs_dict = {}
            if isinstance(raw_attrs, str):
                attrs_dict = json.loads(raw_attrs)
            elif isinstance(raw_attrs, dict):
                attrs_dict = raw_attrs
            elif isinstance(raw_attrs, list):
                attrs_dict = {item['name']: item['value'] for item in raw_attrs if 'name' in item}

            key_map = {
                "длина упаковки": "length",
                "ширина упаковки": "width",
                "высота упаковки": "height"
            }

            for k, v in attrs_dict.items():
                k_lower = str(k).lower()
                for ru_key, en_key in key_map.items():
                    if ru_key in k_lower:
                        match = re.search(r'\d+', str(v))
                        if match:
                            extracted_val = int(match.group())
                            if extracted_val > 0:
                                dims[en_key] = extracted_val
        except Exception as e:
            print(f"⚠️ 解析包装尺寸时发生异常: {e}，将使用默认尺寸")

        return dims

    def create_wb_card(self, product, sizes) -> bool:
        """
        🌟 核心建品方法：动态注入尺寸、描述与 SKU 条码
        """
        url = "https://content-api.wildberries.ru/content/v2/cards/upload"
        vendor_code = f"SKU-{product.nm_id}"

        characteristics = []
        try:
            raw_attrs = product.attributes_json
            if raw_attrs:
                if isinstance(raw_attrs, str): raw_attrs = json.loads(raw_attrs)
                if isinstance(raw_attrs, dict):
                    characteristics = [{"name": str(k), "value": str(v)} for k, v in raw_attrs.items()]
                elif isinstance(raw_attrs, list):
                    characteristics = raw_attrs
        except Exception as e:
            print(f"⚠️ 属性解析失败: {e}")

        # 🌟 组装尺码数据，预先向 WB 注册我们自定义的 SKU 条码
        sizes_payload = []
        for s in sizes:
            sizes_payload.append({
                "techSize": str(s.tech_size),
                "wbSize": "",
                "price": self._calc_price(product.price_rub),
                "skus": [f"{vendor_code}-{s.tech_size}"]
            })

        # 安全兜底：如果没有获取到尺码（或商品原本就没有尺码），默认生成一个 "0" 尺码
        if not sizes_payload:
            sizes_payload = [{"techSize": "0", "wbSize": "", "price": 9999, "skus": [f"{vendor_code}-0"]}]

        # 提取真实长宽高
        real_dimensions = self._extract_dimensions(product.attributes_json)

        payload = [{
            "subjectID": product.subject_id,  # 动态类目
            "variants": [{
                "vendorCode": vendor_code,
                "title": product.title,
                "description": product.description or product.title,  # 使用真实描述
                "brand": product.brand or "Нет бренда",
                "dimensions": real_dimensions,
                "characteristics": characteristics,
                "sizes": sizes_payload
            }]
        }]

        print(f"📦 [发送请求] 正在提交建品数据: {product.nm_id}")

        try:
            resp = requests.post(url, headers=self.headers, json=payload, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if not data.get("error"):
                    print("✅ 建品任务提交成功！等待 WB 审核生成 nmID...")
                    return True
                else:
                    print(f"❌ WB 业务报错: {data.get('errorText')}")
            else:
                print(f"❌ 请求失败 (HTTP {resp.status_code})")
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
        """
        🌟 修复后的视频上传：移除干扰参数，精准识别格式
        """
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

        # 绝不传递 X-Photo-Number
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

    async def process_publish(self, original_nm_ids, db_session: AsyncSession):
        """
        🌟 高性能批处理核心调度流
        """
        repo = WBProductRepository(db_session)

        # ==========================================
        # 阶段 1：无阻塞批量提交建品任务
        # ==========================================
        pending_products = {}

        print(f"\n🚀 [阶段 1] 开始批量提交 {len(original_nm_ids)} 个商品的建品请求...")
        for nm_id in original_nm_ids:
            if await repo.is_published(nm_id, self.target_store):
                print(f"⏭️ 商品 {nm_id} 已在该店铺刊登，自动跳过")
                continue

            product = await repo.get_product_by_nm(nm_id)
            if not product: continue

            # 获取并传入 sizes
            sizes = await repo.get_sizes_by_product_id(product.id)

            print(f"   ▶️ 正在提交: {product.title} (原始ID: {nm_id})")
            is_submitted = await asyncio.to_thread(self.create_wb_card, product, sizes)

            if is_submitted:
                vendor_code = f"SKU-{product.nm_id}"
                pending_products[vendor_code] = product
            else:
                print(f"   ❌ 商品 {nm_id} 建品请求失败")

            await asyncio.sleep(1)

        if not pending_products:
            print("✅ 所有建品已提交完毕，暂无需要等待分配 nmID 的新商品。")
            return

        # ==========================================
        # 阶段 2：统一批量轮询真实的 nmID
        # ==========================================
        print(f"\n⏳ [阶段 2] 开始为 {len(pending_products)} 个商品批量查询真实 nmID...")
        real_nm_ids_map = {}

        url = "https://content-api.wildberries.ru/content/v2/get/cards/list"
        max_retries = 12

        for i in range(max_retries):
            unresolved_codes = [vc for vc in pending_products.keys() if vc not in real_nm_ids_map]
            if not unresolved_codes:
                print("   🎉 所有商品的 nmID 已全部获取完毕！")
                break

            payload = {
                "settings": {
                    "cursor": {"limit": 100},
                    "filter": {
                        "withError": False,
                        "vendorCodes": unresolved_codes
                    }
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

                # ==========================================
        # 阶段 3：并发上传素材、改价、改库存并更新数据库
        # ==========================================
        print(f"\n📸 [阶段 3] 开始为成功获取 nmID 的 {len(real_nm_ids_map)} 个商品同步物料...")

        for vendor_code, real_new_nm_id in real_nm_ids_map.items():
            product = pending_products[vendor_code]
            print(f"   ⚙️ 正在处理: {vendor_code} (目标 nmID: {real_new_nm_id})")

            sizes = await repo.get_sizes_by_product_id(product.id)
            stocks_to_update = [{"sku": f"{vendor_code}-{s.tech_size}", "amount": s.stock_qty} for s in sizes]
            fake_price = self._calc_price(product.price_rub)
            discount_payload = [{"nmID": real_new_nm_id, "price": fake_price, "discount": random.randint(40, 70)}]

            try:
                # 核心并发网路请求
                await asyncio.gather(
                    asyncio.to_thread(self.upload_images_concurrently, product.local_folder, real_new_nm_id),
                    asyncio.to_thread(self.upload_video, product.local_folder, real_new_nm_id),
                    asyncio.to_thread(self.update_stocks, stocks_to_update),
                    asyncio.to_thread(self.set_discounts, discount_payload)
                )

                await repo.record_publish(product.nm_id, self.target_store, real_new_nm_id, vendor_code)

                # 重命名本地文件夹
                old_path = os.path.join(settings.base_data_dir, product.local_folder)
                new_path = f"{old_path}_已刊登"
                if os.path.exists(old_path) and not os.path.exists(new_path):
                    os.rename(old_path, new_path)

                print(f"   🎉 商品 {vendor_code} 全流程上架完成！\n")
            except Exception as e:
                print(f"   ❌ 商品 {vendor_code} 物料同步发生异常: {e}\n")

            await asyncio.sleep(2)

        print("🏁 本批次刊登任务全部结束。")