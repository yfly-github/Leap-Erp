# app/utils/logger.py
"""
日志配置模块
配置应用的日志系统

⚠️ 注意：此模块只定义配置逻辑，绝不自动执行。
必须在程序入口（如 main.py 或 tasks.py）的最顶部显式调用 setup_logging()。
其他普通的业务文件，直接使用原生 logging.getLogger(__name__) 即可。
"""
import logging
import sys
import os
from logging.handlers import RotatingFileHandler

from app.core.config import get_settings


def setup_logging():
    """
    配置全局日志系统
    根据环境配置不同的日志格式和处理器
    """
    settings = get_settings()

    # 创建/获取根日志记录器
    root_logger = logging.getLogger()
    # 动态设置全局日志级别
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    # 清除现有的处理器，防止热重载或多次调用时发生重复打印
    if root_logger.handlers:
        root_logger.handlers.clear()

    # 创建格式化器
    # 优先使用 JSON 格式（如果配置），否则使用标准文本格式
    if settings.LOG_FORMAT == "json":
        try:
            from app.utils.json_log_formatter import JSONLogFormatter
            formatter = JSONLogFormatter()
        except ImportError:
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
    else:
        # 文本格式日志
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    # 1. 配置控制台处理器 (Console)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    root_logger.addHandler(console_handler)

    # 2. 配置文件处理器 (File)
    if settings.LOG_TO_FILE:
        # 🛡️ 健壮性优化：确保日志存放的目录存在，防止 FileNotFoundError
        log_dir = os.path.dirname(settings.LOG_FILE_PATH)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        print(f"📄 全局日志已挂载，写入路径：{settings.LOG_FILE_PATH}")

        file_handler = RotatingFileHandler(
            settings.LOG_FILE_PATH,
            maxBytes=10 * 1024 * 1024,  # 单个文件最大 10MB
            backupCount=5,  # 保留 5 个历史文件
            encoding='utf-8'  # 显式指定 UTF-8，防止 Windows 中文乱码
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

        # 添加到根记录器 (捕获所有普通业务日志)
        root_logger.addHandler(file_handler)

        # 专门拦截 Uvicorn 的日志并写入同一个文件
        uvicorn_logger = logging.getLogger("uvicorn")
        uvicorn_access_logger = logging.getLogger("uvicorn.access")

        # 避免 Uvicorn 记录器重复添加 handler
        if not any(isinstance(h, RotatingFileHandler) for h in uvicorn_logger.handlers):
            uvicorn_logger.addHandler(file_handler)

        if not any(isinstance(h, RotatingFileHandler) for h in uvicorn_access_logger.handlers):
            uvicorn_access_logger.addHandler(file_handler)

    # 禁止根节点将日志传递给父级（根节点也没有父级了，防止一些奇怪的重复输出）
    root_logger.propagate = False

    # 3. 压制第三方库的冗余日志 (避免刷屏)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.DEBUG if settings.DEBUG else logging.WARNING
    )
    logging.getLogger("uvicorn.access").setLevel(
        logging.DEBUG if settings.DEBUG else logging.INFO
    )

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    logging.getLogger("google_genai.models").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)

    return root_logger
