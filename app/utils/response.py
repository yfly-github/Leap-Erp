from typing import Generic, Optional, TypeVar
from pydantic import BaseModel

T = TypeVar("T")

class ResponseModel(BaseModel, Generic[T]):
    code: int
    message: str
    data: Optional[T] = None

class Response:
    @staticmethod
    def success(data: T = None, message: str = "ok") -> ResponseModel[T]:
        return ResponseModel(code=200, message=message, data=data)

    @staticmethod
    def fail(message: str = "ok") -> ResponseModel[T]:
        return ResponseModel(code=200, message=message)