import functools
import logging
import time
from collections.abc import Callable
from typing import TypeVar

import requests

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def is_retryable_request_error(e: Exception) -> bool:
    """True for transient network failures and 429/5xx responses - the
    kinds of failures a retry can plausibly fix. False for 4xx client
    errors (bad params, invalid API key, no data for the requested
    period) and anything else, where retrying just repeats a failure
    that won't change.
    """
    if isinstance(e, requests.exceptions.HTTPError):
        response = e.response
        return response is not None and response.status_code in _RETRYABLE_STATUS_CODES
    return isinstance(e, requests.exceptions.ConnectionError | requests.exceptions.Timeout)


def retry_with_backoff(
    max_retries: int, base_delay: float, is_retryable: Callable[[Exception], bool]
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Retry a function up to max_retries times (max_retries + 1 total
    attempts) on exceptions is_retryable accepts, waiting base_delay,
    2*base_delay, 4*base_delay, ... between attempts. Exceptions
    is_retryable rejects propagate immediately, on the first attempt.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt >= max_retries or not is_retryable(e):
                        raise
                    delay = base_delay * (2**attempt)
                    attempt += 1
                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt}/{max_retries}): {e}. "
                        f"Retrying in {delay}s"
                    )
                    time.sleep(delay)

        return wrapper

    return decorator
