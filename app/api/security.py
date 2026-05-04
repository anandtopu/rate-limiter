import hmac

from fastapi import Header, HTTPException, status

from app.config import settings


async def require_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    if not x_admin_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing admin API key",
        )

    if not hmac.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin API key",
        )
