from typing import Any, Optional, Dict
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError


class APIException(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class UnauthorizedException(APIException):
    def __init__(self, message: str = "Authentication required or token expired"):
        super().__init__(
            code="UNAUTHORIZED",
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class ForbiddenException(APIException):
    def __init__(self, message: str = "You do not have permission to access this resource"):
        super().__init__(
            code="FORBIDDEN",
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
        )


class NotFoundException(APIException):
    def __init__(self, message: str = "The requested resource was not found"):
        super().__init__(
            code="RESOURCE_NOT_FOUND",
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ConflictException(APIException):
    def __init__(self, message: str = "State or idempotency conflict"):
        super().__init__(
            code="CONFLICT",
            message=message,
            status_code=status.HTTP_409_CONFLICT,
        )


class RateLimitException(APIException):
    def __init__(self, message: str = "Rate limit or quota exceeded"):
        super().__init__(
            code="RATE_LIMIT_EXCEEDED",
            message=message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )


async def api_exception_handler(request: Request, exc: APIException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "req_unknown")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
            "request_id": request_id,
        },
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "req_unknown")
    formatted_errors = []
    for err in exc.errors():
        field = ".".join(str(loc) for loc in err.get("loc", []))
        formatted_errors.append({
            "field": field,
            "message": err.get("msg", "Invalid value"),
        })
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Validation failed for request parameters or payload",
                "details": {"errors": formatted_errors},
            },
            "request_id": request_id,
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "req_unknown")
    # Never expose raw stack traces or internal DB details to users (Architecture Section 78)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred. Please try again later.",
                "details": {},
            },
            "request_id": request_id,
        },
    )

