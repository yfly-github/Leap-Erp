from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.database import settings

# 1. 创建同步数据库引擎
engine = create_engine(
    settings.DATABASE_URL_SYNC,
    pool_pre_ping=True,       # 每次拿连接前先 ping 一下，防止 MySQL 自动断开连接
    pool_recycle=3600,        # 1小时回收一次连接
    pool_size=20,             # 🚀 核心优化：基础连接池大小调大，适配外层 5 个线程的并发
    max_overflow=50,          # 🚀 核心优化：并发高峰时，允许额外创建的最多连接数
    echo=False
)

# 2. 创建同步的 Session 工厂 (这就是我们要的 SessionLocal)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 3. 声明数据模型基类
Base = declarative_base()