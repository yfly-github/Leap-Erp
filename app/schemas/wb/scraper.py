from pydantic import BaseModel
from typing import List

class SupplierScrapeRequest(BaseModel):
    """WB 店铺采集请求参数"""
    supplier_id: int
    use_filter: bool = False
    min_fb: int = 0           # 最小评价数
    max_fb: int = 9999999     # 最大评价数 (默认给个极大值)
    filter_rate: float = 0.0  # 最小评分
    fbs_only: bool = False

class ProductScrapeRequest(BaseModel):
    """WB 指定商品采集请求参数"""
    product_ids: List[int]
    fbs_only: bool = False