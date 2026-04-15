from __future__ import annotations

import logging
from logging.config import dictConfig

from shared_python.tracing import get_correlation_id


class CorrelationIdFilter(logging.Filter):
    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self.service_name
        record.correlation_id = get_correlation_id()
        return True


# A compact structured-like formatter keeps logs readable locally and parseable in production.
def configure_logging(service_name: str, level: str) -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "correlation": {
                    "()": CorrelationIdFilter,
                    "service_name": service_name,
                }
            },
            "formatters": {
                "standard": {
                    "format": "%(asctime)s | %(levelname)s | service=%(service)s | correlation_id=%(correlation_id)s | %(name)s | %(message)s",
                }
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "filters": ["correlation"],
                }
            },
            "root": {"handlers": ["default"], "level": level},
        }
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
