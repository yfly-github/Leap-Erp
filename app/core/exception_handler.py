# app/core/exception_handlers.py
from fastapi import Request, FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

import logging

from app.core.error_code import ErrorCode
from app.core.exceptions import APIError

logger = logging.getLogger(__name__)


def setup_global_exception_handlers(app: FastAPI):
    """
    全局异常处理器 - 只需要在应用启动时调用一次
    """

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """
        拦截 FastAPI 的参数校验异常，将 Pydantic 的恶心报错扁平化、友好化
        """
        error_messages = []
        for error in exc.errors():
            # loc 包含了错误字段的层级路径，比如 ["body", "payload", "description"]
            # 我们过滤掉没用的 "body"，把剩下的拼起来，比如 "payload.description"
            field_path = ".".join([str(loc) for loc in error.get("loc", []) if loc != "body"])

            error_type = error.get("type", "")
            error_msg = error.get("msg", "")

            # 翻译并美化常见的错误类型
            if "missing" in error_type:
                friendly_msg = f"缺少必填参数 [{field_path}]"
            elif "type_error" in error_type or "string_type" in error_type:
                friendly_msg = f"参数 [{field_path}] 的数据类型不正确"
            elif "value_error" in error_type:
                friendly_msg = f"参数 [{field_path}] 的值无效"
            else:
                # 兜底：保留原始的提示信息，但附加上具体出问题的字段
                friendly_msg = f"参数 [{field_path}] 校验失败 ({error_msg})"

            error_messages.append(friendly_msg)

        # 如果有多个字段报错，用分号或者换行连起来
        final_message = "； ".join(error_messages)

        # 返回符合你们团队规范的统一 Response 结构
        return JSONResponse(
            status_code=200,  # 也可以用 422，看团队规范
            content={
                "code": 40000,
                "message": final_message,  # 🌟 现在变成一个干净漂亮的字符串了
                "data": None
            }
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """HTTP异常处理 - 处理404等HTTP错误"""
        status_code = exc.status_code

        # 1. 定义状态码映射表 (业务状态码, 友好的中文提示, 日志级别)
        http_code_map = {
            404: (ErrorCode.NOT_FOUND.value, f"请求的接口路径不存在: {request.url.path}", "info"),
            405: (ErrorCode.METHOD_NOT_ALLOWED.value, f"请求方法不允许: {request.method}", "warning"),
            401: (ErrorCode.UNAUTHORIZED.value, "未授权凭证无效，请先登录", "warning"),
            403: (ErrorCode.FORBIDDEN.value, "访问被拒绝，您没有执行此操作的权限", "warning"),
            429: (ErrorCode.TOO_MANY_REQUESTS.value, "请求过于频繁，请稍后再试", "warning"),
        }

        # 2. 从字典中匹配，如果没有匹配到，则走兜底逻辑
        default_biz_code = ErrorCode.BAD_REQUEST.value
        default_msg = exc.detail if exc.detail else f"网络/路由请求异常: {status_code}"

        biz_code, message, log_level = http_code_map.get(
            status_code,
            (default_biz_code, default_msg, "warning")
        )

        # 3. 动态记录日志
        log_text = f"HTTP {status_code} | {request.method} {request.url.path} | {message}"
        if log_level == "info":
            logger.info(log_text)
        else:
            logger.warning(log_text)

        # 4. 统一按照大厂规范返回：HTTP状态码为200，真实错误码放在JSON的code里
        return JSONResponse(
            status_code=200,
            content={
                "code": biz_code,  # 例如 404 变成了 40400
                "message": message,
                "data": None
            }
        )

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        """所有API异常的统一处理"""
        logger.warning(f"API异常: {exc.message}")
        return JSONResponse(
            status_code=200,
            content={
                "code": exc.code,
                "message": exc.message,
                "data": exc.detail
            }
        )

    @app.exception_handler(SQLAlchemyOperationalError)
    async def database_operational_handler(request: Request, exc: SQLAlchemyOperationalError):
        """数据库异常"""
        logger.error(f"数据库操作异常: {str(exc)}")
        return JSONResponse(
            status_code=200,
            content={
                "code": 500,
                "message": "数据库服务异常，请稍后重试",
                "data": None
            }
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """全局兜底异常处理"""
        logger.error(f"未处理的系统异常: {str(exc)}", exc_info=True)

        return JSONResponse(
            status_code=200,
            content={
                "code": 500,
                "message": "系统内部错误，请稍后重试",
                "data": None
            }
        )

