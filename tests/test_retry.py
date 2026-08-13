import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from retry import is_retryable_request_error, retry_with_backoff


class TestIsRetryableRequestError:
    def test_connection_error_is_retryable(self):
        assert is_retryable_request_error(requests.exceptions.ConnectionError("refused")) is True

    def test_timeout_is_retryable(self):
        assert is_retryable_request_error(requests.exceptions.Timeout("timed out")) is True

    @pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
    def test_5xx_and_429_are_retryable(self, status_code):
        response = Mock(status_code=status_code)
        error = requests.exceptions.HTTPError(response=response)
        assert is_retryable_request_error(error) is True

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    def test_4xx_is_not_retryable(self, status_code):
        response = Mock(status_code=status_code)
        error = requests.exceptions.HTTPError(response=response)
        assert is_retryable_request_error(error) is False

    def test_http_error_without_response_is_not_retryable(self):
        assert is_retryable_request_error(requests.exceptions.HTTPError("no response")) is False

    def test_unrelated_exception_is_not_retryable(self):
        assert is_retryable_request_error(ValueError("not a request error")) is False


class TestRetryWithBackoff:
    @patch("retry.time.sleep")
    def test_succeeds_first_try_no_retry(self, mock_sleep):
        func = Mock(return_value="ok")
        wrapped = retry_with_backoff(3, 1, lambda e: True)(func)

        result = wrapped()

        assert result == "ok"
        func.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("retry.time.sleep")
    def test_retries_until_success(self, mock_sleep):
        func = Mock(__name__="func", side_effect=[ConnectionError("a"), ConnectionError("b"), "ok"])
        wrapped = retry_with_backoff(3, 1, lambda e: True)(func)

        result = wrapped()

        assert result == "ok"
        assert func.call_count == 3

    @patch("retry.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep):
        func = Mock(__name__="func", side_effect=[ConnectionError("a"), ConnectionError("b"), "ok"])
        wrapped = retry_with_backoff(3, 2, lambda e: True)(func)

        wrapped()

        assert mock_sleep.call_args_list == [((2,),), ((4,),)]

    @patch("retry.time.sleep")
    def test_exhausts_retries_then_raises(self, mock_sleep):
        func = Mock(__name__="func", side_effect=ConnectionError("persistent"))
        wrapped = retry_with_backoff(3, 1, lambda e: True)(func)

        with pytest.raises(ConnectionError, match="persistent"):
            wrapped()

        # max_retries=3 means 3 retries after the first attempt, so 4 total
        assert func.call_count == 4

    @patch("retry.time.sleep")
    def test_non_retryable_exception_raises_immediately(self, mock_sleep):
        func = Mock(side_effect=ValueError("bad input"))
        wrapped = retry_with_backoff(3, 1, lambda e: False)(func)

        with pytest.raises(ValueError, match="bad input"):
            wrapped()

        func.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("retry.time.sleep")
    def test_preserves_function_metadata(self, mock_sleep):
        @retry_with_backoff(3, 1, lambda e: True)
        def some_function():
            """docstring"""

        assert some_function.__name__ == "some_function"
        assert some_function.__doc__ == "docstring"
