"""HTTP API for receiving. Thin: every decision is made in validate.py.

Mounted by slipcheck.api. Sample receipts are served only by id (R01, R02 ...), never by path.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from typing import Any

import pymupdf
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from slipcheck.evidence import receipt_evidence
from slipcheck.extract import ExtractionError
from slipcheck.receiving import store
from slipcheck.receiving.extract import read_receipt
from slipcheck.receiving.reference import RECEIVING_DIR, load_receiving, norm_receipt_no
from slipcheck.receiving.validate import validate_receipt
from slipcheck.validate import InvalidSlip, as_field

router = APIRouter(prefix="/api/receiving")
RECEIPTS_DIR = RECEIVING_DIR / "receipts"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


class ReceiptRequest(BaseModel):
    receipt: Any
    name: str | None = None
    answers: list[str] = []


def _samples() -> list[dict]:
    with open(RECEIVING_DIR / "scenarios.csv", newline="", encoding="utf-8") as f:
        scenarios = {r["id"]: r for r in csv.DictReader(f)}
    out = []
    for p in sorted(RECEIPTS_DIR.iterdir()):
        if p.stem in scenarios and p.suffix.lower() in IMAGE_SUFFIXES | {".pdf"}:
            s = scenarios[p.stem]
            out.append({"id": p.stem, "file": p.name, "kind": "pdf" if p.suffix.lower() == ".pdf" else "image",
                        "receipt_number": s["receipt_number"], "po_number": s["po_number"], "shows": s["shows"]})
    return out


def _sample_path(sample_id: str) -> Path:
    match = next((s for s in _samples() if s["id"] == sample_id), None)
    if match is None:
        raise HTTPException(404, f"No sample receipt named {sample_id}")
    return RECEIPTS_DIR / match["file"]


def _reference_for(reading: Any):
    """The PO state as it was before this receipt: if it is already posted, leave it out of the history."""
    number = norm_receipt_no(as_field(reading.get("receipt_number")).value) if isinstance(reading, dict) else ""
    posted = store.posted_receipts()
    return load_receiving(posted=[p for p in posted if norm_receipt_no(p["receipt_number"]) != number]), \
        (store.find_posted(number) if number else None)


def _check(reading: Any, with_ref: bool = False):
    ref, posted = _reference_for(reading)
    try:
        report = validate_receipt(reading, ref)
    except InvalidSlip as e:
        raise HTTPException(422, str(e))
    return (report, posted, ref) if with_ref else (report, posted)


@router.get("/samples")
def samples() -> list[dict]:
    return _samples()


@router.get("/samples/{sample_id}")
def sample(sample_id: str) -> dict:
    path = _sample_path(sample_id)
    try:
        reading = read_receipt(path)
    except ExtractionError as e:
        raise HTTPException(422, str(e))
    return {"reading": reading, "document": f"/api/receiving/page/{sample_id}",
            "kind": "pdf" if path.suffix.lower() == ".pdf" else "image"}


@router.get("/page/{sample_id}")
def page(sample_id: str) -> Response:
    """Page 1 as an image, so a value's word box can be drawn on top of it."""
    path = _sample_path(sample_id)
    if path.suffix.lower() in IMAGE_SUFFIXES:
        return FileResponse(path)
    with pymupdf.open(path) as doc:
        return Response(doc[0].get_pixmap(dpi=110).tobytes("png"), media_type="image/png")


@router.post("/extract")
async def extract_upload(file: UploadFile = File(...), live: bool = Form(False)) -> dict:
    """Read an uploaded PDF (text layer) or image (cached reading by file stem, or live)."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in IMAGE_SUFFIXES | {".pdf"}:
        raise HTTPException(422, f"'{file.filename}' is not a PDF or image (pdf, png, jpg).")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(file.filename).name
        path.write_bytes(await file.read())
        try:
            return {"reading": read_receipt(path, live=live)}
        except ExtractionError as e:
            raise HTTPException(422, str(e))


@router.post("/validate")
def validate_it(req: ReceiptRequest) -> dict:
    report, posted, ref = _check(req.receipt, with_ref=True)
    if req.name and not posted:
        store.record_check(req.name, report)
    return report.to_dict() | {"posted": posted, "evidence": receipt_evidence(req.receipt, report, ref)}


@router.post("/post")
def post_it(req: ReceiptRequest) -> dict:
    """Post to the MOCK purchase-order history. Re-validates first; never trusts the client."""
    report, posted = _check(req.receipt)
    if posted:
        raise HTTPException(409, f"Receipt {posted['receipt_number']} was already posted as entry #{posted['id']}.")
    name = req.name or report.receipt_number or "receipt"
    store.record_check(name, report)
    try:
        return store.post(name, report, req.answers)
    except (store.NotPostable, store.AlreadyReceived) as e:
        raise HTTPException(409, str(e))


@router.get("/summary")
def summary() -> dict:
    return store.summary(store.current_reference())
