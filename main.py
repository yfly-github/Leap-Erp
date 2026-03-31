import logging

import uvicorn

# 导入并初始化日志配置
from app import create_app
from app.core.config import get_settings

from app.core.logger import setup_logging

setup_logging()
logger = logging.getLogger(__name__)
settings = get_settings()

app = create_app(settings)

# main.py
if __name__ == "__main__":
    try:
        # 判断是否开启了 reload，动态决定传入的 app 形式
        is_reload = settings.RELOAD and settings.DEBUG
        app_target = "main:app" if is_reload else app

        uvicorn.run(
            app_target,
            host=settings.HOST,
            port=settings.PORT,
            reload=is_reload,
            log_level=settings.LOG_LEVEL.lower(),
            access_log=False,
        )
    except Exception as e:
        logger.critical(f"系统因不可预见错误退出: {e}", exc_info=True)