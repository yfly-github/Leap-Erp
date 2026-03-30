import time
import random
import requests
import os


def request_with_retry(url: str, method: str = "GET", headers: dict = None, json_data: dict = None, retries: int = 3,
                       timeout: int = 15, stream: bool = False, **kwargs):
    """通用的带重试机制的请求工具"""
    for i in range(retries):
        try:
            if method.upper() == "GET":
                r = requests.get(url, headers=headers, timeout=timeout, stream=stream, **kwargs)
            else:
                r = requests.request(method, url, headers=headers, json=json_data, timeout=timeout, stream=stream,
                                     **kwargs)

            if r.status_code in [200, 204]:
                return r
            elif r.status_code == 404:
                return None

            print(f"   ⚠️ 请求 {url} HTTP {r.status_code}，重试 ({i + 1}/{retries})...")
            time.sleep(random.uniform(1.5, 3))
        except Exception as e:
            print(f"   ⚠️ 网络异常: {e}，重试 ({i + 1}/{retries})...")
            time.sleep(random.uniform(2, 4))
    return None


def download_file_with_retry(url: str, filepath: str, headers: dict = None, retries: int = 3):
    """通用的文件下载工具"""
    for _ in range(retries):
        try:
            r = requests.get(url, headers=headers, stream=True, timeout=15)
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