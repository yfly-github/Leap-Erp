from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Session, selectinload
from app.entities.wb_product_entity import WBProductEntity, WBProductSizeEntity, WBPublishRecordEntity
from datetime import datetime

class WBProductRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def save_product_and_sizes(self, product_data, sizes_data):
        # 1. 存主表：使用 selectinload 连同关联的 sizes 一起预加载出来
        stmt = (
            select(WBProductEntity)
            .options(selectinload(WBProductEntity.sizes))
            .filter_by(nm_id=product_data['nm_id'])
        )
        result = await self.db.execute(stmt)
        prod = result.scalar_one_or_none()

        # 2. 准备新的尺码数据（完全不需要手动塞 product_id，ORM 会自动通过主表映射关联）
        new_sizes = [WBProductSizeEntity(**s) for s in sizes_data]

        if not prod:
            prod = WBProductEntity(**product_data)
            prod.sizes = new_sizes  # 🌟 直接赋值给 relationship 属性
            self.db.add(prod)

        await self.db.commit()

    async def is_published(self, original_nm_id, store_name):
        stmt = select(WBPublishRecordEntity).filter_by(
            original_nm_id=original_nm_id, target_store=store_name
        )
        result = await self.db.execute(stmt)

        return result.scalar_one_or_none() is not None

    async def record_publish(self, original_nm_id, store_name, my_nm_id, vcode):
        record = WBPublishRecordEntity(
            original_nm_id=original_nm_id,
            target_store=store_name,
            my_nm_id=my_nm_id,
            my_vendor_code=vcode,
            published_at=datetime.now() # 自动记录精确时间
        )
        self.db.add(record)
        await self.db.commit()

    async def get_sizes_by_product_id(self, product_id: int):
        """
        根据商品的主键 ID 获取该商品所有的尺码和库存信息
        """
        # 1. 构造查询语句：查询 WBProductSizeEntity，条件是 product_id 匹配
        stmt = select(WBProductSizeEntity).filter_by(product_id=product_id)

        # 2. 异步执行查询
        result = await self.db.execute(stmt)

        # 3. 获取所有匹配的记录（因为一个商品有多个尺码，所以用 scalars().all() 返回列表）
        return result.scalars().all()


    async def get_product_by_nm(self, nm_id: int):
        """
        根据商品变体 ID (nm_id) 查询商品主表信息
        """
        # 1. 构造查询语句
        stmt = select(WBProductEntity).filter_by(nm_id=nm_id)

        # 2. 异步执行查询
        result = await self.db.execute(stmt)

        # 3. 提取单条数据，如果找不到则返回 None
        return result.scalar_one_or_none()