"""Shared utility functions for the docverify engine.

Every module imports from here — do NOT duplicate these helpers.
See CONTRACTS.md §6 and INTEGRATION.md for conventions.
"""

import hashlib
import logging
import re


def content_hash(text: str, source_path: str = "") -> str:
    """SHA-256 hash of normalized (lowercased, whitespace-collapsed) text.

    Used to generate stable doc_id values.  Includes source_path so that
    distinct empty files produce distinct hashes (avoids doc_id collision
    when text is empty).
    """
    normalized = " ".join(text.lower().split())
    key = normalized + "\x00" + source_path
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def normalize_identifier(value: str | None) -> str | None:
    """Uppercase, strip spaces and separator characters (- / .).

    Used for matching and verification comparisons.
    e.g. 'ord-2026-77566' -> 'ORD202677566'
    Returns None if input is None or empty after stripping.
    """
    if value is None:
        return None
    cleaned = re.sub(r"[\s\-/\.]", "", value).upper()
    return cleaned if cleaned else None


def parse_number(raw: str | None) -> float | None:
    """Parse a numeric string that may contain thousands separators, currency
    symbols, or EU-format decimal commas.

    Handles: "6,402.00", "€6,402.00", "6.402,00" (EU), "4 967", "USD 12,345",
    "1.234.567,89" (EU thousands), plain "42", "3.14".

    Returns None on failure (never raises).
    """
    if raw is None:
        return None

    s = str(raw).strip()
    if not s:
        return None

    # Normalize Arabic-Indic digits (٠١٢٣٤٥٦٧٨٩) to Western digits (0-9)
    _ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    s = s.translate(_ARABIC_DIGITS)

    # Remove currency symbols and common prefixes
    s = re.sub(r"[€$£¥]", "", s)
    s = re.sub(r"^[A-Z]{3}\s*", "", s, flags=re.IGNORECASE)
    s = s.strip()

    # Strip trailing unit suffixes (e.g., "1119 CTNS" -> "1119", "50829.00 KG" -> "50829.00")
    s = re.sub(r"\s+[A-Za-z/]+$", "", s).strip()

    if not s:
        return None

    # Detect EU format: if it has dots followed by a comma at the end, or
    # if there are multiple dots and a trailing comma, treat as EU.
    # EU: 1.234.567,89 or 6.402,00
    # US: 1,234,567.89 or 6,402.00
    # Also handle space-separated thousands: 4 967

    # Remove spaces used as thousand separators
    s = s.replace(" ", "")

    # Try to detect format
    # If it ends with comma-digit(s), it's EU format
    eu_match = re.match(r"^[\d.]+,\d{1,2}$", s)
    eu_thousands_only = re.match(r"^\d{1,3}(\.\d{3})+$", s)
    if eu_match:
        # EU format: dots are thousands, comma is decimal
        s = s.replace(".", "").replace(",", ".")
    elif eu_thousands_only:
        # EU format with dots as thousands separators only (e.g. "1.234", "1.234.567")
        s = s.replace(".", "")
    else:
        # Check if it has commas as thousands separators (US format)
        # Pattern: digits,commas,digits but no period, OR standard US with period
        # Remove commas that are thousands separators
        # A comma is a thousands separator if followed by exactly 3 digits
        # repeatedly until end or a decimal point
        if re.match(r"^\d{1,3}(,\d{3})+(\.\d+)?$", s):
            # US format with thousands separators
            s = s.replace(",", "")
        elif re.match(r"^\d{1,3}(,\d{3})+$", s):
            # US format, integer with thousands
            s = s.replace(",", "")
        elif re.match(r"^\d+,\d{3}$", s):
            # Could be ambiguous — treat as US thousands (no decimal)
            s = s.replace(",", "")
        else:
            # Try removing commas as a fallback (handles simple cases)
            # Only if there's at most one comma or it looks like thousands
            parts = s.split(",")
            if len(parts) == 2:
                # Could be decimal (e.g. "6,42") or thousands (e.g. "6,402")
                if len(parts[1]) == 3 and "." not in s:
                    # Thousands separator: 6,402
                    s = s.replace(",", "")
                elif len(parts[1]) <= 2:
                    # Decimal comma: 6,42
                    s = s.replace(",", ".")
                else:
                    # Ambiguous — try removing comma
                    s = s.replace(",", "")
            elif len(parts) > 2:
                # Multiple commas = thousands separators
                s = s.replace(",", "")

    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_int(raw: str | int | float | None) -> int | None:
    """Parse an integer from a string that may contain separators.

    Delegates to parse_number then truncates to int.
    Returns None on failure.
    """
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    val = parse_number(raw)
    if val is None:
        return None
    return int(val)


def get_logger(name: str) -> logging.Logger:
    """Return a WARNING-level logger that never logs full document text.

    Convention: use module name as logger name, e.g. get_logger(__name__).
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.WARNING)
        formatter = logging.Formatter("%(name)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    return logger
