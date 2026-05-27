import json
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError
from rentablez.sender import send, SendOutcome


def _mock_response(status: int, body: bytes = b"{}"):
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_2xx_returns_sent():
    with patch("urllib.request.urlopen", return_value=_mock_response(200)):
        outcome = send("https://api.example.com/checkin", "TOKEN", {"a": 1})
        assert outcome == SendOutcome.SENT


def test_201_returns_sent():
    with patch("urllib.request.urlopen", return_value=_mock_response(201)):
        outcome = send("https://api.example.com/checkin", "TOKEN", {"a": 1})
        assert outcome == SendOutcome.SENT


def test_400_returns_permanent_failure():
    err = HTTPError("https://x", 400, "Bad Request", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        outcome = send("https://x", "T", {"a": 1})
        assert outcome == SendOutcome.PERMANENT_FAILURE


def test_401_returns_permanent_failure():
    err = HTTPError("https://x", 401, "Unauthorized", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        outcome = send("https://x", "T", {"a": 1})
        assert outcome == SendOutcome.PERMANENT_FAILURE


def test_408_returns_transient():
    err = HTTPError("https://x", 408, "Request Timeout", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        outcome = send("https://x", "T", {"a": 1})
        assert outcome == SendOutcome.TRANSIENT_FAILURE


def test_429_returns_transient():
    err = HTTPError("https://x", 429, "Too Many Requests", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        outcome = send("https://x", "T", {"a": 1})
        assert outcome == SendOutcome.TRANSIENT_FAILURE


def test_500_returns_transient():
    err = HTTPError("https://x", 500, "Server Error", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        outcome = send("https://x", "T", {"a": 1})
        assert outcome == SendOutcome.TRANSIENT_FAILURE


def test_network_error_returns_transient():
    with patch("urllib.request.urlopen", side_effect=URLError("no route")):
        outcome = send("https://x", "T", {"a": 1})
        assert outcome == SendOutcome.TRANSIENT_FAILURE


def test_includes_authorization_header():
    captured = {}

    def fake_urlopen(req, *args, **kwargs):
        captured["headers"] = dict(req.header_items())
        captured["data"] = req.data
        return _mock_response(200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        send("https://api.example.com", "MYTOKEN", {"status": "ok"})

    assert captured["headers"]["Authorization"] == "Bearer MYTOKEN"
    assert captured["headers"]["Content-type"] == "application/json"
    assert json.loads(captured["data"]) == {"status": "ok"}


def test_timeout_propagated_to_urlopen():
    captured = {}

    def fake_urlopen(req, *args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return _mock_response(200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        send("https://x", "T", {})

    assert captured["timeout"] == 30
