# app/middleware/logging.py
import logging
import time
from typing import Set, Dict, Any, Optional, Union
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import json
from contextvars import ContextVar
from uuid import uuid4
import re

# 创建请求ID的上下文变量
_request_id: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """获取当前请求的ID"""
    return _request_id.get()


class EnhancedRequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    增强的请求日志中间件
    记录所有请求的访问日志，包含请求/响应详情
    """

    def __init__(
            self,
            app,
            *,
            skip_paths: Set[str] = None,
            skip_methods: Set[str] = None,
            sensitive_headers: Set[str] = None,
            max_body_length: int = 1024,
            log_level_mapping: Dict[int, str] = None,
            extra_fields: Dict[str, Any] = None,
            logger_name: str = "request"
    ):
        """
        初始化中间件

        Args:
            app: FastAPI应用
            skip_paths: 跳过的路径列表
            skip_methods: 跳过的HTTP方法
            sensitive_headers: 敏感请求头（会被遮蔽）
            max_body_length: 日志中记录的最大body长度
            log_level_mapping: 状态码到日志级别的映射
            extra_fields: 额外要记录的字段
            logger_name: 日志记录器名称
        """
        super().__init__(app)
        self.skip_paths = skip_paths or {"/health", "/metrics", "/favicon.ico"}
        self.skip_methods = skip_methods or {"OPTIONS"}
        self.sensitive_headers = sensitive_headers or {
            "authorization", "cookie", "token", "api-key", "password"
        }
        self.max_body_length = max_body_length
        self.logger = logging.getLogger(logger_name)

        # 默认的日志级别映射
        self.log_level_mapping = log_level_mapping or {
            200: "INFO",
            201: "INFO",
            204: "INFO",
            400: "WARNING",
            401: "WARNING",
            403: "WARNING",
            404: "INFO",  # 404可能只是访问了不存在的路径
            422: "WARNING",  # 参数验证失败
            500: "ERROR",
            502: "ERROR",
            503: "ERROR",
            504: "ERROR",
        }

        # 支持正则表达式匹配的跳过路径
        self.skip_patterns = [
            re.compile(pattern) for pattern in self.skip_paths
            if "*" in pattern or "?" in pattern or "{" in pattern
        ]
        self.skip_paths = {p for p in self.skip_paths if "*" not in p and "?" not in p and "{" not in p}

        # 预编译敏感头部的正则表达式
        self.sensitive_patterns = [
            re.compile(rf'{header}', re.IGNORECASE)
            for header in self.sensitive_headers
        ]

        # 额外的字段
        self.extra_fields = extra_fields or {}

    def _should_skip(self, request: Request) -> bool:
        """判断是否应该跳过日志记录"""
        # 检查方法
        if request.method in self.skip_methods:
            return True

        path = request.url.path

        # 检查精确匹配的路径
        if path in self.skip_paths:
            return True

        # 检查正则匹配的路径
        for pattern in self.skip_patterns:
            if pattern.match(path):
                return True

        return False

    def _mask_sensitive_data(self, data: Union[Dict[str, Any], Any]) -> Union[Dict[str, Any], Any]:
        """
        遮蔽敏感数据
        支持嵌套字典的递归处理
        """
        # 如果不是字典，直接返回
        if not isinstance(data, dict):
            return data

        # 如果是字典，创建副本并处理
        masked = {}
        for key, value in data.items():
            # 递归处理嵌套字典
            if isinstance(value, dict):
                masked[key] = self._mask_sensitive_data(value)
            # 处理字符串值
            elif isinstance(value, str):
                # 检查键名是否包含敏感信息
                is_sensitive = False
                key_lower = key.lower()
                for sensitive_key in self.sensitive_headers:
                    if sensitive_key in key_lower:
                        is_sensitive = True
                        break

                if is_sensitive:
                    masked[key] = "***MASKED***"
                else:
                    masked[key] = value
            # 其他类型直接保留
            else:
                masked[key] = value

        return masked

    def _extract_request_info(self, request: Request) -> Dict[str, Any]:
        """提取请求信息"""
        # 基本请求信息
        info = {
            "method": request.method,
            "path": request.url.path,
            "query_params": str(request.query_params),
            "client_host": request.client.host if request.client else None,
            "client_port": request.client.port if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "referer": request.headers.get("referer"),
        }

        # 处理请求头（遮蔽敏感信息）
        headers = dict(request.headers)
        info["headers"] = self._mask_sensitive_data(headers)

        return info

    def _extract_response_info(self, response: Response) -> Dict[str, Any]:
        """提取响应信息"""
        info = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
        }

        # 尝试获取响应体大小
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                info["content_length"] = int(content_length)
            except ValueError:
                info["content_length"] = 0

        return info

    async def _get_request_body(self, request: Request) -> Optional[str]:
        """安全地获取请求体，不消耗原始请求流"""
        try:
            # 检查请求方法
            if request.method not in ["POST", "PUT", "PATCH"]:
                return None

            # 获取原始请求体内容
            body_bytes = await request.body()
            if not body_bytes:
                return None

            # 只读取前max_body_length个字节
            body_str = body_bytes[:self.max_body_length].decode('utf-8', errors='ignore')
            if len(body_bytes) > self.max_body_length:
                body_str += f"... (truncated, total {len(body_bytes)} bytes)"

            # 如果是JSON，尝试解析并遮蔽敏感数据
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    json_body = json.loads(body_str.split("...")[0] if "..." in body_str else body_str)
                    masked_body = self._mask_sensitive_data(json_body)
                    return json.dumps(masked_body, ensure_ascii=False)
                except json.JSONDecodeError:
                    pass

            return body_str
        except Exception:
            pass
        return None

    async def dispatch(self, request: Request, call_next):
        # 判断是否应该跳过
        if self._should_skip(request):
            return await call_next(request)

        # 生成请求ID
        request_id = str(uuid4())
        token = _request_id.set(request_id)
        request.state.request_id = request_id

        # 记录请求开始时间
        start_time = time.perf_counter()

        # 提取请求信息
        request_info = self._extract_request_info(request)

        # 对于POST/PUT/PATCH请求，先不读取请求体，而是让后续处理器处理
        request_body = None
        if request.method in ["POST", "PUT", "PATCH"]:
            # 仅在需要时记录请求体，避免影响后续处理
            request_body = await self._get_request_body(request)
            # 重新设置请求体，但注意这在某些FastAPI版本中可能不工作
            original_body = await request.body()

            async def receive():
                return {"type": "http.request", "body": original_body, "more_body": False}

            request._receive = receive

        # 处理请求
        try:
            response = await call_next(request)
            process_time = (time.perf_counter() - start_time) * 1000

            # 提取响应信息
            response_info = self._extract_response_info(response)

            # 记录日志
            self._log_request(
                request_id=request_id,
                request_info=request_info,
                request_body=request_body,
                response_info=response_info,
                process_time=process_time
            )

        except Exception as exc:
            process_time = (time.perf_counter() - start_time) * 1000
            self._log_exception(
                request_id=request_id,
                request_info=request_info,
                request_body=request_body,
                process_time=process_time,
                exception=exc
            )
            raise
        finally:
            _request_id.reset(token)

        return response

    def _get_log_level(self, status_code: int) -> str:
        """根据状态码获取日志级别"""
        return self.log_level_mapping.get(status_code, "INFO")

    def _log_request(
            self,
            request_id: str,
            request_info: Dict[str, Any],
            request_body: Optional[str],
            response_info: Dict[str, Any],
            process_time: float
    ):
        """记录请求日志"""
        log_data = {
            "request_id": request_id,
            "type": "request",
            "request": request_info,
            "response": response_info,
            "process_time_ms": round(process_time, 2),
            **self.extra_fields
        }

        if request_body:
            log_data["request"]["body"] = request_body

        # 转换为JSON格式
        log_message = json.dumps(log_data, ensure_ascii=False, default=str)

        # 根据状态码选择日志级别
        log_level = self._get_log_level(response_info["status_code"])
        log_method = getattr(self.logger, log_level.lower(), self.logger.info)
        log_method(log_message)

    def _log_exception(
            self,
            request_id: str,
            request_info: Dict[str, Any],
            request_body: Optional[str],
            process_time: float,
            exception: Exception
    ):
        """记录异常日志"""
        log_data = {
            "request_id": request_id,
            "type": "exception",
            "request": request_info,
            "process_time_ms": round(process_time, 2),
            "exception_type": type(exception).__name__,
            "exception_message": str(exception),
            **self.extra_fields
        }

        if request_body:
            log_data["request"]["body"] = request_body

        # 转换为JSON格式
        log_message = json.dumps(log_data, ensure_ascii=False, default=str)
        self.logger.error(log_message, exc_info=True)


