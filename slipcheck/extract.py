"""Photo -> slip JSON. This is the only part of the prototype that uses AI.

Two modes:
  mock (default) - replay a cached extraction from data/extractions/<photo stem>.json.
                   No API key, no network. Each cache file says where it came from.
  live           - send the photo to a vision model (Claude Haiku) and ask it to
                   transcribe, not interpret, with a confidence per field.
                   Needs ANTHROPIC_API_KEY. Roughly a fraction of a cent per slip.

Either way the output has the same schema the validator reads, so everything
downstream of this module is identical for typed and photographed slips.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from datetime import date
from pathlib import Path

from slipcheck.reference import DATA_DIR

CACHE_DIR = DATA_DIR / "extractions"
LIVE_MODEL = os.environ.get("SLIPCHECK_MODEL", "claude-haiku-5-5")

PROMPT = """You are reading a photo of a handwritten storeroom parts checkout slip.

Transcribe what is written. Do NOT correct, normalize, look up, or infer anything:
if the slip says "2" with no unit, return qty "2" and unit null. If a part number
is missing, return null for it; do not guess one from the part name.

For every field return {"value": ..., "raw": "<characters as written>", "confidence": 0.0-1.0},
where confidence is how sure you are that you read the handwriting correctly.
If a field is blank, value is null and confidence is 1.0.
If a field is present but you cannot read it, value is null, raw is your best
attempt (use ? for unreadable characters), and confidence is below 0.5.

Return ONLY a JSON object of this shape, no prose:
{
  "wo_number": F, "date": F, "taken_by": F, "location": F,
  "signature": {"value": true|false, "confidence": ...},
  "items": [ {"part_number": F, "part_name": F, "qty": F, "unit": F} ]
}
where F is the field object above. If the image is not a checkout slip, return {"not_a_slip": true}."""


class ExtractionError(RuntimeError):
    pass


def cache_path(photo: Path) -> Path:
    return CACHE_DIR / f"{photo.stem}.json"


def extract_mock(photo: Path) -> dict:
    path = cache_path(photo)
    if not path.exists():
        raise ExtractionError(
            f"No cached extraction for '{photo.name}' (looked for {path}). "
            "Run with --live once (needs ANTHROPIC_API_KEY) and --save-extraction to create it.")
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ExtractionError(f"Model did not return JSON: {text[:200]!r}") from e
    if not isinstance(data, dict):
        raise ExtractionError("Model returned JSON that is not an object.")
    return data


def extract_live(photo: Path) -> dict:
    try:
        import anthropic
    except ImportError as e:
        raise ExtractionError("Live mode needs the 'anthropic' package (pip install anthropic).") from e
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ExtractionError("Live mode needs ANTHROPIC_API_KEY set. Use mock mode to run without one.")

    media_type = mimetypes.guess_type(photo.name)[0] or "image/jpeg"
    if media_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        raise ExtractionError(f"'{photo.name}' is not a supported image type ({media_type}).")
    image = base64.standard_b64encode(photo.read_bytes()).decode()

    msg = anthropic.Anthropic().messages.create(
        model=LIVE_MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image}},
            {"type": "text", "text": PROMPT},
        ]}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text")
    data = _parse_json(text)
    data["_provenance"] = {
        "kind": "live model output",
        "model": LIVE_MODEL,
        "photo": photo.name,
        "extracted_on": date.today().isoformat(),
        "usage": {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens},
    }
    return data


def extract(photo: Path, live: bool = False, save: bool = False) -> dict:
    if not photo.exists():
        raise ExtractionError(f"Photo not found: {photo}")
    data = extract_live(photo) if live else extract_mock(photo)
    if data.get("not_a_slip"):
        raise ExtractionError(f"'{photo.name}' does not look like a checkout slip.")
    if live and save:
        cache_path(photo).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data
