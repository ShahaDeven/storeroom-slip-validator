"""Storeroom slip validator: catch checkout-slip errors at entry time, not at count time."""

from pathlib import Path

try:  # optional: lets ANTHROPIC_API_KEY live in the project's .env (git-ignored)
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from slipcheck.reference import Reference, load_reference  # noqa: E402
from slipcheck.validate import InvalidSlip, Report, validate  # noqa: E402

__all__ = ["InvalidSlip", "Reference", "Report", "load_reference", "validate"]
