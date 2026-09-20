"""Temporary startup instrumentation; no runtime policy changes."""
import logging
from contextlib import contextmanager
from time import perf_counter

logger = logging.getLogger("opctagmanager.startup_trace")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)


@contextmanager
def trace_step(marker, **fields):
    detail = " ".join(f"{key}={value}" for key, value in fields.items())
    started = perf_counter()
    logger.info("%s START %s", marker, detail)
    try:
        yield
    except BaseException as exc:
        logger.info("%s FAILED elapsed=%.3fs exception=%s %s", marker,
                    perf_counter() - started, type(exc).__name__, detail)
        raise
    else:
        logger.info("%s END elapsed=%.3fs %s", marker, perf_counter() - started, detail)
