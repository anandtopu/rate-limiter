import hmac

from fastapi import Header, HTTPException, Request, status

from app.config import settings


def configured_admin_keys() -> dict[str, str]:
    keys = {"default": settings.admin_api_key}

    for raw_item in settings.admin_api_keys.split(","):
        item = raw_item.strip()
        if not item:
            continue

        if ":" in item:
            name, key = item.split(":", 1)
        else:
            name, key = item, item

        name = name.strip()
        key = key.strip()
        if name and key:
            keys[name] = key

    return keys


def admin_key_name_for(value: str) -> str | None:
    matched_name = None
    for name, configured_key in configured_admin_keys().items():
        if hmac.compare_digest(value, configured_key):
            matched_name = name

    return matched_name


async def require_admin_key(
    request: Request,
    x_admin_key: str | None = Header(default=None),
) -> None:
    if not x_admin_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing admin API key",
        )

    admin_key_name = admin_key_name_for(x_admin_key)
    if not admin_key_name:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin API key",
        )

    request.state.admin_key_name = admin_key_name
