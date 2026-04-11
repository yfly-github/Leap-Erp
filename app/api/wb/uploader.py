from fastapi import APIRouter, BackgroundTasks
from app.schemas import PublishRequest
from app.services.uploader_service import WBUploaderService
# 🌟 1. 同时导入 Response 和 ResponseModel
from app.utils.response import Response, ResponseModel

router = APIRouter(prefix="/uploader", tags=["WB 刊登模块"])


async def run_publish_task(store: str, nm_ids: list):
    try:
        uploader = WBUploaderService(target_store=store)
        await uploader.process_publish(nm_ids)
    except Exception as e:
        print(f"❌ 刊登任务启动失败: {e}")


# 🌟 2. 将 response_model 改为 ResponseModel
@router.post("/publish", response_model=ResponseModel)
async def start_publish(req: PublishRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_publish_task, req.target_store, req.nm_ids)

    # 这里 return 的依然是 Response.success()，因为它返回的就是 ResponseModel 实例
    return Response.success(message=f"已将 {len(req.nm_ids)} 个商品加入店铺 [{req.target_store}] 的刊登后台队列")