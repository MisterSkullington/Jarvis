"""
Vision microservice (Phase 4) — FastAPI on port 8003.

Endpoints:
  POST /describe         Accept image bytes (multipart) or a local file path (JSON).
                         Returns {description, ocr_text}.
  POST /capture_describe Capture the screen, then describe it. No body required.
  GET  /health

Description strategy (best available, in order):
  1. Ollama multimodal (llava or configured model) — sends base64 image
  2. OCR-only fallback via pytesseract (if installed)
  3. Plain stub response

Screen capture requires the `vision` optional dependencies:
  pip install "jarvis-assistant[vision]"
"""
from __future__ import annotations

import base64
import io
import logging
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from jarvis_core import load_config, configure_logging

LOG = logging.getLogger(__name__)
app = FastAPI(title="Jarvis Vision Service", version="0.1.0")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class DescribeFileRequest(BaseModel):
    file_path: str


class VisionResponse(BaseModel):
    description: str = ""
    ocr_text: str = ""


# ---------------------------------------------------------------------------
# Vision helpers
# ---------------------------------------------------------------------------

def _ocr_image(image_bytes: bytes) -> str:
    """Extract text from image bytes using pytesseract (optional)."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(img).strip()
    except ImportError:
        return ""
    except Exception as exc:
        LOG.warning("OCR failed: %s", exc)
        return ""


def _describe_with_ollama(image_bytes: bytes, config) -> str:
    """Send image to Ollama multimodal model (llava) for description."""
    vision_model = getattr(getattr(config, "vision", None), "ollama_vision_model", "llava")
    llm_url = getattr(getattr(config, "llm", None), "base_url", "http://localhost:11434")
    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model": vision_model,
        "messages": [
            {
                "role": "user",
                "content": "Describe what you see in this image concisely.",
                "images": [b64],
            }
        ],
        "stream": False,
    }
    try:
        with httpx.Client(timeout=60) as client:
            r = client.post(f"{llm_url.rstrip('/')}/api/chat", json=payload)
            if r.is_success:
                return ((r.json().get("message") or {}).get("content") or "").strip()
    except Exception as exc:
        LOG.warning("Ollama vision failed: %s", exc)
    return ""


def _capture_screen(config) -> bytes:
    """Capture the screen using mss and return PNG bytes."""
    try:
        import mss
        import mss.tools
        region = getattr(getattr(config, "vision", None), "screen_capture_region", None)
        with mss.mss() as sct:
            monitor = region if region else sct.monitors[0]
            shot = sct.grab(monitor)
            return mss.tools.to_png(shot.rgb, shot.size)
    except ImportError:
        raise HTTPException(status_code=503, detail="mss not installed. Run: pip install 'jarvis-assistant[vision]'")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Screen capture failed: {exc}")


def _process_image(image_bytes: bytes, config) -> VisionResponse:
    """Run description + OCR on image bytes."""
    description = _describe_with_ollama(image_bytes, config)
    ocr_text = _ocr_image(image_bytes)

    if not description and not ocr_text:
        description = "Image captured but no description available. Install llava in Ollama or pytesseract for OCR."

    return VisionResponse(description=description, ocr_text=ocr_text)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/describe", response_model=VisionResponse)
async def describe(file: UploadFile = File(...)) -> VisionResponse:
    """Accept an image upload and return description + OCR text."""
    config = load_config()
    image_bytes = await file.read()
    return _process_image(image_bytes, config)


@app.post("/describe_path", response_model=VisionResponse)
def describe_path(req: DescribeFileRequest) -> VisionResponse:
    """Describe an image from a local file path."""
    config = load_config()
    path = Path(req.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")
    return _process_image(path.read_bytes(), config)


@app.post("/capture_describe", response_model=VisionResponse)
def capture_describe() -> VisionResponse:
    """Capture the screen and describe it."""
    config = load_config()
    image_bytes = _capture_screen(config)
    return _process_image(image_bytes, config)


@app.get("/health")
def health() -> Dict[str, str]:
    try:
        import mss  # noqa: F401
        capture_ok = "ok"
    except ImportError:
        capture_ok = "mss not installed"
    try:
        import pytesseract  # noqa: F401
        ocr_ok = "ok"
    except ImportError:
        ocr_ok = "pytesseract not installed"
    return {
        "status": "ok",
        "service": "vision",
        "screen_capture": capture_ok,
        "ocr": ocr_ok,
    }


def main() -> None:
    import uvicorn
    config = load_config()
    configure_logging(config.log_level, "vision")
    uvicorn.run(app, host="0.0.0.0", port=8003)


if __name__ == "__main__":
    main()
