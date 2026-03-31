# app/core/error_code.py
from enum import Enum


class ErrorCode(int, Enum):
    """全局业务状态码字典"""

    # 🟢 成功状态 (20xxx)
    SUCCESS = 200

    # 🟡 客户端请求基础错误 (40xxx)
    BAD_REQUEST = 40000  # 错误的请求 (默认兜底)
    VALIDATION_ERROR = 40001  # 参数格式/校验失败 (对应 HTTP 422)
    UNAUTHORIZED = 40100  # 未授权/凭证无效 (对应 HTTP 401)
    FORBIDDEN = 40300  # 访问被拒绝/权限不足 (对应 HTTP 403)
    NOT_FOUND = 40400  # 接口或资源不存在 (对应 HTTP 404)
    METHOD_NOT_ALLOWED = 40500  # 请求方法不允许 (对应 HTTP 405)
    TOO_MANY_REQUESTS = 42900  # 接口请求过于频繁被限流 (对应 HTTP 429)

    # 🟠 具体业务逻辑错误 (41xxx)
    TASK_NOT_FOUND = 41001  # 任务不存在
    CLAIM_PRODUCT_NOT_FOUND = 41002  # 认领商品不存在

    # 🔴 服务端/第三方依赖错误 (50xxx)
    SYSTEM_ERROR = 50000  # 系统内部代码异常 (对应 HTTP 500)
    DATABASE_ERROR = 50001  # 数据库连接或操作异常
    AI_SERVICE_ERROR = 50010  # 大模型服务调用崩溃/超时
    AI_RATE_LIMIT = 50011  # 大模型端被限流 (区别于我们自己的接口被限流)