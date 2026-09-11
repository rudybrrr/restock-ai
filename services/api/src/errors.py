from typing import Literal

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool = False


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: ErrorDetail


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.detail = ErrorDetail(code=code, message=message)


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return JSONResponse(
        status_code=exc.status, content=ErrorResponse(error=exc.detail).model_dump()
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error=ErrorDetail(
                code="INVALID_REQUEST",
                message="Request does not match the API schema",
            )
        ).model_dump(),
    )
