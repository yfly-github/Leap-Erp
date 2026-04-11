# init_db.py
from app.configs.database import engine, Base
# 必须显式导入所有实体模型，这样 Base 才能“看到”它们
from app.entities.wb_product_entity import WBProductEntity, WBProductSizeEntity, WBPublishRecordEntity
from app.entities.wb_store_entity import WBStoreEntity

def create_tables():
    print("⏳ 正在检查并创建数据库表...")
    # create_all 会自动去 MySQL 创建缺失的表
    Base.metadata.create_all(bind=engine)
    print("✅ 数据库表创建完成！")

if __name__ == "__main__":
    create_tables()