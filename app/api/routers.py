from fastapi import APIRouter

from app.api.wb import wb_router

api_v1_router = APIRouter()

api_v1_router.include_router(wb_router)