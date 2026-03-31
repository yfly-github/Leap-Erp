# app/core/config.py
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 获取项目根目录
BASE_PATH = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    # ========== 应用配置 ==========
    PROJECT_NAME: str = Field(default="Project Name", description="项目名称")
    VERSION: str = Field(default="v1.0.0", description="项目版本号")
    DESCRIPTION: str = Field(default="Project Description", description="项目描述")

    # ========== 服务器配置开始 ==========
    HOST: str = Field(default="0.0.0.0", description="服务器监听地址")
    PORT: int = Field(default=8088, description="服务器监听端口")
    RELOAD: bool = Field(default=False, description="是否启用热重载")
    ENVIRONMENT: str = Field(default="development", description="运行环境：development, testing, production")
    DEBUG: bool = Field(default=False, description="是否启用调试模式")
    BACKEND_CORS_ORIGINS: List[str] = Field(default_factory=list, description="允许的CORS源列表")

    # ========== API配置 ==========
    API_V1_STR: str = Field(default="/api/v1", description="API v1版本前缀")
    DOCS_URL: Optional[str] = Field(default="/docs", description="Swagger UI文档URL")
    REDOC_URL: Optional[str] = Field(default="/redoc", description="ReDoc文档URL")
    OPENAPI_URL: Optional[str] = Field(default="/openapi.json", description="OpenAPI JSON URL")
    ROUTER_WHITELIST_ENABLED: bool = Field(default=True, description="是否启用路由白名单")
    ROUTER_WHITELIST: list[str] = ["/api/v1/signature/generic"]
    ENABLE_REQUEST_LOGGING: bool = Field(default=True, description="启用请求日志")
    # ========= API配置结束 ==========

    # ======== 日志配置开始 ==========
    LOG_FILE_PATH: str = Field(default=str(BASE_PATH / "logs" / "app.log"), description="配置日志文件")
    LOG_LEVEL: str = Field(default="INFO", description="日志级别：DEBUG, INFO, WARNING, ERROR, CRITICAL")
    LOG_FORMAT: str = Field(default="default", description="日志格式：default, json")
    LOG_TO_FILE: bool = Field(default=True, description="是否记录到文件")
    # ========= 日志配置结束 ==========

    # ============ 数据库 & Redis 配置开始 ==========
    MYSQL_HOST: str = Field(default="localhost", description="MySQL主机")
    MYSQL_PORT: int = Field(default=3306, ge=1, le=65535, description="MySQL端口")
    MYSQL_USER: str = Field(default="root", description="MySQL用户名")
    MYSQL_PASSWORD: str = Field(default="", description="MySQL密码")
    MYSQL_DB: str = Field(default="ai_factory", description="MySQL数据库名")
    MYSQL_CHARSET: str = Field(default="utf8mb4", description="MySQL字符集")

    base_data_dir: str = Field(default=str(BASE_PATH / "data"), description="数据存储目录")

    browser_path: str = Field(default=f"C:\Program Files\Google\Chrome\Application\chrome.exe", description="浏览器路径")


    @computed_field
    @property
    def DATABASE_URL_ASYNC(self) -> str:
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}"
            f"?charset={self.MYSQL_CHARSET}"
        )

    @computed_field
    @property
    def DATABASE_URL_SYNC(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}"
            f"?charset={self.MYSQL_CHARSET}"
        )
    # =========== 数据库 & Redis 配置结束 ==========

    # ========== 阿里云OSS配置开始 ==========
    ALIYUN_OSS_ACCESS_KEY_ID: str = Field("", description="OSS访问密钥ID")
    ALIYUN_OSS_ACCESS_KEY_SECRET: str = Field("", description="OSS访问密钥Secret")
    ALIYUN_OSS_ENDPOINT: str = Field("", description="OSS端点")
    ALIYUN_OSS_BUCKET_NAME: str = Field("", description="OSS存储桶名称")
    ALIYUN_OSS_FOLDER_PATH: str = Field("infringement_library/", description="OSS文件夹路径")
    # ========== 阿里云OSS配置结束 ==========



    #  Pydantic Settings 魔法配置：自动寻找并解析 .env 文件
    model_config = SettingsConfigDict(
        # 按照优先级加载：优先读带环境变量后缀的，没有就兜底读 .env
        env_file=(".env", f".env.{os.getenv('APP_ENV', os.getenv('ENVIRONMENT', 'dev'))}"),
        env_file_encoding="utf-8",
        extra="ignore"
    )
    # ========== 服务器配置结束 ==========


# ====================================================================
# 全局单例缓存 (FastAPI 官方推荐实践)
# ====================================================================
@lru_cache()
def get_settings() -> Settings:
    """
    使用 lru_cache 装饰器，确保无论调用多少次，都只在第一次时实例化并加载配置文件。
    """
    settings = Settings()
    print(f"🔧 当前配置: PORT={settings.PORT}, ENVIRONMENT={settings.ENVIRONMENT}")
    return settings