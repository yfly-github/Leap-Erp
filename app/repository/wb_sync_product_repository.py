# ... 原有的代码保持不变 ...
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.entities.wb_product_entity import WBProductEntity, WBProductSizeEntity


# 🚀 新增：专门用于多线程爬虫环境的同步仓储类
class SyncWBProductRepository:
    def __init__(self, db: Session):
        self.db = db

    def save_product_and_sizes(self, product_data, sizes_data):
        # 1. 构造查询
        stmt = (
            select(WBProductEntity)
            .options(selectinload(WBProductEntity.sizes))
            .filter_by(nm_id=product_data['nm_id'])
        )
        # 2. 同步执行查询 (去掉了 await)
        result = self.db.execute(stmt)
        prod = result.scalar_one_or_none()

        # 3. 准备关联数据
        new_sizes = [WBProductSizeEntity(**s) for s in sizes_data]

        # 4. 如果数据库没有，则新增
        if not prod:
            prod = WBProductEntity(**product_data)
            prod.sizes = new_sizes
            self.db.add(prod)

        # 5. 同步提交 (去掉了 await)
        self.db.commit()