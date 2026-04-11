# app/repository/wb_store_repository.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.entities.wb_store_entity import WBStoreEntity


class WBStoreRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_token_by_name(self, store_name: str) -> str | None:
        """
        根据店铺名称，查询有效状态下的 API Token
        """
        stmt = select(WBStoreEntity).filter_by(
            store_name=store_name,
            is_active=True  # 确保只查询未被禁用的店铺
        )
        result = await self.db.execute(stmt)
        store = result.scalar_one_or_none()

        # 如果找到了店铺，返回 token；否则返回 None
        return store.api_token if store else None

    async def create_store(self, store_name: str, api_token: str):
        """
        [备用] 新增店铺的方法，供后续开发"店铺管理"接口时使用
        """
        new_store = WBStoreEntity(store_name=store_name, api_token=api_token)
        self.db.add(new_store)
        await self.db.commit()
        return new_store