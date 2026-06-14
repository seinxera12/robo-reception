# app/tools/info.py
import json
import logging
from difflib import get_close_matches
from pathlib import Path
from pydantic_ai import RunContext

from app.agent.core import agent
from app.agent.models import RoboDeps, InfoResult

logger = logging.getLogger(__name__)

# Path resolves relative to this file: app/tools/info.py → ../../data/faq.json
_FAQ_PATH = Path(__file__).parent.parent.parent / "data" / "faq.json"
_faq: dict = {}


def _load_faq() -> dict:
    """Load FAQ JSON once, then return cached dict on subsequent calls."""
    global _faq
    if not _faq:
        with open(_FAQ_PATH, "r", encoding="utf-8") as f:
            _faq = json.load(f)
        logger.info(f"FAQ loaded: {list(_faq.keys())}")
    return _faq


@agent.tool
async def get_info(
    ctx: RunContext[RoboDeps],
    query_type: str,
) -> InfoResult:
    """
    Answer building FAQ questions. No database call — instant response.
    Supported topics: hours, parking, wifi, accessibility, cafeteria, security.
    Use this tool whenever a visitor asks about building facilities, rules, or services.
    """
    logger.info(f"Tool: get_info(query_type={query_type!r})")
    faq = _load_faq()

    # Exact match first (case-insensitive)
    key = query_type.lower().strip()
    if key in faq:
        return InfoResult(found=True, query_type=key, answer=faq[key])

    # Fuzzy match via difflib
    matches = get_close_matches(key, faq.keys(), n=1, cutoff=0.5)
    if matches:
        matched_key = matches[0]
        logger.info(f"FAQ fuzzy match: '{query_type}' → '{matched_key}'")
        return InfoResult(found=True, query_type=matched_key, answer=faq[matched_key])

    logger.info(f"FAQ miss: '{query_type}'")
    return InfoResult(
        found=False,
        query_type=query_type,
        answer="I don't have information about that. Please ask the front desk staff for assistance.",
    )
