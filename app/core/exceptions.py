# app/core/exceptions.py
from typing import Optional, Dict, Any
from app.core.error_code import ErrorCode

class APIError(Exception):
    def __init__(
            self,
            code: int = ErrorCode.SYSTEM_ERROR.value, # ✨ 接收 5 位数业务码
            message: str = "服务器内部错误",
            detail: Optional[Dict[str, Any]] = None
    ):
        self.code = code
        self.message = message
        self.detail = detail or {}
        super().__init__(self.message)

class NotFoundError(APIError):
    def __init__(self, resource: str, identifier: Any):
        super().__init__(
            code=ErrorCode.NOT_FOUND.value, # ✨ 使用业务码 40400
            message=f"{resource} 未找到",
            detail={"resource": resource, "identifier": str(identifier)}
        )

class ValidationError(APIError):
    def __init__(self, field: str, reason: str):
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR.value, # ✨ 使用业务码 40001
            message="数据验证失败",
            detail={"field": field, "reason": reason}
        )

class AuthenticationError(APIError):
    def __init__(self, message: str = "认证失败"):
        super().__init__(code=ErrorCode.UNAUTHORIZED.value, message=message)

class AuthorizationError(APIError):
    def __init__(self, message: str = "权限不足"):
        super().__init__(code=ErrorCode.FORBIDDEN.value, message=message)

class DatabaseConnectionError(APIError):
    def __init__(self, message: str = "数据库连接失败"):
        super().__init__(code=ErrorCode.DATABASE_ERROR.value, message=message)