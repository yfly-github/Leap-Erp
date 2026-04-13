import requests

from app.core.database import settings


class PricingService:
    def __init__(self):
        self.dynamic_rate = self._fetch_dynamic_rate()

    def _fetch_dynamic_rate(self) -> float:
        '''获取实时汇率并结合利润率计算最终系数'''
        url = "https://www.cbr-xml-daily.ru/daily_json.js"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                cny_value = resp.json()['Valute']['CNY']['Value']
                return (1 / cny_value) * settings.PROFIT_MARGIN
        except Exception:
            pass
        return 0.086  # 兜底汇率

    def calculate_smart_price(self, rub_price: int) -> int:
        '''智能分段定价逻辑 (防止小件商品亏本)'''
        if rub_price < 500:
            return int(rub_price * self.dynamic_rate * 1.5)
        elif rub_price < 2000:
            return int(rub_price * self.dynamic_rate * 1.2)
        else:
            return int(rub_price * self.dynamic_rate * 1.1)