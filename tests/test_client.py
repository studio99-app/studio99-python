"""Offline tests: urlopen is replaced by a fake. Run: python -m unittest discover -s tests"""

import io
import json
import os
import sys
import unittest
import urllib.error
from email.message import Message
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from studio99 import Studio99, Studio99Error  # noqa: E402


def _headers(d=None):
    m = Message()
    for k, v in (d or {}).items():
        m[k] = v
    return m


class _Resp:
    def __init__(self, body, status=200, headers=None):
        self.status = status
        self._raw = json.dumps(body).encode()
        self.headers = _headers(headers)

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(status, body, headers=None):
    return urllib.error.HTTPError("u", status, "err", _headers(headers), io.BytesIO(json.dumps(body).encode()))


class Fake:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, req, timeout=None):
        self.calls.append(req)
        r = self.responses.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r


class ClientTests(unittest.TestCase):
    def test_generate_sends_key_and_body(self):
        fake = Fake(_Resp({"success": True, "data": {"generatedResults": [], "metadata": {}},
                           "usage": {"monthlyUsed": 4, "monthlyLimit": 100, "remaining": 96}},
                          headers={"X-RateLimit-Limit": "5", "X-RateLimit-Remaining": "4", "X-RateLimit-Reset": "1790000000"}))
        with mock.patch("urllib.request.urlopen", fake):
            res = Studio99("k_test").generate("shubh vivah", language="hindi", count=4)
        req = fake.calls[0]
        self.assertEqual(req.full_url, "https://studio99.app/api/v1/generate")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("X-api-key"), "k_test")
        self.assertEqual(json.loads(req.data), {"text": "shubh vivah", "language": "hindi", "count": 4})
        self.assertEqual(res.usage["remaining"], 96)
        self.assertEqual(res.rate_limit.remaining, 4)

    def test_unicode_body_is_utf8(self):
        fake = Fake(_Resp({"success": True, "data": {}}))
        with mock.patch("urllib.request.urlopen", fake):
            Studio99("k").render("शुभ विवाह", "font-1", font_size=96)
        self.assertEqual(json.loads(fake.calls[0].data.decode("utf-8"))["text"], "शुभ विवाह")

    def test_query_skips_none(self):
        fake = Fake(_Resp({"success": True, "data": {"fonts": []}}))
        with mock.patch("urllib.request.urlopen", fake):
            Studio99("k").fonts(language="marathi", limit=10)
        self.assertEqual(fake.calls[0].full_url, "https://studio99.app/api/v1/fonts?language=marathi&limit=10")

    def test_api_error_not_retried_for_credits(self):
        fake = Fake(_http_error(429, {"success": False, "error": {"code": "INSUFFICIENT_CREDITS", "message": "used up"}}))
        with mock.patch("urllib.request.urlopen", fake):
            with self.assertRaises(Studio99Error) as ctx:
                Studio99("k").generate("x")
        self.assertEqual(ctx.exception.code, "INSUFFICIENT_CREDITS")
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(len(fake.calls), 1)

    def test_rate_limit_is_retried(self):
        fake = Fake(_http_error(429, {"success": False, "error": {"code": "RATE_LIMIT_EXCEEDED", "message": "slow"}}),
                    _Resp({"success": True, "data": {"fonts": []}}))
        with mock.patch("urllib.request.urlopen", fake), mock.patch("time.sleep"):
            res = Studio99("k").fonts()
        self.assertEqual(res.data, {"fonts": []})
        self.assertEqual(len(fake.calls), 2)

    def test_post_network_error_not_retried(self):
        fake = Fake(urllib.error.URLError("reset"), _Resp({"success": True, "data": {}}))
        with mock.patch("urllib.request.urlopen", fake):
            with self.assertRaises(Studio99Error) as ctx:
                Studio99("k").generate("x")
        self.assertEqual(ctx.exception.code, "NETWORK_ERROR")
        self.assertEqual(len(fake.calls), 1)

    def test_get_network_error_is_retried(self):
        fake = Fake(urllib.error.URLError("reset"), _Resp({"success": True, "data": {"fonts": []}}))
        with mock.patch("urllib.request.urlopen", fake), mock.patch("time.sleep"):
            Studio99("k").fonts()
        self.assertEqual(len(fake.calls), 2)

    def test_health_unwrapped(self):
        fake = Fake(_Resp({"status": "ok", "version": "1.2", "product": "Studio99 Indic Typography API"}))
        with mock.patch("urllib.request.urlopen", fake):
            self.assertEqual(Studio99("k").health().data["version"], "1.2")

    def test_requires_key_and_hides_it(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                Studio99()
        self.assertNotIn("secret", repr(Studio99("secret")))


if __name__ == "__main__":
    unittest.main()
