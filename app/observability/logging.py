import logging
from typing import Any

logger = logging.getLogger("rate_limiter")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s level=%(levelname)s logger=%(name)s %(message)s",
    )


def log_rate_limit_decision(**fields: Any) -> None:
    payload = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    logger.info("rate_limit_decision %s", payload)
