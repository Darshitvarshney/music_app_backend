from fastapi import HTTPException


def api_error(status_code: int, code: str, message: str, **extra) -> HTTPException:
    """HTTPException with `detail` = `{code, message, ...extra}` so clients can branch on code."""
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, **extra},
    )
