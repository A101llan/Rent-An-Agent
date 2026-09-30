from fastapi import HTTPException, status
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class AppError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, request_id: str | None = None):
        super().__init__(
            status_code=status_code,
            detail={"error": {"code": code, "message": message, "request_id": request_id}},
        )


def unauthorized(code: str = "UNAUTHORIZED", message: str = "Authentication required") -> AppError:
    return AppError(status.HTTP_401_UNAUTHORIZED, code, message)


def forbidden(code: str = "FORBIDDEN", message: str = "Access denied") -> AppError:
    return AppError(status.HTTP_403_FORBIDDEN, code, message)


def not_found(code: str = "NOT_FOUND", message: str = "Resource not found") -> AppError:
    return AppError(status.HTTP_404_NOT_FOUND, code, message)


def bad_request(code: str = "BAD_REQUEST", message: str = "Invalid request") -> AppError:
    return AppError(status.HTTP_400_BAD_REQUEST, code, message)


def conflict(code: str = "CONFLICT", message: str = "Resource conflict") -> AppError:
    return AppError(status.HTTP_409_CONFLICT, code, message)


def session_expired(message: str = "This agent session has expired.") -> AppError:
    return AppError(status.HTTP_410_GONE, "SESSION_EXPIRED", message)


def too_many_requests(message: str = "Too many requests") -> AppError:
    return AppError(status.HTTP_429_TOO_MANY_REQUESTS, "RATE_LIMITED", message)
