"""Track mirrored backup failures so the UI can warn the treasurer."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def record_failure(app: Any, exc: BaseException | None = None, detail: str | None = None) -> None:
    msg = (detail or (str(exc) if exc else "Unknown error"))[:500]
    app.config["BACKUP_LAST_ERROR"] = msg
    app.config["BACKUP_LAST_ERROR_AT"] = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    if exc is not None:
        app.logger.error("Lodge Office backup mirror failed: %s", msg, exc_info=exc)
    else:
        app.logger.error("Lodge Office backup mirror failed: %s", msg)


def clear_failure(app: Any) -> None:
    app.config["BACKUP_LAST_ERROR"] = None
    app.config["BACKUP_LAST_ERROR_AT"] = None
