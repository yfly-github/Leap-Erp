from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.entities.wb_product_entity import WBProductEntity, WBProductSizeEntity


# 🚀 专门用于多线程爬虫环境的同步仓储类
class SyncWBProductRepository:
    def __init__(self, db: Session):
        self.db = db

    # ==========================================
    # 🌟 新增：根据 nm_id 查询商品的方法
    # ==========================================
    def get_product_by_nm(self, nm_id: int) -> WBProductEntity:
        """
        根据 nm_id 精确查询数据库中是否已存在该变体
        """
        stmt = select(WBProductEntity).filter_by(nm_id=nm_id)
        result = self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ==========================================
    # 原有的保存方法
    # ==========================================
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

        # 4. 如果数据库没有，则新增，有则更新覆盖（可选逻辑）
        if not prod:
            prod = WBProductEntity(**product_data)
            prod.sizes = new_sizes
            self.db.add(prod)
        else:
            # 如果是强制更新 (force_update=True) 时走到了这里
            # 更新主表核心数据
            for key, value in product_data.items():
                setattr(prod, key, value)

            # 更新尺码子表 (简单粗暴的先删后插，保证数据最新)
            prod.sizes = []
            self.db.flush()  # 先将删除操作同步到缓存
            prod.sizes = new_sizes

        # 5. 同步提交 (去掉了 await)
        self.db.commit()