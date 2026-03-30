from sqlalchemy.orm import Session
from app.entities.wb_product_entity import WBProductEntity, WBProductSizeEntity, WBPublishRecordEntity
from datetime import datetime

class WBProductRepository:
    def __init__(self, db: Session):
        self.db = db

    def save_product_and_sizes(self, product_data, sizes_data):
        # 存主表
        prod = self.db.query(WBProductEntity).filter_by(nm_id=product_data['nm_id']).first()
        if not prod:
            prod = WBProductEntity(**product_data)
            self.db.add(prod)
        else:
            for k, v in product_data.items(): setattr(prod, k, v)
        self.db.flush()
        # 存尺码子表
        self.db.query(WBProductSizeEntity).filter_by(product_id=prod.id).delete()
        for s in sizes_data:
            self.db.add(WBProductSizeEntity(product_id=prod.id, **s))
        self.db.commit()

    def is_published(self, original_nm_id, store_name):
        return self.db.query(WBPublishRecordEntity).filter_by(
            original_nm_id=original_nm_id, target_store=store_name
        ).first() is not None

    def record_publish(self, original_nm_id, store_name, my_nm_id, vcode):
        record = WBPublishRecordEntity(
            original_nm_id=original_nm_id,
            target_store=store_name,
            my_nm_id=my_nm_id,
            my_vendor_code=vcode,
            published_at=datetime.now() # 自动记录精确时间
        )
        self.db.add(record)
        self.db.commit()

    def get_product_by_nm(self, nm_id):
        return self.db.query(WBProductEntity).filter_by(nm_id=nm_id).first()