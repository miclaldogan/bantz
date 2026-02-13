from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union
import base64
import json
import logging
import os

import requests

from bantz.google.service_account import get_service_account_credentials
from bantz.vision.quota import MonthlyQuotaLimiter, VisionQuotaExceeded

logger = logging.getLogger(__name__)


GOOGLE_VISION_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"


class GoogleVisionError(RuntimeError):
    pass


def _b64(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


def _read_bytes(path: Union[str, Path]) -> bytes:
    return Path(path).read_bytes()


def _load_images_from_path(
    path: Union[str, Path],
    *,
    max_pdf_pages: int = 5,
) -> List[bytes]:
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"}:
        return [_read_bytes(p)]

    if suffix == ".pdf":
        try:
            import fitz  # PyMuPDF
        except Exception as e:
            raise RuntimeError("PyMuPDF is required for PDF support. Install with: pip install -e '.[vision]'") from e

        doc = fitz.open(str(p))
        try:
            images: List[bytes] = []
            page_count = min(len(doc), max_pdf_pages)
            matrix = fitz.Matrix(2, 2)  # ~144 DPI
            for idx in range(page_count):
                page = doc[idx]
                pix = page.get_pixmap(matrix=matrix)
                images.append(pix.tobytes("png"))
            return images
        finally:
            doc.close()

    raise ValueError(f"Unsupported file type for vision: {suffix}")


@dataclass
class GoogleVisionConfig:
    max_pdf_pages: int = 5
    monthly_quota: int = 1000


class GoogleVisionClient:
    """Google Vision API client (REST).

    Uses service-account credentials and sends base64-encoded content.
    """

    def __init__(
        self,
        *,
        credentials_path: Optional[str] = None,
        quota_limiter: Optional[MonthlyQuotaLimiter] = None,
        session: Optional[requests.Session] = None,
        max_pdf_pages: int = 5,
    ):
        self._credentials_path = credentials_path
        self._quota = quota_limiter or MonthlyQuotaLimiter.from_env()
        self._session = session or requests.Session()
        self._max_pdf_pages = max_pdf_pages

    def _authorized_headers(self) -> Dict[str, str]:
        creds = get_service_account_credentials(
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
            service_account_path=self._credentials_path,
        )

        try:
            from google.auth.transport.requests import Request  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Google auth dependencies are not installed. Install with: pip install -e '.[vision]'"
            ) from e

        creds.refresh(Request())
        return {"Authorization": f"Bearer {creds.token}"}

    def annotate(
        self,
        *,
        images: Sequence[bytes],
        features: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        # Free-tier safety: count 1 request per API call.
        self._quota.check_and_increment(units=1)

        headers = {
            "Content-Type": "application/json",
            **self._authorized_headers(),
        }

        reqs = [
            {
                "image": {"content": _b64(content)},
                "features": list(features),
            }
            for content in images
        ]

        payload = {"requests": reqs}
        resp = self._session.post(GOOGLE_VISION_ENDPOINT, headers=headers, data=json.dumps(payload), timeout=30)
        if resp.status_code >= 400:
            raise GoogleVisionError(f"Google Vision API error {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        # API returns errors per response
        for r in data.get("responses", []) or []:
            if "error" in r:
                raise GoogleVisionError(f"Google Vision response error: {r['error']}")
        return data

    def ocr_path(self, path: Union[str, Path]) -> str:
        images = _load_images_from_path(path, max_pdf_pages=self._max_pdf_pages)
        data = self.annotate(images=images, features=[{"type": "TEXT_DETECTION"}])

        texts: List[str] = []
        for r in data.get("responses", []) or []:
            full = (r.get("fullTextAnnotation") or {}).get("text")
            if full:
                texts.append(full)
                continue
            anns = r.get("textAnnotations") or []
            if anns:
                texts.append((anns[0] or {}).get("description") or "")

        return "\n\n".join([t.strip() for t in texts if t and t.strip()]).strip()

    def describe_path(
        self,
        path: Union[str, Path],
        *,
        max_labels: int = 10,
        include_faces: bool = True,
        include_logos: bool = True,
    ) -> Dict[str, Any]:
        images = _load_images_from_path(path, max_pdf_pages=self._max_pdf_pages)

        features: List[Dict[str, Any]] = [
            {"type": "LABEL_DETECTION", "maxResults": max_labels},
        ]
        if include_logos:
            features.append({"type": "LOGO_DETECTION", "maxResults": 10})
        if include_faces:
            features.append({"type": "FACE_DETECTION", "maxResults": 5})

        data = self.annotate(images=images, features=features)

        # Aggregate labels across pages.
        label_scores: Dict[str, float] = {}
        logos: List[Dict[str, Any]] = []
        faces: List[Dict[str, Any]] = []

        for r in data.get("responses", []) or []:
            for lab in r.get("labelAnnotations") or []:
                desc = (lab or {}).get("description")
                score = float((lab or {}).get("score") or 0.0)
                if not desc:
                    continue
                label_scores[desc] = max(label_scores.get(desc, 0.0), score)

            for logo in r.get("logoAnnotations") or []:
                desc = (logo or {}).get("description")
                score = float((logo or {}).get("score") or 0.0)
                if desc:
                    logos.append({"description": desc, "score": score})

            for face in r.get("faceAnnotations") or []:
                faces.append(
                    {
                        "detectionConfidence": (face or {}).get("detectionConfidence"),
                        "landmarkingConfidence": (face or {}).get("landmarkingConfidence"),
                        "joyLikelihood": (face or {}).get("joyLikelihood"),
                        "sorrowLikelihood": (face or {}).get("sorrowLikelihood"),
                        "angerLikelihood": (face or {}).get("angerLikelihood"),
                        "surpriseLikelihood": (face or {}).get("surpriseLikelihood"),
                        "headwearLikelihood": (face or {}).get("headwearLikelihood"),
                    }
                )

        labels = [
            {"label": k, "score": v}
            for k, v in sorted(label_scores.items(), key=lambda kv: kv[1], reverse=True)
        ]

        return {
            "labels": labels[:max_labels],
            "logos": logos,
            "faces": faces,
        }


_DEFAULT_CLIENT: Optional[GoogleVisionClient] = None


def get_default_google_vision_client() -> GoogleVisionClient:
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = GoogleVisionClient()
    return _DEFAULT_CLIENT


def vision_ocr(image_path: Union[str, Path]) -> str:
    """Extract text from an image or PDF using Google Vision (service account)."""
    return get_default_google_vision_client().ocr_path(image_path)


def vision_describe(image_path: Union[str, Path]) -> Dict[str, Any]:
    """Describe an image or PDF using Google Vision labels/logos/faces."""
    return get_default_google_vision_client().describe_path(image_path)
