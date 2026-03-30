import os
from app.configs.settings import settings

class MediaPathManager:
    @staticmethod
    def get_local_path(relative_path: str) -> str:
        """获取本地磁盘绝对路径，用于保存文件、刊登时读取文件"""
        return os.path.normpath(os.path.join(settings.base_data_dir, relative_path))

    @staticmethod
    def get_web_url(relative_path: str) -> str:
        """获取可访问的 URL，用于可视化页面展示"""
        if settings.asset_host:
            # 云端模式：拼接 CDN 地址
            return f"{settings.asset_host.rstrip('/')}/{relative_path}"
        else:
            # 本地模式：返回绝对路径或由 FastAPI 提供的静态资源路由
            return f"/assets/{relative_path}"