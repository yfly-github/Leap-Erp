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
from app.core.database import settings
from app.repository.wb_product_repository import WBProductRepository
from app.repository.wb_sync_product_repository import SyncWBProductRepository
from app.utils.http_client import request_with_retry, download_file_with_retry


class WBScraperService:
    def __init__(self, supplier_id=None, use_filter=False, min_fb=0, max_fb=9999999, filter_rate=0.0, fbs_only=False):
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
        """强化版 FBS 校验"""
        wh_id = None
        try:
            for s in detail_item.get('sizes', []):
                stocks = s.get('stocks', [])
                if stocks:
                    wh_id = stocks[0].get('wh')
                    if wh_id: break
        except:
            pass
        if wh_id is None:
            wh_id = detail_item.get('wh')
        if not wh_id: return False
        return wh_id not in self.official_fbo_ids if self.official_fbo_ids else False

    # 🌟 融合升级 1：根据采集目标动态选择拦截接口，完美获取对应的真实 Header
    def get_headers_stealth(self, trigger_nm_id=None):
        print("🚀 正在启动浏览器获取授权指纹...")
        co = ChromiumOptions()
        co.set_argument('--no-sandbox')
        if settings.browser_path:
            co.set_browser_path(settings.browser_path)

        page = ChromiumPage(co)

        if self.supplier_id:
            # 店铺模式：访问卖家主页，精准拦截目录 API
            target_url = f"https://www.wildberries.ru/seller/{self.supplier_id}"
            listen_target = 'catalog/sellers'
        elif trigger_nm_id:
            # 单品模式：访问前台商品详情页，精准拦截详情 API
            target_url = f"https://www.wildberries.ru/catalog/{trigger_nm_id}/detail.aspx"
            listen_target = 'v4/detail'
        else:
            target_url = "https://www.wildberries.ru"
            listen_target = 'wildberries.ru'

        page.listen.start(listen_target)
        page.get(target_url)
        res = page.listen.wait(timeout=20)

        if res:
            # 采用你原有的神级克隆手法
            self.headers = {k: v for k, v in res.request.headers.items() if not k.startswith(':')}
            self.headers.update({'Accept-Encoding': 'gzip, deflate', 'x-requested-with': 'XMLHttpRequest'})
            page.quit()
            self.load_basket_config()
            return True

        page.quit()
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

    # 🌟 融合升级 2：强力数学算法兜底 CDN 路由，防止图片 404
    def get_basket_host(self, vol):
        for entry in self.basket_hosts_map:
            if entry['vol_range_from'] <= vol <= entry['vol_range_to']: return entry['host']

        # 当官方配置失效时的最强兜底
        if 0 <= vol <= 143: return "basket-01.wbcontent.net"
        if 144 <= vol <= 287: return "basket-02.wbcontent.net"
        if 288 <= vol <= 431: return "basket-03.wbcontent.net"
        if 432 <= vol <= 719: return "basket-04.wbcontent.net"
        if 720 <= vol <= 1007: return "basket-05.wbcontent.net"
        if 1008 <= vol <= 1061: return "basket-06.wbcontent.net"
        if 1062 <= vol <= 1115: return "basket-07.wbcontent.net"
        if 1116 <= vol <= 1169: return "basket-08.wbcontent.net"
        if 1170 <= vol <= 1313: return "basket-09.wbcontent.net"
        if 1314 <= vol <= 1601: return "basket-10.wbcontent.net"
        if 1602 <= vol <= 1655: return "basket-11.wbcontent.net"
        if 1656 <= vol <= 1919: return "basket-12.wbcontent.net"
        if 1920 <= vol <= 2045: return "basket-13.wbcontent.net"
        if 2046 <= vol <= 2189: return "basket-14.wbcontent.net"
        if 2190 <= vol <= 2405: return "basket-15.wbcontent.net"
        if 2406 <= vol <= 2621: return "basket-16.wbcontent.net"
        if 2622 <= vol <= 2837: return "basket-17.wbcontent.net"
        if 2838 <= vol <= 3053: return "basket-18.wbcontent.net"
        if 3054 <= vol <= 3269: return "basket-19.wbcontent.net"
        if 3270 <= vol <= 3485: return "basket-20.wbcontent.net"
        if 3486 <= vol <= 3701: return "basket-21.wbcontent.net"
        if 3702 <= vol <= 3917: return "basket-22.wbcontent.net"
        return "basket-23.wbcontent.net"

    def get_video_host(self, product_id):
        vol = product_id % 144
        for entry in self.video_hosts_map:
            if entry['vol_range_from'] <= vol <= entry['vol_range_to']: return entry['host']
        basket_num = (vol // 12) + 1
        return f"videonme-basket-{basket_num:02d}.wbbasket.ru"

    def download_video(self, product_id, save_path):
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
                "ffmpeg", "-y", "-user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "15",
                "-i", found_url, "-c", "copy", "-bsf:a", "aac_adtstoasc", "-loglevel", "error", mp4_path
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
            url = (f"https://www.wildberries.ru/__internal/catalog/sellers/v4/catalog?"
                   f"appType=1&curr=rub&dest=-1257786&sort=rate&spp=30"
                   f"&supplier={self.supplier_id}&page={page}")

            resp = request_with_retry(url, headers=self.headers)
            if not resp:
                print(f"❌ 获取第 {page} 页失败，停止翻页")
                break

            try:
                data = resp.json()
            except Exception:
                print(f"⚠️ 第 {page} 页解析 JSON 失败 (可能被风控或已无数据)，安全结束任务。")
                break

            products = data.get('products', [])
            if not products:
                print(f"✅ 扫描结束，第 {page} 页未获取到商品数据")
                break

            print(f"📄 第 {page} 页: 捕获 {len(products)} 个商品")

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = []
                for p in products:
                    if p.get('feedbacks', 0) == 0:
                        no_fb_count += 1
                    else:
                        no_fb_count = 0

                    if no_fb_count >= 20:
                        print(f"🛑 触发终止条件：连续 {no_fb_count} 个无评分，停止扫描")
                        executor.shutdown(wait=False, cancel_futures=True)
                        return

                    futures.append(executor.submit(self.process_group, p.get('id')))

                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"   ⚠️ 商品组处理异常: {e}")

            page += 1

    # 🌟 融合升级 3：跑单品时，把第一个ID传给拦截器打前站
    def run_product_list(self, product_ids):
        if not product_ids: return
        if not self.headers and not self.get_headers_stealth(trigger_nm_id=product_ids[0]): return
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
                    group_qualified = True

                if not group_qualified:
                    print(f"   ⛔ 组内无变体满足条件，跳过整组。")
                    return

            if self.fbs_only:
                has_valid_fbs = False
                if products_map:
                    for pid, p_data in products_map.items():
                        if self.check_is_fbs(p_data):
                            has_valid_fbs = True
                            break

                if not has_valid_fbs:
                    print(f"   ⛔ 该组全为 FBO 或缺货，跳过。")
                    return

            print(f"   ⚡ 开启变体并发，当前组共 {len(variant_ids)} 个变体同时开足马力...")
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(self.process_single_variant, vid, products_map.get(vid)): vid for vid in
                           variant_ids}
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"   ⚠️ 变体采集异常: {e}")

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
                futures = [executor.submit(_download_img, i) for i in range(1, pics + 1)]
                if card_data.get('media', {}).get('has_video', False):
                    futures.append(executor.submit(self.download_video, product_id, save_path))

                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        pass

            self._save_to_db(product_id, card_data, detail_data, save_path)
            print(f"   ✅ 已采集并入库: {product_id}")

        except Exception as e:
            print(f"   ❌ 采集变体 {product_id} 失败: {e}")

    def _save_to_db(self, product_id, card_data, detail_data, save_path):
        rel_dir = os.path.relpath(save_path, settings.base_data_dir).replace('\\', '/')

        attrs = {}
        for group in card_data.get('grouped_options', []):
            for opt in group.get('options', []):
                attrs[opt['name']] = opt['value']
        attrs['description'] = card_data.get('description', '')

        sizes_list = []
        if detail_data:
            for s in detail_data.get('sizes', []):
                sizes_list.append({
                    "tech_size": str(s.get('origName') or s.get('techSize') or "OS"),
                    "stock_qty": sum(st.get('qty', 0) for st in s.get('stocks', []))
                })

        image_files = glob.glob(os.path.join(save_path, "*.webp")) + glob.glob(os.path.join(save_path, "*.jpg"))

        def sort_key(filepath):
            basename = os.path.splitext(os.path.basename(filepath))[0]
            return int(basename) if basename.isdigit() else 999

        image_files.sort(key=sort_key)
        images_list = [os.path.relpath(img, settings.base_data_dir).replace('\\', '/') for img in image_files]
        main_img = images_list[0] if images_list else ""

        video_files = glob.glob(os.path.join(save_path, "*.mp4"))
        video_rel_path = os.path.relpath(video_files[0], settings.base_data_dir).replace('\\',
                                                                                         '/') if video_files else ""

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
                "subject_id": detail_data.get("subjectId", 0),  # 完美提取
                "category": card_data.get('subj_name', ''),
                "price_rub": price_rub,
                "feedbacks": detail_data.get('feedbacks', 0) if detail_data else 0,
                "rating": detail_data.get('reviewRating', 0) if detail_data else 0,
                "is_fbs": self.check_is_fbs(detail_data) if detail_data else False,
                "attributes_json": attrs,
                "local_folder": rel_dir,
                "main_image": main_img,
                "images_json": images_list,
                "video_path": video_rel_path
            }
            with SessionLocal() as db:
                repo = SyncWBProductRepository(db)
                repo.save_product_and_sizes(product_dict, sizes_list)
        except Exception as e:
            print(f"   ❌ 数据库保存失败: {e}")
            raise