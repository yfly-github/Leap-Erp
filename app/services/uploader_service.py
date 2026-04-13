# app/services/uploader_service.py
import os
import random
import glob
import asyncio
import json
import time
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

    def create_wb_card(self, product) -> bool:
        """
        🌟 核心方法：提交建品任务 (返回布尔值，不再返回假的 nmID)
        """
        url = "https://content-api.wildberries.ru/content/v2/cards/upload"

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

        payload = [{
            "subjectID": product.subject_id,
            "variants": [{
                "vendorCode": f"P-{product.nm_id}",
                "title": product.title,
                "description": product.title,
                "brand": product.brand or "Нет бренда",
                "dimensions": {"length": 10, "width": 10, "height": 10},
                "characteristics": characteristics
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

    def _wait_for_real_nm_id(self, vendor_code: str, max_retries: int = 15, delay: int = 10):
        """
        🌟 轮询查询接口：等待 WB 后台分配真实的 nmID
        """
        url = "https://content-api.wildberries.ru/content/v2/get/cards/list"

        # 🚀 修复点 1：使用 vendorCodes 精确匹配，避开 textSearch 的索引延迟
        payload = {
            "settings": {
                "cursor": {"limit": 10},
                "filter": {
                    "withError": False,
                    "vendorCodes": [vendor_code]  # 把 textSearch 换成了 vendorCodes 数组
                }
            }
        }

        print(f"⏳ 正在等待 WB 生成真实的 nmID (条码: {vendor_code})...")

        # 🚀 修复点 2：增加了默认重试次数 (15 * 10 = 等待 150 秒)，防止 WB 偶尔处理缓慢
        for i in range(max_retries):
            time.sleep(delay)
            print(f"   🔄 第 {i + 1}/{max_retries} 次查询...")
            try:
                resp = requests.post(url, headers=self.headers, json=payload, timeout=15)
                if resp.status_code == 200:
                    cards = resp.json().get("cards", [])
                    if cards:
                        real_nm_id = cards[0].get("nmID")
                        print(f"🎉 成功获取到 WB 真实 nmID: {real_nm_id}")
                        return real_nm_id
            except Exception as e:
                print(f"   ⚠️ 查询出错: {e}")

        print("❌ 等待超时，WB 尚未生成 nmID，请稍后再试。")
        return None

    def upload_images_concurrently(self, folder_rel_path, nm_id):
        folder_path = Path(settings.base_data_dir) / str(folder_rel_path)
        if not folder_path.exists() or not folder_path.is_dir():
            return
        images = [str(p) for p in folder_path.glob("*.webp")]
        if not images: return

        url = f"{CONTENT_API_URL}/content/v3/media/file"

        def _upload(img_path, idx):
            # 🌟 拦截并过滤大小为 0 的损坏图片
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

        # 建议并发数设为 1 或 2，防止触发 429 频率限制
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(_upload, img, i + 1) for i, img in enumerate(images)]
            for _ in as_completed(futures): pass

    def upload_video(self, folder_rel_path, nm_id):
        folder_path = Path(settings.base_data_dir) / str(folder_rel_path)
        videos = glob.glob(os.path.join(folder_path, "*.mp4")) + glob.glob(os.path.join(folder_path, "*.mov"))
        if not videos: return

        video_path = videos[0]
        filename = os.path.basename(video_path)

        # 🌟 拦截并过滤大小为 0 的损坏视频，或过大的视频
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
        hdrs.update({"X-Nm-Id": str(nm_id), "X-Photo-Number": "1"})

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
        repo = WBProductRepository(db_session)

        # ==========================================
        # 阶段 1：无阻塞批量提交建品任务
        # ==========================================
        pending_products = {}  # 记录成功提交等待分配 nmID 的商品字典 {vendor_code: product}

        print(f"\n🚀 [阶段 1] 开始批量提交 {len(original_nm_ids)} 个商品的建品请求...")
        for nm_id in original_nm_ids:
            # 1. 检查是否已经刊登过
            if await repo.is_published(nm_id, self.target_store):
                print(f"⏭️ 商品 {nm_id} 已在该店铺刊登，自动跳过")
                continue

            # 2. 查询商品数据
            product = await repo.get_product_by_nm(nm_id)
            if not product: continue

            print(f"   ▶️ 正在提交: {product.title} (原始ID: {nm_id})")

            # 3. 提交建品请求
            is_submitted = await asyncio.to_thread(self.create_wb_card, product)

            if is_submitted:
                vendor_code = f"P-{product.nm_id}"
                pending_products[vendor_code] = product
            else:
                print(f"   ❌ 商品 {nm_id} 建品请求失败")

            # 短暂休息 1 秒，防止短时间内高频发包触发 WB API 429 限制
            await asyncio.sleep(1)

        if not pending_products:
            print("✅ 所有建品已提交完毕，暂无需要等待分配 nmID 的新商品。")
            return

        # ==========================================
        # 阶段 2：统一批量轮询真实的 nmID
        # ==========================================
        print(f"\n⏳ [阶段 2] 开始为 {len(pending_products)} 个商品批量查询真实 nmID...")
        real_nm_ids_map = {}  # 存储获取到的 {vendor_code: real_nm_id}

        url = "https://content-api.wildberries.ru/content/v2/get/cards/list"
        max_retries = 12  # 12 次 * 15秒 = 最多等待 3 分钟

        for i in range(max_retries):
            # 筛选出还没查到 nmID 的条码
            unresolved_codes = [vc for vc in pending_products.keys() if vc not in real_nm_ids_map]
            if not unresolved_codes:
                print("   🎉 所有商品的 nmID 已全部获取完毕！")
                break  # 提前结束轮询

            # 构造批量查询的 payload，使用 vendorCodes 数组精确匹配
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
                # 因为 requests 是同步库，所以依然用 to_thread 包装防止阻塞主线程
                resp = await asyncio.to_thread(requests.post, url, headers=self.headers, json=payload, timeout=20)
                if resp.status_code == 200:
                    cards = resp.json().get("cards", [])
                    for card in cards:
                        vc = card.get("vendorCode")
                        # 确保查回来的 code 在我们的等待列表里
                        if vc in pending_products and vc not in real_nm_ids_map:
                            real_nm_ids_map[vc] = card.get("nmID")
                            print(f"   ✅ 成功获取到 {vc} 的专属 nmID: {real_nm_ids_map[vc]}")
            except Exception as e:
                print(f"   ⚠️ 批量查询出错: {e}")

            # 如果还没全查到，等待 15 秒后再发起下一轮批量查询
            if len(real_nm_ids_map) < len(pending_products):
                await asyncio.sleep(15)

                # ==========================================
        # 阶段 3：并发上传素材、改价、改库存并更新数据库
        # ==========================================
        print(f"\n📸 [阶段 3] 开始为成功获取 nmID 的 {len(real_nm_ids_map)} 个商品同步物料...")

        for vendor_code, real_new_nm_id in real_nm_ids_map.items():
            product = pending_products[vendor_code]
            print(f"   ⚙️ 正在处理: {vendor_code} (目标 nmID: {real_new_nm_id})")

            # 准备库存和价格数据
            sizes = await repo.get_sizes_by_product_id(product.id)
            stocks_to_update = [{"sku": f"{vendor_code}-{s.tech_size}", "amount": s.stock_qty} for s in sizes]
            fake_price = self._calc_price(product.price_rub)
            discount_payload = [{"nmID": real_new_nm_id, "price": fake_price, "discount": random.randint(40, 70)}]

            try:
                # 🌟 核心并发区：同时发起传图、传视频、同步库存、改价格的网络请求
                await asyncio.gather(
                    asyncio.to_thread(self.upload_images_concurrently, product.local_folder, real_new_nm_id),
                    asyncio.to_thread(self.upload_video, product.local_folder, real_new_nm_id),
                    asyncio.to_thread(self.update_stocks, stocks_to_update),
                    asyncio.to_thread(self.set_discounts, discount_payload)
                )

                # 更新数据库记录
                await repo.record_publish(product.nm_id, self.target_store, real_new_nm_id, vendor_code)

                # 重命名本地文件夹，标记为已刊登
                old_path = os.path.join(settings.base_data_dir, product.local_folder)
                new_path = f"{old_path}_已刊登"
                if os.path.exists(old_path) and not os.path.exists(new_path):
                    os.rename(old_path, new_path)

                print(f"   🎉 商品 {vendor_code} 全流程上架完成！\n")
            except Exception as e:
                print(f"   ❌ 商品 {vendor_code} 物料同步发生异常: {e}\n")

            # 每个商品处理完后缓冲 2 秒，保护下游系统
            await asyncio.sleep(2)

        print("🏁 本批次刊登任务全部结束。")