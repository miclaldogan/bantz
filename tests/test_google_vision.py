from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict

import pytest

from bantz.vision.google_vision import GoogleVisionClient, GoogleVisionError
from bantz.vision.quota import MonthlyQuotaLimiter


class _DummyResponse:
    def __init__(self, status_code: int, payload: Dict[str, Any]):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> Dict[str, Any]:
        return self._payload


class _DummySession:
    def __init__(self, responder):
        self._responder = responder
        self.last_request = None

    def post(self, url: str, headers=None, data=None, timeout=None):
        self.last_request = {
            "url": url,
            "headers": headers,
            "data": data,
            "timeout": timeout,
        }
        return self._responder(url=url, headers=headers, data=data, timeout=timeout)


def test_annotate_sends_base64_and_features(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    quota = MonthlyQuotaLimiter(max_requests_per_month=1000, quota_path=tmp_path / "quota.json")

    def responder(**kwargs):
        return _DummyResponse(
            200,
            {
                "responses": [
                    {
                        "textAnnotations": [
                            {"description": "HELLO"},
                        ]
                    }
                ]
            },
        )

    session = _DummySession(responder)
    client = GoogleVisionClient(quota_limiter=quota, session=session)

    monkeypatch.setattr(client, "_authorized_headers", lambda: {"Authorization": "Bearer test"})

    img = b"fake-image-bytes"
    out = client.annotate(images=[img], features=[{"type": "TEXT_DETECTION"}])
    assert out["responses"][0]["textAnnotations"][0]["description"] == "HELLO"

    sent = session.last_request
    assert sent is not None
    assert sent["headers"]["Authorization"] == "Bearer test"

    payload = sent["data"]
    assert "TEXT_DETECTION" in payload

    expected_b64 = base64.b64encode(img).decode("ascii")
    assert expected_b64 in payload


def test_ocr_path_uses_full_text_annotation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    quota = MonthlyQuotaLimiter(max_requests_per_month=1000, quota_path=tmp_path / "quota.json")

    def responder(**kwargs):
        return _DummyResponse(
            200,
            {
                "responses": [
                    {"fullTextAnnotation": {"text": "Line1\nLine2\n"}},
                ]
            },
        )

    session = _DummySession(responder)
    client = GoogleVisionClient(quota_limiter=quota, session=session)
    monkeypatch.setattr(client, "_authorized_headers", lambda: {"Authorization": "Bearer test"})

    img_path = tmp_path / "x.png"
    img_path.write_bytes(b"img")

    text = client.ocr_path(img_path)
    assert text == "Line1\nLine2"


def test_describe_path_aggregates_labels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    quota = MonthlyQuotaLimiter(max_requests_per_month=1000, quota_path=tmp_path / "quota.json")

    def responder(**kwargs):
        return _DummyResponse(
            200,
            {
                "responses": [
                    {
                        "labelAnnotations": [
                            {"description": "Cat", "score": 0.8},
                            {"description": "Pet", "score": 0.7},
                        ],
                        "logoAnnotations": [{"description": "ACME", "score": 0.9}],
                        "faceAnnotations": [{"detectionConfidence": 0.5, "joyLikelihood": "VERY_LIKELY"}],
                    },
                    {
                        "labelAnnotations": [
                            {"description": "Cat", "score": 0.85},
                        ]
                    },
                ]
            },
        )

    session = _DummySession(responder)
    client = GoogleVisionClient(quota_limiter=quota, session=session)
    monkeypatch.setattr(client, "_authorized_headers", lambda: {"Authorization": "Bearer test"})

    img_path = tmp_path / "x.jpg"
    img_path.write_bytes(b"img")

    result = client.describe_path(img_path, max_labels=10)
    labels = {x["label"]: x["score"] for x in result["labels"]}

    assert labels["Cat"] == pytest.approx(0.85)
    assert labels["Pet"] == pytest.approx(0.7)
    assert result["logos"][0]["description"] == "ACME"
    assert result["faces"][0]["joyLikelihood"] == "VERY_LIKELY"


def test_annotate_raises_on_per_response_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    quota = MonthlyQuotaLimiter(max_requests_per_month=1000, quota_path=tmp_path / "quota.json")

    def responder(**kwargs):
        return _DummyResponse(
            200,
            {"responses": [{"error": {"message": "boom", "code": 400}}]},
        )

    session = _DummySession(responder)
    client = GoogleVisionClient(quota_limiter=quota, session=session)
    monkeypatch.setattr(client, "_authorized_headers", lambda: {"Authorization": "Bearer test"})

    with pytest.raises(GoogleVisionError):
        client.annotate(images=[b"img"], features=[{"type": "TEXT_DETECTION"}])
