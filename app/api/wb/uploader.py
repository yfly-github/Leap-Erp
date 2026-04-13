# app/api/wb/uploader.py
from fastapi import APIRouter, BackgroundTasks

from app.schemas import PublishRequest
from app.services.uploader_service import WBUploaderService
from app.utils.response import Response, ResponseModel
from app.core.database import AsyncSessionLocal

# 🌟 引入刚写的 Repository
from app.repository.wb_store_repository import WBStoreRepository

router = APIRouter(prefix="/uploader", tags=["WB 刊登模块"])


async def run_publish_task(store: str, nm_ids: list):
    """
    这是一个绝佳的"组装工厂"：
    1. 负责管理数据库生命周期
    2. 负责查 Token
    3. 负责给 Service 注入依赖
    """
    try:
        # 🌟 1. 开启整个后台任务专属的数据库连接
        async with AsyncSessionLocal() as db:

            # 🌟 2. 查 Token
            store_repo = WBStoreRepository(db)
            token = await store_repo.get_token_by_name(store)

            if not token:
                print(f"❌ 刊登任务已取消: 数据库中未找到店铺 [{store}] 的有效 Token！")
                return

            # 🌟 3. 初始化 Service，将查好的 Token 注入进去
            uploader = WBUploaderService(target_store=store, token=token)

            # 🌟 4. 将同一个数据库会话(db)传递给 Service 供其内部记录数据使用，
            # 这样就彻底复用了同一个连接，效率最高也最安全。
            await uploader.process_publish(original_nm_ids=nm_ids, db_session=db)

    except Exception as e:
        print(f"❌ 刊登任务执行失败: {e}")


@router.post("/publish", response_model=ResponseModel)
async def start_publish(req: PublishRequest, background_tasks: BackgroundTasks):
    # 将参数扔进后台任务去跑
    background_tasks.add_task(run_publish_task, req.target_store, req.nm_ids)

    return Response.success(message=f"已将 {len(req.nm_ids)} 个商品加入店铺 [{req.target_store}] 的刊登后台队列")