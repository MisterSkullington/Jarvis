from __future__ import annotations

import json
import logging
import sys
from typing import Any, Dict, Optional


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload: Dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, self.datefmt),
        }

        # Optional extras commonly used in services
        for attr in ("service", "correlation_id", "intent", "user_id"):
            if hasattr(record, attr):
                payload[attr] = getattr(record, attr)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", service_name: Optional[str] = None) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Clear any existing handlers (so multiple configure calls don't duplicate logs)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)

    if service_name:
        # Attach default service name to all log records
        old_factory = logging.getLogRecordFactory()

        def record_factory(*args, **kwargs):  # type: ignore[override]
            record = old_factory(*args, **kwargs)
            if not hasattr(record, "service"):
                record.service = service_name
            return record

        logging.setLogRecordFactory(record_factory)

