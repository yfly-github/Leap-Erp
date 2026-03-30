import sys, os, re
from app.services.scraper_service import WBScraperService
from app.services.uploader_service import WBUploaderService
from app.services.excel_task_service import ExcelTaskService


def print_menu():
    print("=" * 60)
    print("   Leap-Erp 跨境智能系统 (终极企业版)   ")
    print("=" * 60)
    print("1. [单次采集] 输入店铺或商品ID采集")
    print("2. [手动刊登] 指定店铺和文件夹上传")
    print("3. [批量自动化] 读取 Excel 自动化采集+刊登")
    print("q. 退出")


def main():
    # --- 1. 全局配置询问 ---
    use_filter = False
    filter_fb = 0
    filter_rate = 0.0
    use_fbs_only = False

    enable_filter_input = input("❓ 是否执行抓取限制 (评价数量&评分)？(y/n): ").strip().lower()
    if enable_filter_input == 'y':
        use_filter = True
        try:
            print("👇 请输入具体数值 (⚠️ 规则：组内任意一个 >= n 即整组下载):")
            filter_fb = int(input("   最小评价数量 n = "))
            filter_rate = float(input("   最小评分数 n = "))
            print(f"⚙️ 过滤已开启: 评价 >= {filter_fb} 且 评分 >= {filter_rate}")
        except ValueError:
            print("❌ 输入格式错误，默认关闭过滤")
            use_filter = False

    enable_fbs_input = input("❓ 是否只采集包含 FBS (商家仓) 变体的商品组? (y/n): ").strip().lower()
    if enable_fbs_input == 'y':
        use_fbs_only = True
        print("⚙️ FBS 模式已开启: 将跳过全组均为官方仓的商品")

    while True:
        print_menu()
        choice = input("\n👉 请输入选择: ").strip().lower()
        if choice in ['q', 'exit']: break

        if choice == '1':
            target = input("请输入 WB 店铺ID或商品ID: ").strip()

            # 将配置参数传入 ScraperService
            scraper = WBScraperService(
                use_filter=use_filter,
                filter_fb=filter_fb,
                filter_rate=filter_rate,
                fbs_only=use_fbs_only
            )

            if len(target) > 7 and not target.startswith('seller'):
                scraper.run_product_list([int(x) for x in re.split(r'[,\s]+', target) if x.isdigit()])
            else:
                sid = int(re.sub(r'\D', '', target))
                scraper.supplier_id = sid
                scraper.run_supplier_scan()

        elif choice == '2':
            store = input("🎯 请输入目标店铺别名 (如 店铺A): ").strip()
            try:
                uploader = WBUploaderService(target_store=store)
                uploader.process_publish("data")
            except ValueError as e:
                print(f"❌ {e}")

        elif choice == '3':
            file_path = input("📂 请拖入 tasks.xlsx: ").strip().replace('"', '')
            if file_path:
                ExcelTaskService().run_tasks(file_path)


if __name__ == "__main__":
    main()