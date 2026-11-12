"""Small helpers for sentences the product says to people."""

from __future__ import annotations


def count_of(number: int, one: str, many: str | None = None) -> str:
    """``3 items``, ``1 item`` — a count and its noun, agreeing.

    "3 item(s)" hands the reader a sum to finish.  Everything a shopkeeper
    reads here was written for them, and a sentence that has not decided
    whether it is talking about one thing or several was not.
    """
    return f"{number} {one if number == 1 else (many or one + 's')}"


def need(number: int) -> str:
    """The verb to go with a count: one product *needs*, two *need*."""
    return "needs" if number == 1 else "need"
