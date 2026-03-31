import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
# Base = declarative_base()

# ==========================================
# 🚀 异步数据库核心 (专供 FastAPI 路由接口使用)
# ==========================================

# 1. 创建异步引擎 (使用 mysql+aiomysql://)
async_engine = create_async_engine(
    settings.DATABASE_URL_ASYNC,  # 请确保这里获取到的是异步连接串
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,       # 30分钟回收一次，防止防火墙断开
    pool_size=20,            # 常驻连接数
    max_overflow=30,         # 突发并发时的额外连接数
    pool_timeout=30          # 连接池耗尽时最多等待30秒
)

# 2. 创建异步会话工厂 (使用最新的 async_sessionmaker)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# 3. 依赖注入函数 (供 routers 里的 Depends 使用)
async def get_async_db():
    """
    获取异步数据库会话，请求结束自动释放回连接池
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# 4. 生命周期管理：销毁引擎
async def dispose_engine():
    """显式销毁异步引擎连接池"""
    if async_engine:
        try:
            await async_engine.dispose()
            logger.info("✅ 异步数据库连接池已安全关闭")
        except Exception as e:
            logger.error(f"❌ 销毁异步引擎连接池时出错: {e}")

# 5. 生命周期管理：健康检查
async def ping_database() -> bool:
    """异步数据库连通性心跳检查"""
    try:
        async with async_engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        logger.error(f"⚠️ 异步数据库心跳检查失败: {e}")
        return False