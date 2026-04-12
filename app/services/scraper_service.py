import asyncio
import os
import json
import time
import random
import glob
import subprocess
import shutil
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from DrissionPage import ChromiumPage, ChromiumOptions

from app.configs.database import SessionLocal
from app.core.database import settings, AsyncSessionLocal
from app.repository.wb_product_repository import WBProductRepository
from app.repository.wb_sync_product_repository import SyncWBProductRepository
from app.utils.http_client import request_with_retry, download_file_with_retry


class WBScraperService:
    def __init__(self, supplier_id=None, use_filter=False, min_fb=0,max_fb=9999999, filter_rate=0.0, fbs_only=False):
        self.supplier_id = supplier_id
        self.base_dir = settings.base_data_dir

        # 智能识别目录，与V2保持一致
        default_name = str(supplier_id) if supplier_id else "mixed_products"
        published_name = f"{default_name}_已刊登"
        if os.path.exists(os.path.join(self.base_dir, published_name)):
            self.save_subdir = published_name
        else:
            self.save_subdir = default_name

        self.basket_hosts_map = []
        self.video_hosts_map = []
        self.headers = None
        self.basket_config_loaded = False

        self.filter_enabled = use_filter
        self.min_feedbacks = min_fb
        self.max_feedbacks = max_fb
        self.min_rating = filter_rate
        self.fbs_only = fbs_only
        self.official_fbo_ids = set()

        if self.fbs_only:
            self.load_official_warehouses()

    def load_official_warehouses(self):
        url = "https://marketplace-api.wildberries.ru/api/v3/offices"
        token = list(settings.tokens_dict.values())[0] if settings.tokens_dict else ""
        headers = {"Authorization": token}
        resp = request_with_retry(url, headers=headers)
        if resp:
            for item in resp.json():
                if item.get('deliveryType') == 1:
                    self.official_fbo_ids.add(item['id'])

    def check_is_fbs(self, detail_item):
        """强化版 FBS 校验 (合并自 downloader_v2)"""
        wh_id = None
        try:
            for s in detail_item.get('sizes', []):
                stocks = s.get('stocks', [])
                if stocks:
                    wh_id = stocks[0].get('wh')
                    if wh_id: break
        except:
            pass
        # 兜底直接读外层
        if wh_id is None:
            wh_id = detail_item.get('wh')
        if not wh_id: return False
        return wh_id not in self.official_fbo_ids if self.official_fbo_ids else False

    def get_headers_stealth(self):
        print("🚀 正在启动浏览器获取授权指纹...")
        co = ChromiumOptions()
        co.set_argument('--no-sandbox')
        if settings.browser_path:
            co.set_browser_path(settings.browser_path)

        page = ChromiumPage(co)
        target_url = f"https://www.wildberries.ru/seller/{self.supplier_id}" if self.supplier_id else "https://www.wildberries.ru"
        page.listen.start('catalog/sellers' if self.supplier_id else 'wildberries.ru')
        page.get(target_url)
        res = page.listen.wait(timeout=20)

        if res:
            self.headers = {k: v for k, v in res.request.headers.items() if not k.startswith(':')}
            self.headers.update({'Accept-Encoding': 'gzip, deflate', 'x-requested-with': 'XMLHttpRequest'})
            page.quit()
            self.load_basket_config()
            return True
        return False

    def load_basket_config(self):
        url = "https://cdn.wbbasket.ru/api/v3/upstreams"
        resp = request_with_retry(url, headers={'User-Agent': 'Mozilla/5.0'})
        if resp:
            data = resp.json()
            route_map = data.get('mediabasket_route_map', []) or data.get('origin', {}).get('mediabasket_route_map', [])
            video_route = data.get('videonme_route_map', []) or data.get('origin', {}).get('videonme_route_map', [])

            if route_map: self.basket_hosts_map = route_map[0].get('hosts', [])
            if video_route: self.video_hosts_map = video_route[0].get('hosts', [])
            self.basket_config_loaded = True

    def get_basket_host(self, vol):
        for entry in self.basket_hosts_map:
            if entry['vol_range_from'] <= vol <= entry['vol_range_to']: return entry['host']
        if 0 <= vol <= 143: return "basket-01.wbbasket.ru"
        if 144 <= vol <= 287: return "basket-02.wbbasket.ru"
        return "basket-29.wbbasket.ru"

    def get_video_host(self, product_id):
        vol = product_id % 144
        for entry in self.video_hosts_map:
            if entry['vol_range_from'] <= vol <= entry['vol_range_to']: return entry['host']
        basket_num = (vol // 12) + 1
        return f"videonme-basket-{basket_num:02d}.wbbasket.ru"

    def download_video(self, product_id, save_path):
        """新增：视频探测与FFmpeg下载 (合并自 downloader_v2)"""
        vol, part = product_id % 144, product_id // 10000
        host = self.get_video_host(product_id)
        base_url = f"https://{host}/vol{vol}/part{part}/{product_id}/hls"

        qualities = ["1440p", "1080p", "720p", "480p", "360p"]
        found_url = None

        print(f"   🎬 检测到视频，正在探测有效画质...")
        for q in qualities:
            test_url = f"{base_url}/{q}/index.m3u8"
            resp = request_with_retry(test_url, headers=self.headers)
            if resp and resp.status_code == 200:
                found_url = test_url
                print(f"   ✅ 成功获取画质: {q}")
                break

        if not found_url: return

        with open(os.path.join(save_path, "video.txt"), "w", encoding="utf-8") as f:
            f.write(found_url)

        mp4_path = os.path.join(save_path, "video.mp4")
        if shutil.which("ffmpeg"):
            print(f"   ⬇️ 正在调用 FFmpeg 下载 MP4...")
            cmd = [
                "ffmpeg", "-y",
                "-user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "15",  # 最大重试等待时间（秒）
                "-i", found_url,
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                "-loglevel", "error",
                mp4_path
            ]
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
                print(f"   🎉 视频下载成功")
            except Exception as e:
                print(f"   ⚠️ FFmpeg 下载异常: {e}")

    def run_supplier_scan(self):
        if not self.headers and not self.get_headers_stealth(): return
        print(f"🔎 开始扫描店铺: {self.supplier_id}")
        page, no_fb_count = 1, 0

        while True:
            # 补全 dest 和 curr 等关键参数
            url = (f"https://www.wildberries.ru/__internal/catalog/sellers/v4/catalog?"
                   f"appType=1&curr=rub&dest=-1257786&sort=rate&spp=30"
                   f"&supplier={self.supplier_id}&page={page}")

            resp = request_with_retry(url, headers=self.headers)

            if not resp:
                print(f"❌ 获取第 {page} 页失败，停止翻页")
                break

            products = resp.json().get('products', [])
            if not products:
                print(f"✅ 扫描结束，第 {page} 页未获取到商品数据")
                break

            print(f"📄 第 {page} 页: 捕获 {len(products)} 个商品")

            # 🚀 优化：使用线程池并发处理当前页的所有商品组
            from concurrent.futures import ThreadPoolExecutor, as_completed

            # 这里控制外层并发数为 5。结合底层的并发，速度会非常快。
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = []
                for p in products:
                    if p.get('feedbacks', 0) == 0:
                        no_fb_count += 1
                    else:
                        no_fb_count = 0

                    if no_fb_count >= 20:
                        print(f"🛑 触发终止条件：连续 {no_fb_count} 个无评分，停止扫描")
                        # ⚠️ 关键操作：触发终止时，取消线程池中还在排队的任务，然后直接结束方法
                        executor.shutdown(wait=False, cancel_futures=True)
                        return

                    # 提交并发任务：处理当前商品组
                    futures.append(executor.submit(self.process_group, p.get('id')))

                # 阻塞等待：必须等当前页的所有商品（及其下属变体、图片）全部下完，再翻下一页
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"   ⚠️ 商品组处理异常: {e}")

            page += 1

    def run_product_list(self, product_ids):
        if not self.headers and not self.get_headers_stealth(): return
        for pid in product_ids:
            self.process_group(pid)

    def process_group(self, input_id):
        vol, part = input_id // 100000, input_id // 1000
        host = self.get_basket_host(vol)
        info_url = f"https://{host}/vol{vol}/part{part}/{input_id}/info/ru/card.json"

        r = request_with_retry(info_url, headers=self.headers)
        if not r: return self.process_single_variant(input_id)

        try:
            card_data = r.json()
            variant_ids = [int(x) for x in card_data.get('colors', [])] or [input_id]

            nm_param = ';'.join(map(str, variant_ids))

            detail_api = (f"https://www.wildberries.ru/__internal/card/cards/v4/detail?"
                          f"appType=1&curr=rub&dest=-1257786&spp=30&lang=ru&nm={nm_param}")

            r_batch = request_with_retry(detail_api, headers=self.headers)
            products_map = {p['id']: p for p in r_batch.json().get('products', [])} if r_batch else {}

            # ================= 恢复：[过滤逻辑] 整组判断 =================
            if self.filter_enabled:
                group_qualified = False
                if products_map:
                    for pid, p_data in products_map.items():
                        fb = p_data.get('feedbacks', 0)
                        rate = p_data.get('reviewRating', 0)
                        if self.min_feedbacks <= fb <= self.max_feedbacks and rate >= self.min_rating:
                            group_qualified = True
                            break


                else:
                    group_qualified = True  # 宽容模式：获取不到详情时放行

                if not group_qualified:
                    print(f"   ⛔ 组内无变体满足条件 (评价>={self.min_feedbacks}, 评分>={self.min_rating})，跳过整组。")
                    return  # 🔴 不达标，直接结束方法，不下载

            # ================= 恢复：[FBS 过滤逻辑] 整组判断 =================
            if self.fbs_only:
                has_valid_fbs = False
                if products_map:
                    for pid, p_data in products_map.items():
                        if self.check_is_fbs(p_data):
                            has_valid_fbs = True
                            break

                if not has_valid_fbs:
                    print(f"   ⛔ 该组所有变体均不满足 FBS 条件 (全为 FBO 或 缺货)，跳过下载。")
                    return  # 🔴 不达标，直接结束方法，不下载
            # ==============================================================

            # 🚀 优化点：开启变体级并发
            from concurrent.futures import ThreadPoolExecutor, as_completed
            print(f"   ⚡ 开启变体并发，当前组共 {len(variant_ids)} 个变体同时开足马力...")

            # 使用最大 5 个工作线程并发处理变体，你可以根据网络情况调大或调小 max_workers
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {
                    executor.submit(self.process_single_variant, vid, products_map.get(vid)): vid
                    for vid in variant_ids
                }
                for future in as_completed(futures):
                    try:
                        # 阻塞直到该变体处理完成
                        future.result()
                    except Exception as e:
                        vid = futures[future]
                        print(f"   ⚠️ 变体 {vid} 采集异常: {e}")

        except Exception as e:
            print(f"   ⚠️ 分析变体组出现异常: {e}")
            self.process_single_variant(input_id)

    def process_single_variant(self, product_id, cached_detail=None):
        save_path = os.path.join(self.base_dir, self.save_subdir, str(product_id))
        published_path = os.path.join(self.base_dir, self.save_subdir, f"{product_id}_已刊登")

        if os.path.exists(published_path) or (os.path.exists(os.path.join(save_path, 'card.json')) and os.path.exists(
                os.path.join(save_path, 'detail.json'))):
            return

        os.makedirs(save_path, exist_ok=True)
        vol, part = product_id // 100000, product_id // 1000
        host = self.get_basket_host(vol)
        base_url = f"https://{host}/vol{vol}/part{part}/{product_id}"

        try:
            r_card = request_with_retry(f"{base_url}/info/ru/card.json", headers=self.headers)
            if not r_card: return
            card_data = r_card.json()
            with open(os.path.join(save_path, 'card.json'), 'w', encoding='utf-8') as f:
                json.dump(card_data, f, ensure_ascii=False, indent=4)

            detail_data = cached_detail
            if not detail_data:
                r_det = request_with_retry(
                    f"https://www.wildberries.ru/__internal/card/cards/v4/detail?nm={product_id}", headers=self.headers)
                if r_det: detail_data = r_det.json().get('products', [{}])[0]

            if detail_data:
                with open(os.path.join(save_path, 'detail.json'), 'w', encoding='utf-8') as f:
                    json.dump(detail_data, f, ensure_ascii=False, indent=4)

            pics = card_data.get('media', {}).get('photo_count', 5)

            def _download_img(i):
                img_url = f"{base_url}/images/big/{i}.webp"
                img_path = os.path.join(save_path, f"{i}.webp")
                download_file_with_retry(img_url, img_path, headers=self.headers)

            print(f"   📥 正在并发下载 {pics} 张图片...")
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = []

                # 1. 提交所有图片下载任务
                for i in range(1, pics + 1):
                    futures.append(executor.submit(_download_img, i))

                # 2. 提交视频下载任务 (如果有)
                if card_data.get('media', {}).get('has_video', False):
                    futures.append(executor.submit(self.download_video, product_id, save_path))

                # 3. 阻塞等待当前变体的所有图和视频下载完成
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"   ⚠️ 媒体下载子任务异常: {e}")


            #     executor.map(_download_img, range(1, pics + 1))
            #
            # # 下载视频逻辑
            # if card_data.get('media', {}).get('has_video', False):
            #     self.download_video(product_id, save_path)

            self._save_to_db(product_id, card_data, detail_data, save_path)
            print(f"   ✅ 已采集并入库: {product_id}")

        except Exception as e:
            print(f"   ❌ 采集变体 {product_id} 失败: {e}")

    def _save_to_db(self, product_id, card_data, detail_data, save_path):
        rel_dir = os.path.relpath(save_path, settings.base_data_dir).replace('\\', '/')

        # 1. 提取属性
        attrs = {}
        for group in card_data.get('grouped_options', []):
            for opt in group.get('options', []):
                attrs[opt['name']] = opt['value']
        attrs['description'] = card_data.get('description', '')

        # 2. 提取尺寸与库存
        sizes_list = []
        if detail_data:
            for s in detail_data.get('sizes', []):
                sizes_list.append({
                    "tech_size": str(s.get('origName') or s.get('techSize') or "OS"),
                    "stock_qty": sum(st.get('qty', 0) for st in s.get('stocks', []))
                })

        # ================= [新增] 扫描图片和视频文件 =================
        import glob

        # 获取所有图片并按数字顺序排序 (1.webp, 2.webp...)
        image_files = glob.glob(os.path.join(save_path, "*.webp")) + glob.glob(os.path.join(save_path, "*.jpg"))

        def sort_key(filepath):
            basename = os.path.splitext(os.path.basename(filepath))[0]
            return int(basename) if basename.isdigit() else 999

        image_files.sort(key=sort_key)

        # 转换为相对路径列表
        images_list = [os.path.relpath(img, settings.base_data_dir).replace('\\', '/') for img in image_files]
        main_img = images_list[0] if images_list else ""

        # 获取视频文件
        video_files = glob.glob(os.path.join(save_path, "*.mp4"))
        video_rel_path = os.path.relpath(video_files[0], settings.base_data_dir).replace('\\',
                                                                                         '/') if video_files else ""
        # ==========================================================

        # 【修复】安全提取 sizes 中的价格
        price_rub = 0
        if detail_data and detail_data.get('sizes'):
            price_rub = detail_data.get('sizes')[0].get('price', {}).get('product', 0) / 100

        try:
            product_dict = {
                "supplier_id": card_data.get('selling', {}).get('supplier_id', self.supplier_id or 0),
                "imt_id": card_data.get('imt_id'),
                "nm_id": product_id,
                "title": card_data.get('imt_name', ''),
                "brand": card_data.get('selling', {}).get('brand_name', ''),
                "subject_id": detail_data.get("subjectId", 0),
                "category": card_data.get('subj_name', ''),
                "price_rub": price_rub,
                "feedbacks": detail_data.get('feedbacks', 0) if detail_data else 0,
                "rating": detail_data.get('reviewRating', 0) if detail_data else 0,
                "is_fbs": self.check_is_fbs(detail_data) if detail_data else False,
                "attributes_json": attrs,
                "local_folder": rel_dir,

                # ===== [更新] 媒体资产存入字典 =====
                "main_image": main_img,
                "images_json": images_list,  # 需要 repository 和 entity 支持该字段
                "video_path": video_rel_path  # 需要 repository 和 entity 支持该字段
            }
            with SessionLocal() as db:
                repo = SyncWBProductRepository(db)
                repo.save_product_and_sizes(product_dict, sizes_list)
        except Exception as e:
            print(f"   ❌ 数据库保存失败: {e}")
            raise