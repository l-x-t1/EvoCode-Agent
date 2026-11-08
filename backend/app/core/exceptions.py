"""业务异常体系 + FastAPI 全局异常处理器（docs/08 §4 横切约定）。

所有错误出口统一为 {"error": {"code", "message", "details"?}}：
- BizException：业务主动抛出
- StarletteHTTPException：路由 404 / 方法不允许等 → 同样转错误体
- RequestValidationError：422 → validation_error
- 兜底 Exception：500 internal（记录 traceback，不泄露内部细节）
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger
from app.core.response import ErrorCode, ErrorBody, ErrorDetail

logger = get_logger(__name__)


class BizException(Exception):
    """业务异常：service 层主动抛出，status_code 语义化。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: object | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _error_response(status_code: int, code: str, message: str, details: object | None = None) -> JSONResponse:
    body = ErrorBody(error=ErrorDetail(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizException)
    async def on_biz_exception(_: Request, exc: BizException) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def on_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Starlette 的 404/405 等也统一为错误体（前端依赖该结构）
        code_map = {404: ErrorCode.NOT_FOUND, 405: ErrorCode.INVALID_REQUEST, 429: ErrorCode.RATE_LIMITED}
        code = code_map.get(exc.status_code, ErrorCode.INVALID_REQUEST if exc.status_code < 500 else ErrorCode.INTERNAL)
        return _error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            422,
            ErrorCode.VALIDATION_ERROR,
            "请求参数校验失败",
            details=exc.errors(include_url=False, include_input=False),
        )

    @app.exception_handler(Exception)
    async def on_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常: %s", exc)
        return _error_response(500, ErrorCode.INTERNAL, "服务器内部错误")
