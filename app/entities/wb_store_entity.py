# 示例结构
from sqlalchemy import Column, Integer, String, Boolean

from app.configs.database import Base


class WBStoreEntity(Base):
    __tablename__ = "wb_stores"
    id = Column(Integer, primary_key=True)
    store_name = Column(String(50), unique=True, comment="店铺名称")
    api_token = Column(String(500), comment="API授权Token")
    status = Column(Boolean, default=True, comment="店铺状态")