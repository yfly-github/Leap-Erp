import time
import random
import requests
import os
from requests.adapters import HTTPAdapter

# 1. 创建全局 Session 并配置连接池大小
session = requests.Session()
adapter = HTTPAdapter(pool_connections=100, pool_maxsize=200)  # 根据并发数调大
session.mount('http://', adapter)
session.mount('https://', adapter)


# 🌟 修复点 1：去掉了 json_data 参数，完全依赖 **kwargs 透传 requests 支持的所有参数 (如 json, data, files)
def request_with_retry(url: str, method: str = "GET", headers: dict = None, retries: int = 3,
                       timeout: int = 15, stream: bool = False, **kwargs):
    """通用的带重试机制的请求工具"""
    for i in range(retries):
        try:
            # 🌟 修复点 2：统一使用 session.request，不再区分 GET 和 POST，代码更精简
            r = session.request(method, url, headers=headers, timeout=timeout, stream=stream, **kwargs)

            if r.status_code in [200, 204]:
                return r
            elif r.status_code == 404:
                return None

            print(f"   ⚠️ 请求 {url} HTTP {r.status_code}，重试 ({i + 1}/{retries})...")
            # 如果接口返回了错误信息，可以尝试打印出来方便调试
            if r.status_code >= 400:
                print(f"   ⚠️ 错误详情: {r.text}")

            time.sleep(random.uniform(1.5, 3))
        except Exception as e:
            print(f"   ⚠️ 网络异常: {e}，重试 ({i + 1}/{retries})...")
            time.sleep(random.uniform(2, 4))
    return None


def download_file_with_retry(url: str, filepath: str, headers: dict = None, retries: int = 3):
    """通用的文件下载工具"""
    for _ in range(retries):
        try:
            r = session.get(url, headers=headers, stream=True, timeout=15)
            if r.status_code == 200:
                with open(filepath, 'wb') as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
                return True
            elif r.status_code == 404:
                return False
        except Exception:
            time.sleep(2)
    return False