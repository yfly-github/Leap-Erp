import os

from pydantic_settings import BaseSettings
import json

class Settings(BaseSettings):
    wb_api_tokens: str = "{}"
    profit_margin: float = 0.95
    browser_path: str = ""
    database_url: str = "mysql+pymysql://root:123456@127.0.0.1:3306/leap_erp?charset=utf8mb4"
    # 1. 物理存储根目录 (用于 Python 读写文件)
    base_data_dir: str = os.path.join(os.getcwd(), "data")

    # 2. 资源访问前缀 (用于前端显示或刊登引用)
    # 本地开发时可以留空或给相对路径，上线后改为 https://oss-bucket.com/
    asset_host: str = ""

    @property
    def tokens_dict(self) -> dict:
        try:
            return json.loads(self.wb_api_tokens)
        except Exception:
            return {}

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
