from pydantic import BaseModel
from typing import List

class PublishRequest(BaseModel):
    """WB 刊登请求参数"""
    target_store: str
    nm_ids: List[int]  # 前端勾选的要刊登的原始 nm_id 列表