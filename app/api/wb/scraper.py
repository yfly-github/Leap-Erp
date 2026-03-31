from fastapi import APIRouter, BackgroundTasks

from app.schemas import SupplierScrapeRequest, ProductScrapeRequest
from app.services.scraper_service import WBScraperService
from app.utils.response import Response

router = APIRouter(prefix="/scraper", tags=["WB 采集模块"])

def run_supplier_task(req: SupplierScrapeRequest):
    scraper = WBScraperService(
        supplier_id=req.supplier_id,
        use_filter=req.use_filter,
        min_fb=req.min_fb,
        max_fb=req.max_fb,
        filter_rate=req.filter_rate,
        fbs_only=req.fbs_only
    )
    scraper.run_supplier_scan()

def run_product_task(req: ProductScrapeRequest):
    scraper = WBScraperService(fbs_only=req.fbs_only)
    scraper.run_product_list(req.product_ids)

@router.post("/supplier")
async def start_supplier_scraper(req: SupplierScrapeRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_supplier_task, req)
    return Response.success(message=f"店铺 {req.supplier_id} 采集任务已在后台启动")

@router.post("/products")
async def start_products_scraper(req: ProductScrapeRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_product_task, req)
    return Response.success(message=f"已将 {len(req.product_ids)} 个商品加入后台采集队列")