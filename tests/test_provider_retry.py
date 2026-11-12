import io
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from providers import ProviderHTTPError, post_json, retry_delay, classify_http_error


def http_error(code, retry_after=None, body=b''):
    headers = {} if retry_after is None else {'Retry-After': retry_after}
    return HTTPError('https://example.com', code, 'error', headers, io.BytesIO(body))


class RetryTests(unittest.TestCase):
    @patch('providers.time.sleep')
    @patch('providers.urllib.request.urlopen')
    def test_daily_quota_is_not_retried(self, open_url, sleep):
        error = http_error(429, body=b'{"error":{"message":"Free requests per day exhausted"}}')
        open_url.side_effect = error
        with self.assertRaises(ProviderHTTPError) as caught:
            post_json('https://example.com', {}, {})
        self.assertEqual(caught.exception.error_kind, 'daily_quota')
        sleep.assert_not_called()

    def test_upstream_error_is_classified_without_retaining_body(self):
        error = http_error(429, body=b'{"error":{"metadata":{"provider_name":"example"}}}')
        self.assertEqual(classify_http_error(error), 'upstream_rate_limit')
        error.close()

    @patch('providers.time.sleep')
    @patch('providers.urllib.request.urlopen')
    def test_429_waits_then_returns_response(self, open_url, sleep):
        response = MagicMock()
        response.__enter__.return_value = io.StringIO('{"ok": true}')
        open_url.side_effect = [http_error(429, '2'), response]
        self.assertEqual(post_json('https://example.com', {}, {}), {'ok': True})
        sleep.assert_called_once_with(2)
        self.assertEqual(open_url.call_count, 2)

    @patch('providers.time.sleep')
    @patch('providers.urllib.request.urlopen')
    def test_persistent_429_stops(self, open_url, sleep):
        open_url.side_effect = [http_error(429, '1') for _ in range(5)]
        with self.assertRaises(ProviderHTTPError) as caught:
            post_json('https://example.com', {}, {})
        self.assertEqual(caught.exception.http_status, 429)
        self.assertEqual(open_url.call_count, 5)
        self.assertEqual(sleep.call_count, 4)

    @patch('providers.time.sleep')
    @patch('providers.urllib.request.urlopen')
    def test_no_retry_auth_or_long_quota_wait(self, open_url, sleep):
        for code, delay in ((401, None), (403, None), (429, '3600')):
            with self.subTest(code=code):
                open_url.reset_mock()
                open_url.side_effect = http_error(code, delay)
                with self.assertRaises(ProviderHTTPError):
                    post_json('https://example.com', {}, {})
                self.assertEqual(open_url.call_count, 1)
        sleep.assert_not_called()

    def test_invalid_delay_and_http_date(self):
        self.assertEqual(retry_delay('invalid', 1), 20)
        self.assertEqual(retry_delay('nan', 0), 10)
        with patch('providers.time.time', return_value=0):
            self.assertEqual(retry_delay('Thu, 01 Jan 1970 00:00:15 GMT', 0), 15)
