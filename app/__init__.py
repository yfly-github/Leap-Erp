# app/__init__.py
"""
应用工厂模块
负责创建和配置FastAPI应用实例
使用工厂模式便于测试和多环境配置
"""
import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

from app.api.routers import api_v1_router
from app.core.config import Settings
from app.core.database import ping_database, dispose_engine
from app.core.exception_handler import setup_global_exception_handlers
from app.middlewares.request_logging import EnhancedRequestLoggingMiddleware

logger = logging.getLogger(__name__)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("🚀 正在初始化基础设施...")

        # 1. 初始化 MySQL
        try:
            if await ping_database():
                logger.info("✅ MySQL 连接池初始化成功")
            else:
                logger.error("❌ MySQL 连接失败")
        except Exception as e:
            logger.error(f"❌ MySQL 初始化异常: {e}")

        # 启动完成，移交控制权
        yield

        # ================= ✨ 核心改造：独立隔离的资源清理 =================
        logger.info("🛑 正在优雅关闭基础设施...")

        # 2. 独立关闭 MySQL
        try:
            await dispose_engine()
            logger.info("✅ MySQL 连接池已销毁")
        except Exception as e:
            logger.error(f"❌ MySQL 清理失败 (系统将自动回收): {e}")

        logger.info("👋 应用已完全停止。")
        # =================================================================

    # 创建应用实例 (保留了您原有的 Wildberries 描述)
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description="Wildberries平台产品数据分析与管理系统API",
        docs_url=settings.DOCS_URL if settings.DEBUG else None,
        redoc_url=settings.REDOC_URL if settings.DEBUG else None,
        openapi_url=settings.OPENAPI_URL if settings.DEBUG else None,
        lifespan=lifespan,
        debug=settings.DEBUG,
    )

    # 配置中间件
    _setup_middleware(app, settings)

    # 配置路由
    _setup_routers(app, settings)

    # 配置异常处理
    setup_global_exception_handlers(app)

    # 添加健康检查端点
    _setup_health_check(app)

    print(f"""系统路由：{app.routes}""")

    return app


def _setup_middleware(app: FastAPI, settings: Settings) -> None:
    """
    配置应用中间件
    """
    # 配置CORS中间件
    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.BACKEND_CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        logger.info(f"✅ CORS中间件已配置，允许的源: {settings.BACKEND_CORS_ORIGINS}")

    # 请求日志中间件
    if settings.ENABLE_REQUEST_LOGGING:
        app.add_middleware(
            EnhancedRequestLoggingMiddleware,
            skip_paths=settings.REQUEST_LOG_SKIP_PATHS if hasattr(settings, "REQUEST_LOG_SKIP_PATHS") else None
        )
        logger.info("✅ 请求日志中间件已启用")


def _setup_routers(app: FastAPI, settings: Settings) -> None:
    """
    注册应用路由
    """
    app.include_router(
        api_v1_router,
        prefix=settings.API_V1_STR,
        tags=["api-v1"]
    )
    logger.info("✅ API路由已注册")



def _setup_health_check(app: FastAPI) -> None:
    """
    配置健康检查端点
    """

    @app.get("/health", tags=["health"])
    async def health_check():
        from datetime import datetime
        from app.core.database import ping_database

        db_status = "healthy"
        try:
            # 💡 顺手修复的 Bug: ping_database() 是异步函数，这里必须加 await 才能正确获取 boolean 值
            if not await ping_database():
                db_status = "unhealthy"
        except Exception as e:
            db_status = f"error: {str(e)}"

        return {
            "status": "healthy",
            "service": "Product Management",
            "timestamp": datetime.now().isoformat(),
            "database": db_status
        }

    logger.info("✅ 健康检查端点已配置")