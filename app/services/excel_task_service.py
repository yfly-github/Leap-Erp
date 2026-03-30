import pandas as pd
import re, os
from app.services.scraper_service import WBScraperService
from app.services.uploader_service import WBUploaderService
from app.configs.settings import settings

class ExcelTaskService:
    def extract_ids(self, text: str) -> list:
        matches = re.findall(r'catalog/(\d+)/detail', str(text))
        if matches: return [int(m) for m in matches]
        return [int(x) for x in re.split(r'[,\s]+', str(text)) if x.isdigit()]

    def run_tasks(self, file_path: str):
        if not os.path.exists(file_path):
            print(f"❌ 找不到 Excel: {file_path}")
            return

        df = pd.read_excel(file_path)
        for idx, row in df.iterrows():
            task_type = str(row.get('任务类型', '')).strip()
            target = str(row.get('目标(店铺ID或商品链接)', ''))
            fbs = str(row.get('仅限商家仓(是/否)', '否')).strip() == '是'
            auto_pub = str(row.get('是否自动刊登(是/否)', '否')).strip() == '是'
            store = str(row.get('目标刊登店铺', '店铺A')).strip()

            print(f"\n▶️ [任务 {idx+1}] {task_type} -> {target[:30]}...")

            if task_type == '店铺':
                sid = int(re.sub(r'\D', '', target)) if re.sub(r'\D', '', target) else None
                scraper = WBScraperService(supplier_id=sid, fbs_only=fbs)
                scraper.run_supplier_scan()
            elif task_type == '商品':
                pids = self.extract_ids(target)
                scraper = WBScraperService(fbs_only=fbs)
                scraper.run_product_list(pids)

            if auto_pub:
                try:
                    uploader = WBUploaderService(target_store=store)
                    uploader.process_publish(settings.base_data_dir)
                except ValueError as e:
                    print(f"❌ {e}")
