from __future__ import annotations

import logging
from contextvars import ContextVar
from logging.config import dictConfig


request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
request_method_var: ContextVar[str] = ContextVar("request_method", default="-")
request_path_var: ContextVar[str] = ContextVar("request_path", default="-")


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("-")
        record.request_method = request_method_var.get("-")
        record.request_path = request_path_var.get("-")
        return True


def setup_logging(level: int = logging.INFO) -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "request_context": {
                    "()": RequestContextFilter,
                }
            },
            "formatters": {
                "standard": {
                    "format": (
                        "%(asctime)s | %(levelname)s | %(name)s | "
                        "req=%(request_id)s | %(request_method)s %(request_path)s | %(message)s"
                    )
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": level,
                    "formatter": "standard",
                    "filters": ["request_context"],
                }
            },
            "root": {
                "level": level,
                "handlers": ["console"],
            },
        }
    )

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
