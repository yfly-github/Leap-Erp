# app/services/uploader_service.py
import os
import random
import glob
import asyncio
from pathlib import Path

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy.ext.asyncio import AsyncSession  # 🌟 引入用于类型提示

from app.core.database import settings
from app.repository.wb_product_repository import WBProductRepository
from app.utils.http_client import request_with_retry
from app.constants.wb_constants import CONTENT_API_URL


class WBUploaderService:
    # 🌟 改造点1：通过依赖注入，直接接收 token，不关心 token 是从哪查出来的
    def __init__(self, target_store: str, token: str):
        self.target_store = target_store
        self.token = token

        if not self.token:
            raise ValueError(f"缺少店铺 {target_store} 的 Token")

        self.headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.marketplace_url = "https://marketplace-api.wildberries.ru"
        self.discount_url = "https://discounts-prices-api.wildberries.ru"

        # 尝试获取该店铺仓库ID
        self.warehouse_id = self.fetch_warehouse_id()
        # 实时获取计算汇率
        self.dynamic_rate = self.fetch_dynamic_rate(settings.profit_margin)

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

    def upload_images_concurrently(self, folder_rel_path, nm_id):
        folder_path = Path(settings.base_data_dir) / str(folder_rel_path)
        if not folder_path.exists() or not folder_path.is_dir():
            print(f"⚠️ 找不到对应的本地文件夹: {folder_path}")
            return
        images = [str(p) for p in folder_path.glob("*.webp")]

        if not images: return

        url = f"{CONTENT_API_URL}/content/v3/media/file"

        def _upload(img_path, idx):
            hdrs = self.headers.copy()
            hdrs.pop("Content-Type", None)
            hdrs.update({"X-Nm-Id": str(nm_id), "X-Photo-Number": str(idx)})
            with open(img_path, 'rb') as f:
                request_with_retry(
                    url,
                    method="POST",
                    headers=hdrs,
                    files={'uploadfile': (os.path.basename(img_path), f, "image/webp")}
                )

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(_upload, img, i + 1) for i, img in enumerate(images)]
            for _ in as_completed(futures): pass

    def upload_video(self, folder_rel_path, nm_id):
        folder_path = Path(settings.base_data_dir) / str(folder_rel_path)
        videos = glob.glob(os.path.join(folder_path, "*.mp4")) + glob.glob(os.path.join(folder_path, "*.mov"))
        if not videos: return

        video_path = videos[0]
        filename = os.path.basename(video_path)
        if os.path.getsize(video_path) / (1024 * 1024) > 50:
            print(f"⚠️ 视频 {filename} 超过 50MB 限制，跳过")
            return

        url = f"{CONTENT_API_URL}/content/v3/media/file"
        hdrs = self.headers.copy()
        hdrs.pop("Content-Type", None)
        hdrs.update({"X-Nm-Id": str(nm_id), "X-Photo-Number": "1"})

        mime_type = "video/quicktime" if filename.lower().endswith(".mov") else "video/mp4"

        with open(video_path, 'rb') as f:
            request_with_retry(
                url,
                method="POST",
                headers=hdrs,
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

    # 🌟 改造点2：接收外部传入的 db_session，不再自己创建
    async def process_publish(self, original_nm_ids, db_session: AsyncSession):
        repo = WBProductRepository(db_session)

        for nm_id in original_nm_ids:
            if await repo.is_published(nm_id, self.target_store):
                continue

            product = await repo.get_product_by_nm(nm_id)
            if not product:
                continue

            print(f"🚀 正在发布: {product.title} 到 {self.target_store}")

            new_nm_id = nm_id + 88888

            # 依旧保持我们之前优化的防止卡死的做法
            await asyncio.to_thread(self.upload_images_concurrently, product.local_folder, new_nm_id)
            await asyncio.to_thread(self.upload_video, product.local_folder, new_nm_id)

            sizes = await repo.get_sizes_by_product_id(product.id)
            stocks_to_update = []
            my_vendor_code = f"P-{nm_id}"

            for s in sizes:
                sku = f"{my_vendor_code}-{s.tech_size}"
                stocks_to_update.append({"sku": sku, "amount": s.stock_qty})

            await asyncio.to_thread(self.update_stocks, stocks_to_update)

            fake_price = self._calc_price(product.price_rub)
            discount_rate = random.randint(40, 70)

            await asyncio.to_thread(
                self.set_discounts,
                [{"nmID": new_nm_id, "price": fake_price, "discount": discount_rate}]
            )

            await repo.record_publish(nm_id, self.target_store, new_nm_id, my_vendor_code)

            try:
                folder_path = os.path.join(settings.base_data_dir, product.local_folder)
                new_path = f"{folder_path}_已刊登"
                os.rename(folder_path, new_path)
            except Exception as e:
                print(f"📁 文件夹重命名失败: {e}")