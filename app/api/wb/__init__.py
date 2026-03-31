from fastapi import APIRouter

from app.api.wb import scraper, uploader

# 创建一个 WB 专属的路由大分类，并统一加上 /wb 前缀
wb_router = APIRouter(prefix="/wb")

wb_router.include_router(scraper.router)
wb_router.include_router(uploader.router)