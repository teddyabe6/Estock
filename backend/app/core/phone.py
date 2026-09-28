"""Phone numbers in the one form the rest of the system compares (PRD 16)."""

from __future__ import annotations

import re

#: Ethiopian numbers, local (09..., 07...) or international (+251...).
ET_PHONE_RE = re.compile(r"^(?:\+251|251|0)?(9|7)\d{8}$")


def normalise_et_phone(value: str | None) -> str | None:
    """Store Ethiopian numbers in one canonical ``+251...`` form.

    Two customers who type ``0911 22 33 44`` and ``+251911223344`` are the same
    person, and matching a storefront request to a customer record depends on
    that.  Non-Ethiopian numbers are kept as entered rather than rejected.
    """
    if not value:
        return None
    cleaned = re.sub(r"[\s\-()]", "", value.strip())
    if not ET_PHONE_RE.match(cleaned):
        return cleaned or None
    digits = cleaned.lstrip("+")
    if digits.startswith("251"):
        digits = digits[3:]
    digits = digits.lstrip("0")
    return f"+251{digits}"
