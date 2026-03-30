import os
from pathlib import Path


def build_project():
    print("🚀 开始构建 Leap-Erp 模块化项目结构...")

    # ==========================================
    # 1. 定义要创建的目录结构
    # ==========================================
    dirs = [
        "app/configs",
        "app/constants",
        "app/core",
        "app/schemas",
        "app/services",
        "app/utils"
    ]

    for d in dirs:
        os.makedirs(d, exist_ok=True)
        # 为每个包创建 __init__.py
        init_file = Path(d) / "__init__.py"
        if not init_file.exists():
            init_file.touch()

    # 根目录的 app 包也需要 __init__.py
    Path("app/__init__.py").touch(exist_ok=True)

    # ==========================================
    # 2. 定义文件内容 (包含重构后的核心逻辑)
    # ==========================================

    files = {}

    files[".env"] = """
WB_API_TOKEN=请在此处填入你的WB_TOKEN
BASE_DATA_DIR=data
PROFIT_MARGIN=0.95
""".strip()

    files[".gitignore"] = """
__pycache__/
*.pyc
.env
data/
venv/
.idea/
.vscode/
""".strip()

    files["requirements.txt"] = """
requests>=2.31.0
DrissionPage>=4.0.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
""".strip()

    files["app/configs/settings.py"] = """
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    wb_api_token: str = ""
    base_data_dir: str = "data"
    profit_margin: float = 0.95

    class Config:
        env_file = ".env"
        extra = "ignore"

# 全局配置单例
settings = Settings()
""".strip()

    files["app/constants/wb_constants.py"] = """
# WB API 地址
CONTENT_API_URL = "https://content-api.wildberries.ru"
MARKETPLACE_API_URL = "https://marketplace-api.wildberries.ru"
DISCOUNT_API_URL = "https://discounts-prices-api.wildberries.ru"

# 颜色映射表
PARENT_TO_CODE = {
    "бежевый": "BE", "белый": "WH", "голубой": "LB", "желтый": "YL",
    "зеленый": "GR", "коричневый": "BR", "красный": "RD", "оранжевый": "OR",
    "розовый": "PK", "серый": "GY", "синий": "BL", "фиолетовый": "VT", "черный": "BK"
}
""".strip()

    files["app/utils/http_client.py"] = """
import time
import random
import requests

def request_with_retry(url: str, method: str = "GET", headers: dict = None, json_data: dict = None, retries: int = 3, timeout: int = 15, **kwargs):
    '''通用的带重试机制的请求工具'''
    for i in range(retries):
        try:
            if method.upper() == "GET":
                r = requests.get(url, headers=headers, timeout=timeout, **kwargs)
            else:
                r = requests.request(method, url, headers=headers, json=json_data, timeout=timeout, **kwargs)

            if r.status_code in [200, 204]:
                return r
            elif r.status_code == 404:
                return None

            print(f"⚠️ 请求 {url} HTTP {r.status_code}，正在重试 ({i + 1}/{retries})...")
            time.sleep(random.uniform(1.5, 3))
        except Exception as e:
            print(f"⚠️ 请求异常: {e}，正在重试 ({i + 1}/{retries})...")
            time.sleep(random.uniform(2, 4))
    return None
""".strip()

    files["app/services/pricing_service.py"] = """
import requests
from app.configs.settings import settings

class PricingService:
    def __init__(self):
        self.dynamic_rate = self._fetch_dynamic_rate()

    def _fetch_dynamic_rate(self) -> float:
        '''获取实时汇率并结合利润率计算最终系数'''
        url = "https://www.cbr-xml-daily.ru/daily_json.js"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                cny_value = resp.json()['Valute']['CNY']['Value']
                return (1 / cny_value) * settings.profit_margin
        except Exception:
            pass
        return 0.086  # 兜底汇率

    def calculate_smart_price(self, rub_price: int) -> int:
        '''智能分段定价逻辑 (防止小件商品亏本)'''
        if rub_price < 500:
            return int(rub_price * self.dynamic_rate * 1.5)
        elif rub_price < 2000:
            return int(rub_price * self.dynamic_rate * 1.2)
        else:
            return int(rub_price * self.dynamic_rate * 1.1)
""".strip()

    files["app/services/scraper_service.py"] = """
import os
from app.configs.settings import settings
# 这里放置重构后的下载器逻辑 (调用 utils 里的 http_client 等)
# 为保持示例简洁，实际开发中请将原来 downloader_v2.py 的类迁移至此
class WBScraperService:
    def __init__(self):
        self.base_dir = settings.base_data_dir

    def run_supplier_scan(self, sid):
        print(f"正在扫描店铺 {sid} 的数据，保存至 {self.base_dir}...")
        # TODO: 接入原代码逻辑
""".strip()

    files["app/services/uploader_service.py"] = """
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.configs.settings import settings
from app.constants.wb_constants import CONTENT_API_URL
from app.services.pricing_service import PricingService

class WBUploaderService:
    def __init__(self):
        self.headers = {
            "Authorization": settings.wb_api_token,
            "Content-Type": "application/json"
        }
        self.pricing_service = PricingService()

    def process_publish(self, folder_path):
        print(f"正在处理目录 {folder_path} 的刊登任务...")
        # TODO: 接入原代码逻辑中的属性映射和卡片创建
        print(f"当前使用的智能汇率系数为: {self.pricing_service.dynamic_rate:.4f}")

    def upload_images_concurrently(self, images_list, nm_id):
        '''并发传图核心逻辑'''
        print(f"📸 正在并发上传 {len(images_list)} 张图片 -> {nm_id}...")
        url = f"{CONTENT_API_URL}/content/v3/media/file"

        def _upload_single(img_path, idx):
            headers = self.headers.copy()
            headers.pop("Content-Type", None)
            headers["X-Nm-Id"] = str(nm_id)
            headers["X-Photo-Number"] = str(idx)
            # 这里调用 requests 发送文件
            return True

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_upload_single, img, i+1): img for i, img in enumerate(images_list)}
            for future in as_completed(futures):
                pass
        print("✅ 并发传图完成")
""".strip()

    files["main.py"] = """
import sys
from app.services.scraper_service import WBScraperService
from app.services.uploader_service import WBUploaderService

def print_menu():
    print("=" * 60)
    print("   Leap-Erp 跨境智能系统 (企业级模块化版)   ")
    print("=" * 60)
    print("1. [采集] 抓取竞品/店铺数据")
    print("2. [刊登] 自动上传并上架商品")
    print("q. 退出")

def main():
    while True:
        print_menu()
        choice = input("\\n👉 请输入选择: ").strip().lower()

        if choice in ['q', 'exit', 'quit']:
            break

        elif choice == '1':
            scraper = WBScraperService()
            sid = input("请输入 SUPPLIER_ID: ").strip()
            if sid:
                scraper.run_supplier_scan(sid)

        elif choice == '2':
            uploader = WBUploaderService()
            folder = input("📂 拖入要刊登的文件夹: ").strip().replace('"', '').replace("'", "")
            if folder:
                uploader.process_publish(folder)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\\n🛑 强制退出")
""".strip()

    # ==========================================
    # 3. 执行写入操作
    # ==========================================
    for filepath, content in files.items():
        # 确保父目录存在
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        # 写入文件
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content + "\\n")
        print(f"📄 已生成: {filepath}")

    print("\\n🎉 Leap-Erp 项目重构目录生成完毕！")
    print("📌 下一步:")
    print("1. 运行 `pip install -r requirements.txt` 安装依赖")
    print("2. 在 `.env` 文件中填入你的 WB_API_TOKEN")
    print("3. 运行 `python main.py` 启动系统")


if __name__ == "__main__":
    build_project()