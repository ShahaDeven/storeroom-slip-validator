"""HTTP API for the web UI. Thin: every decision is still made in validate.py.

  uvicorn slipcheck.api:app --port 8000

Serves the built frontend (frontend/dist) at / when it exists.
"""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from slipcheck import impact as impact_model
from slipcheck import ledger
from slipcheck.extract import LIVE_MODEL, ExtractionError, extract
from slipcheck.reference import DATA_DIR, load_reference
from slipcheck.validate import InvalidSlip, Report, validate

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
SLIPS_DIR, PHOTOS_DIR = DATA_DIR / "slips", DATA_DIR / "photos"
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

app = FastAPI(title="slipcheck")
ref = load_reference()


class ValidateRequest(BaseModel):
    slip: Any
    name: str | None = None  # when set, the check is recorded in the shift log


class PostRequest(BaseModel):
    slip: Any
    name: str
    answers: list[str] = []


def _check(slip: Any) -> Report:
    """Validate against stock as it stands after this shift's postings."""
    try:
        return validate(slip, ledger.with_posted_stock(ref))
    except InvalidSlip as e:
        raise HTTPException(422, str(e))


def _inside(base: Path, name: str) -> Path | None:
    """base/name if it is an existing file directly inside base, else None."""
    path = (base / name).resolve()
    return path if path.is_file() and path.parent == base.resolve() else None


def _sample_note(path: Path) -> str | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("_note")
    except (json.JSONDecodeError, AttributeError):
        return None


@app.get("/api/meta")
def meta() -> dict:
    return {"live_available": bool(os.environ.get("ANTHROPIC_API_KEY")), "model": LIVE_MODEL,
            "parts": len(ref.parts), "work_orders": len(ref.work_orders)}


@app.get("/api/samples")
def samples() -> list[dict]:
    out = [{"name": p.name, "kind": "slip", "note": _sample_note(p)} for p in sorted(SLIPS_DIR.glob("*.json"))]
    out += [{"name": p.name, "kind": "photo", "note": None}
            for p in sorted(PHOTOS_DIR.iterdir()) if p.suffix.lower() in IMAGE_SUFFIXES]
    return out


@app.get("/api/samples/{name}")
def sample(name: str) -> dict:
    """Return the slip JSON for a sample. Photos go through mock extraction.

    Malformed sample files are returned as raw text so the UI can show the rejection.
    """
    is_slip = name.endswith(".json")
    path = _inside(SLIPS_DIR if is_slip else PHOTOS_DIR, name)
    if path is None or (not is_slip and path.suffix.lower() not in IMAGE_SUFFIXES):
        raise HTTPException(404, f"No sample named {name}")
    if path.suffix.lower() in IMAGE_SUFFIXES:
        try:
            return {"slip": extract(path), "photo": f"/api/photos/{name}"}
        except ExtractionError as e:
            raise HTTPException(422, str(e))
    text = path.read_text(encoding="utf-8")
    try:
        return {"slip": json.loads(text), "photo": None}
    except json.JSONDecodeError as e:
        return {"slip": None, "raw": text, "error": f"{name} is not valid JSON ({e.msg} at line {e.lineno})."}


@app.get("/api/photos/{name}")
def photo(name: str) -> FileResponse:
    path = _inside(PHOTOS_DIR, name)
    if path is None or path.suffix.lower() not in IMAGE_SUFFIXES:
        raise HTTPException(404, f"No photo named {name}")
    return FileResponse(path)


@app.post("/api/validate")
def validate_slip(req: ValidateRequest) -> dict:
    report = _check(req.slip)
    posting = ledger.find_posting(report)
    if req.name and not posting:
        ledger.record_check(req.name, report)
    return report.to_dict() | {"posted": posting}


@app.post("/api/post")
def post_slip(req: PostRequest) -> dict:
    """Post to the MOCK inventory (local SQLite). Re-validates first; never trusts the client."""
    report = _check(req.slip)
    ledger.record_check(req.name, report)
    try:
        return ledger.post(req.name, report, req.answers)
    except ledger.NotPostable as e:
        raise HTTPException(409, str(e))
    except ledger.AlreadyPosted as e:
        raise HTTPException(409, str(e))


@app.get("/api/ledger")
def shift_log() -> dict:
    return ledger.summary(ref)


@app.get("/api/ledger/export.csv")
def export_for_accounting() -> Response:
    """Every posted line with the problems found at entry and how they were corrected."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=ledger.EXPORT_COLUMNS)
    writer.writeheader()
    writer.writerows(ledger.export_rows())
    name = f"storeroom-postings-{date.today().isoformat()}.csv"
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


class ImpactRequest(BaseModel):
    likely: dict[str, Any] = {}


_detection_cache: tuple | None = None


def _detection() -> tuple:
    """Detection runs the real validator over 2,100 synthetic slips (~1 s); do it once."""
    global _detection_cache
    if _detection_cache is None:
        _detection_cache = impact_model.measure_detection(ref)
    return _detection_cache


@app.get("/api/impact")
def impact_defaults() -> dict:
    """ESTIMATED manual-vs-checked comparison with the file's assumptions."""
    return impact_model.impact(ref, detection=_detection())


@app.post("/api/impact")
def impact_with(req: ImpactRequest) -> dict:
    """Same, with the 'likely' inputs replaced by the UI's slider values."""
    return impact_model.impact(ref, overrides=req.likely, detection=_detection())


@app.get("/api/data")
def reference_data() -> dict:
    """Parts with live on-hand, work orders with what was issued against them, and every stock change."""
    return ledger.data_view(ref)


@app.post("/api/ledger/reset")
def clear_shift_log() -> dict:
    ledger.reset()
    return ledger.summary(ref)


@app.post("/api/extract")
async def extract_photo(file: UploadFile = File(...), live: bool = Form(False)) -> dict:
    """Read an uploaded photo. Mock mode matches the cache by file name."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        raise HTTPException(422, f"'{file.filename}' is not an image (jpg, png, webp, gif). iPhone HEIC photos: export as JPEG first.")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(file.filename).name
        path.write_bytes(await file.read())
        try:
            return {"slip": extract(path, live=live)}
        except ExtractionError as e:
            raise HTTPException(422, str(e))


if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        # Unknown API routes are errors, not the app shell.
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, f"No API route /{path}")
        # Only serve real files inside dist/; '..' or encoded slashes must not escape it.
        target = (DIST / path).resolve()
        if path and target.is_file() and target.is_relative_to(DIST.resolve()):
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
