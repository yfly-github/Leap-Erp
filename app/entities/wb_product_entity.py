from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, JSON, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from app.configs.database import Base



class WBProductEntity(Base):
    __tablename__ = "wb_products"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    supplier_id = Column(Integer, index=True, comment="卖家/店铺ID")
    imt_id = Column(Integer, index=True, comment="竞品组ID")
    nm_id = Column(Integer, unique=True, index=True, comment="竞品变体ID")

    title = Column(String(255), comment="商品标题")
    brand = Column(String(100), comment="品牌")
    description = Column(Text, comment="商品描述")

    subject_id = Column(Integer, default=0, comment="WB内部类目(Subject)ID")
    category = Column(String(100), comment="类目")

    main_image = Column(String(500), comment="主图")
    images_json = Column(JSON, comment="所有附图的相对路径列表")
    video_path = Column(String(255), comment="视频文件的相对路径")
    price_rub = Column(Float, comment="卢布原价")
    feedbacks = Column(Integer, default=0, comment="评价数")
    rating = Column(Float, default=0.0, comment="评分")
    is_fbs = Column(Boolean, default=False, comment="是否商家仓")

    attributes_json = Column(JSON, comment="扩展属性")

    status = Column(String(50), default="scraped")
    local_folder = Column(String(255), comment="本地文件夹")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    sizes = relationship("WBProductSizeEntity", back_populates="product", cascade="all, delete-orphan")

class WBProductSizeEntity(Base):
    __tablename__ = "wb_product_sizes"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("wb_products.id"))
    tech_size = Column(String(50), comment="技术尺码")
    stock_qty = Column(Integer, default=0, comment="库存")
    product = relationship("WBProductEntity", back_populates="sizes")

class WBPublishRecordEntity(Base):
    __tablename__ = "wb_publish_records"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    original_nm_id = Column(Integer, index=True)
    target_store = Column(String(50), index=True)
    my_nm_id = Column(Integer)

    published_price_rub = Column(Float, comment="刊登时推送的基础原价(卢布)")
    published_discount = Column(Integer, comment="刊登时推送的折扣比例(%)")
    my_vendor_code = Column(String(100))
    published_at = Column(DateTime, default=datetime.now)
