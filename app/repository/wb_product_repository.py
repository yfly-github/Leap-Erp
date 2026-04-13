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

    async def upsert_scraped_product(
            self,
            nm_id: int,
            title: str,
            brand: str,
            description:str,
            subject_id: int,
            price_rub: float,
            local_folder: str,
            attributes_json: str
    ):
        """
        🚀 插入或更新爬取到的商品数据 (Upsert)
        """
        try:
            # 1. 先查询数据库中是否已经存在该 nm_id
            stmt = select(WBProductEntity).where(WBProductEntity.nm_id == nm_id)
            result = await self.db.execute(stmt)
            product = result.scalars().first()

            if product:
                # 2A. 如果存在，更新数据
                product.title = title
                product.brand = brand
                product.subject_id = subject_id  # 🌟 关键的建品类目ID
                product.price_rub = price_rub
                product.local_folder = local_folder
                product.attributes_json = attributes_json
                product.is_scraped = True
            else:
                # 2B. 如果不存在，创建新记录
                product = WBProductEntity(
                    nm_id=nm_id,
                    title=title,
                    brand=brand,
                    subject_id=subject_id,  # 🌟 关键的建品类目ID
                    price_rub=price_rub,
                    local_folder=local_folder,
                    attributes_json=attributes_json,
                    is_scraped=True
                )
                self.db.add(product)

            # 3. 提交事务
            await self.db.commit()
            return product

        except Exception as e:
            # 遇到异常时回滚，防止数据库连接池死锁
            await self.db_session.rollback()
            print(f"❌ 数据库 Upsert 失败 (nm_id: {nm_id}): {e}")
            raise e