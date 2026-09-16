"""Generate short natural-language spending insights from expense records via the Anthropic API."""

from __future__ import annotations

import logging
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 200
_FALLBACK_INSIGHT = "Insights are unavailable right now. Please try again later."


def _summarize_expenses(expenses: list[dict]) -> str:
    """Build a compact text summary of expenses (amount, category, status) for the prompt."""
    lines = [
        f"- {expense.get('amount_base_minor')} paise, {expense.get('category')}, {expense.get('status')}"
        for expense in expenses
    ]
    return "\n".join(lines)


def generate_insight(expenses: list[dict]) -> str:
    """Ask Claude for three short bullet insights about a list of expenses.

    Args:
        expenses: Expense records, each expected to have amount_base_minor,
            category, and status keys.

    Returns:
        A string containing three short bullet insights, or a safe fallback
        string if the API call fails.
    """
    summary = _summarize_expenses(expenses)
    prompt = (
        "Here is a summary of expenses (amount in minor units of INR, category, status):\n"
        f"{summary}\n\n"
        "Give exactly three short bullet insights about this spending."
    )

    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return next(
            (block.text for block in response.content if block.type == "text"),
            _FALLBACK_INSIGHT,
        )
    except anthropic.APIError as exc:
        logger.error("Anthropic API error while generating insight: %s", exc)
        return _FALLBACK_INSIGHT
