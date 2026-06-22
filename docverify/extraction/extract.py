"""Field Extractor — maps raw text/tables to the canonical CanonicalDoc schema.

OWNER: Agent 02 (Extraction)
FROZEN signatures per CONTRACTS.md §5.

Deterministic extraction is the primary path (cheap, private, reproducible).
The Gemini LLM call is an OPTIONAL fallback for labels the dictionary can't resolve.
"""

import re

from docverify.schemas.models import (
    CanonicalDoc,
    DocType,
    Identifiers,
    LineItem,
    Logistics,
    Parties,
    RawDoc,
    SourceFormat,
    Totals,
)
from docverify.extraction.synonyms import canonical_field
from docverify.utils import get_logger, parse_int, parse_number

logger = get_logger(__name__)


# ── Document type classification ─────────────────────────────────────────────

# Keyword signals for doc_type, checked case-insensitively against text.
# Order matters: more specific / title-level patterns first.
# We normalize spaces for matching so "P A C K I N G   L I S T" works.
_DOC_TYPE_SIGNALS: list[tuple[re.Pattern, DocType]] = [
    (re.compile(r"\bpro\s*forma\b", re.IGNORECASE), DocType.proforma_invoice),
    (re.compile(r"\bshipment\s+confirmation\b", re.IGNORECASE), DocType.confirmation),
    (re.compile(r"\bcommercial\s+invoice\b", re.IGNORECASE), DocType.commercial_invoice),
    (re.compile(r"\bfattura\b", re.IGNORECASE), DocType.commercial_invoice),
    (re.compile(r"\bpacking\s+list\b", re.IGNORECASE), DocType.packing_list),
    (re.compile(r"\bbill\s+of\s+lading\b", re.IGNORECASE), DocType.bill_of_lading),
    # Arabic document type signals
    (re.compile(r"الفاتورة\s+الموحدة"), DocType.proforma_invoice),
    (re.compile(r"فاتورة\s+مبدئية"), DocType.proforma_invoice),
    (re.compile(r"تأكيد\s+الشحن"), DocType.confirmation),
    (re.compile(r"تأكيد\s+الإرسال"), DocType.confirmation),
    (re.compile(r"الفاتورة\s+التجارية"), DocType.commercial_invoice),
    (re.compile(r"قائمة\s+التعبئة"), DocType.packing_list),
    (re.compile(r"قائمة\s+التغليف"), DocType.packing_list),
    (re.compile(r"بوليصة\s+الشحن"), DocType.bill_of_lading),
    # French document type signals
    (re.compile(r"\bfacture\s+pro\s*forma\b", re.IGNORECASE), DocType.proforma_invoice),
    (re.compile(r"\bconfirmation\s+d['e]expédition\b", re.IGNORECASE), DocType.confirmation),
    (re.compile(r"\bconfirmation\s+d['e]envoi\b", re.IGNORECASE), DocType.confirmation),
    (re.compile(r"\bfacture\s+commerciale\b", re.IGNORECASE), DocType.commercial_invoice),
    (re.compile(r"\bliste\s+de\s+colisage\b", re.IGNORECASE), DocType.packing_list),
    (re.compile(r"\bliste\s+de\s+colis\b", re.IGNORECASE), DocType.packing_list),
    (re.compile(r"\bconnaissement\b", re.IGNORECASE), DocType.bill_of_lading),
    (re.compile(r"\bfacture\b", re.IGNORECASE), DocType.commercial_invoice),
]


def classify_doc_type(text: str) -> tuple[DocType, float]:
    """Classify document type from content (never filename).

    Returns (doc_type, confidence). Confidence is 0.9 for a strong match,
    0.6 for a weaker signal, 0.0 for unknown.
    """
    # Normalize spaced-out single-char titles like "P A C K I N G   L I S T"
    # by collapsing "X Y Z" (single uppercase letters separated by spaces)
    # into "XYZ", then normalizing remaining whitespace.
    normalized = re.sub(
        r"\b(?:[A-Z] )+[A-Z]\b",
        lambda m: m.group(0).replace(" ", ""),
        text,
    )
    normalized = re.sub(r"\s{2,}", " ", normalized)

    # Check title/header lines (first ~500 chars) more heavily
    header = normalized[:500]

    for pattern, dtype in _DOC_TYPE_SIGNALS:
        if pattern.search(header):
            return dtype, 0.9

    # Check full text as fallback
    for pattern, dtype in _DOC_TYPE_SIGNALS:
        if pattern.search(normalized):
            return dtype, 0.6

    return DocType.unknown, 0.0


# ── Key-value metadata extraction ────────────────────────────────────────────

# Pattern for finding label: value pairs in free-text lines (legacy format).
# Non-greedy label capture, value terminated by the next label boundary or EOL.
# The value boundary lookahead detects the next "label:" pattern (2+ spaces + word + colon).
_KV_FINDER = re.compile(
    r"([A-Za-z][A-Za-z\s.()/&']{1,40}?)\s*:\s*(.+?)(?=\s{2,}[A-Za-z][A-Za-z\s.()/&']{0,30}?\s*:|$)"
)


def _extract_kv_from_text(text: str) -> dict[str, str]:
    """Extract key-value pairs from free-text lines (legacy format).

    Handles lines with multiple KV pairs separated by whitespace, e.g.:
    'N. Ordine     : ORD-2024-33562        REF      : REF/HK/5919-H'

    Returns {canonical_field: raw_value} for recognized labels.
    """
    result: dict[str, str] = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for m in _KV_FINDER.finditer(line):
            raw_label = m.group(1).strip()
            value = m.group(2).strip()
            canon = canonical_field(raw_label)
            if canon and value:
                result[canon] = value
    return result


def _extract_kv_from_tables(tables: list[list[list[str]]]) -> dict[str, str]:
    """Extract key-value pairs from metadata tables.

    Handles both strict two-column tables (docx) and wider tables with
    spacer columns (xlsx: label, value, spacer, label, value, ...).
    Returns {canonical_field: raw_value}.
    """
    result: dict[str, str] = {}
    for table in tables:
        # Skip tables that look like line-item tables (header row with
        # 3+ recognized fields — these are data tables, not metadata).
        if table:
            first_row = table[0]
            recognized = sum(
                1 for cell in first_row
                if (cell or "").strip() and canonical_field((cell or "").strip())
            )
            if recognized >= 3:
                continue

        for row in table:
            # Check label-value pairs at column positions (0,1) and (3,4).
            # This handles both strict 2-col tables and wide tables with spacers.
            for col_start in (0, 3):
                if col_start + 1 >= len(row):
                    break
                label = (row[col_start] or "").strip()
                value = (row[col_start + 1] or "").strip()
                if label and value:
                    canon = canonical_field(label)
                    if canon and canon not in result:
                        result[canon] = value
    return result


def _extract_confirmation_fields(text: str) -> dict[str, str]:
    """Extract fields from free-text confirmation documents.

    These documents embed identifiers in running prose, e.g.:
    '...order ORD-2024-33562 (reference REF/HK/5919-H) from X to Y,
     under bill of lading BL185831, container WSHZ2980815...'
    """
    result = {}

    # Order number
    m = re.search(r"\border\s+(ORD[\w\-/]+)", text, re.IGNORECASE)
    if m:
        result["order_no"] = m.group(1)

    # Reference
    m = re.search(r"\breference\s+([\w\-/]+)", text, re.IGNORECASE)
    if m:
        result["reference"] = m.group(1)

    # B/L number
    m = re.search(r"\bbill\s+of\s+lading\s+(\w+)", text, re.IGNORECASE)
    if m:
        result["bl_no"] = m.group(1)
    elif re.search(r"\bbl\s*no\.?\s*:?\s*(\w+)", text, re.IGNORECASE):
        result["bl_no"] = re.search(
            r"\bbl\s*no\.?\s*:?\s*(\w+)", text, re.IGNORECASE
        ).group(1)

    # Container
    m = re.search(r"\bcontainer\s+(\w+)", text, re.IGNORECASE)
    if m:
        result["container_no"] = m.group(1)

    # Shipper/consignee: "from X to Y"
    m = re.search(r"\bfrom\s+(.+?)\s+to\s+(.+?)[,\.\n]", text, re.IGNORECASE)
    if m:
        result["shipper"] = m.group(1).strip()
        result["consignee"] = m.group(2).strip()

    # Vessel
    m = re.search(r"\bvessel\s+(\w[\w\s]*?\d+\w*)", text, re.IGNORECASE)
    if m:
        vessel_raw = m.group(1).strip()
        # Strip 'voyage' keyword if captured as part of the vessel name
        # (e.g., "JOHNSON STAR voyage 875E" -> "JOHNSON STAR 875E")
        vessel_raw = re.sub(r"\s+voyage\b", "", vessel_raw, flags=re.IGNORECASE).strip()
        result["vessel"] = vessel_raw

    return result


# ── Totals extraction from paragraph text ────────────────────────────────────

_TOTALS_PATTERNS = {
    "net_kg": [
        re.compile(r"total\s+net\s+weight[:\s]*([\d,\.]+)\s*kg", re.IGNORECASE),
        re.compile(r"net\s*(?:wt|weight)[:\s]*([\d,\.]+)\s*kg", re.IGNORECASE),
        re.compile(r"الوزن\s+الصافي[:\s]*([\d,\.]+)"),
    ],
    "gross_kg": [
        re.compile(r"(?:total\s+)?gross\s+weight[:\s]*([\d,\.]+)\s*kg", re.IGNORECASE),
        re.compile(r"gross[:\s]*([\d,\.]+)\s*kg", re.IGNORECASE),
        re.compile(r"الوزن\s+(?:الإجمالي|الخام)[:\s]*([\d,\.]+)"),
    ],
    "cartons": [
        re.compile(r"total\s+cartons[:\s]*([\d,\.]+)", re.IGNORECASE),
        re.compile(r"cartons[:\s]*([\d,\.]+)", re.IGNORECASE),
        re.compile(r"(?:الصناديق|كراتين)[:\s]*([\d,\.]+)"),
    ],
    "value": [
        re.compile(r"total\s+value[:\s]*([\d,\.]+)", re.IGNORECASE),
        re.compile(r"invoice\s+value[:\s]*([\d,\.]+)", re.IGNORECASE),
        re.compile(r"(?:القيمة|قيمة\s+الفاتورة)[:\s]*([\d,\.]+)"),
    ],
}


def _extract_totals_from_text(text: str) -> dict[str, str]:
    """Extract totals values from paragraph text.

    Returns {canonical_field: raw_value_string}.
    """
    result = {}
    for field, patterns in _TOTALS_PATTERNS.items():
        for pat in patterns:
            m = pat.search(text)
            if m:
                result[field] = m.group(1)
                break
    return result


# ── Header detection for structured tables ───────────────────────────────────

def _detect_header_row(table: list[list[str]]) -> tuple[int, dict[int, str]]:
    """Find the header row and map column index -> canonical field name.

    Returns (header_row_index, {col_idx: canonical_field_name}).
    Returns (-1, {}) if no header row found.

    When multiple candidate rows have 2+ recognized columns, prefer the row
    whose recognized fields look like a line-item header (contains
    'description', 'cartons', 'net_kg', etc.) over metadata key-value rows.
    """
    _LINE_ITEM_FIELDS = {"description", "cartons", "net_kg", "gross_kg",
                         "unit_price", "units", "amount"}

    best_idx = -1
    best_map: dict[int, str] = {}
    best_score = -1

    for row_idx, row in enumerate(table):
        col_map: dict[int, str] = {}
        for col_idx, cell in enumerate(row):
            label = (cell or "").strip()
            if label:
                canon = canonical_field(label)
                if canon:
                    col_map[col_idx] = canon
        # A header row needs at least 2 recognized columns
        if len(col_map) >= 2:
            # Score: prefer rows with line-item-specific fields
            score = len(col_map)
            recognized_set = set(col_map.values())
            if "description" in recognized_set:
                score += 100
            if recognized_set & _LINE_ITEM_FIELDS:
                score += 50
            if score > best_score:
                best_score = score
                best_idx = row_idx
                best_map = col_map

    return best_idx, best_map


# ── Line-item parsing from structured tables ─────────────────────────────────

def _parse_line_items_from_tables(
    tables: list[list[list[str]]],
) -> tuple[list[LineItem], dict[str, str]]:
    """Parse line items from structured tables with detected headers.

    Returns (line_items, raw_field_labels).
    """
    line_items: list[LineItem] = []
    raw_labels: dict[str, str] = {}

    for table in tables:
        header_idx, col_map = _detect_header_row(table)
        if header_idx < 0:
            continue

        # Record raw labels for audit
        for col_idx, canon in col_map.items():
            raw_label = (table[header_idx][col_idx] or "").strip()
            if canon not in raw_labels and raw_label:
                raw_labels[canon] = raw_label

        # Parse data rows (everything after header)
        for row in table[header_idx + 1 :]:
            item_data: dict[str, object] = {}
            for col_idx, canon in col_map.items():
                if col_idx < len(row):
                    cell = (row[col_idx] or "").strip()
                    if cell:
                        item_data[canon] = cell

            # Skip empty rows and total/summary rows
            desc = str(item_data.get("description", "")).strip()
            if not desc:
                continue
            desc_lower = desc.lower()
            if (desc_lower in ("total", "totale", "")
                    or desc_lower.startswith("total")
                    or desc_lower.startswith("specimen")
                    or desc in ("المجموع", "الإجمالي", "اجمالي")):
                # This might be a totals row, watermark, or summary — skip it
                continue

            # Build LineItem
            li = LineItem()
            li.description = desc
            if "lot" in item_data:
                li.lot = str(item_data["lot"])
            if "cartons" in item_data:
                li.cartons = parse_int(str(item_data["cartons"]))
            if "net_kg" in item_data:
                li.net_kg = parse_number(str(item_data["net_kg"]))
            if "gross_kg" in item_data:
                li.gross_kg = parse_number(str(item_data["gross_kg"]))
            if "unit_price" in item_data:
                li.unit_price = parse_number(str(item_data["unit_price"]))
            if "units" in item_data:
                li.units = parse_int(str(item_data["units"]))
            if "amount" in item_data:
                li.amount = parse_number(str(item_data["amount"]))

            # Fallback: compute amount from unit_price * cartons when the
            # Amount column is blank or contains an uncached formula (common
            # in xlsx invoices opened with data_only=True).
            if li.amount is None and li.unit_price is not None and li.cartons is not None:
                li.amount = round(li.unit_price * li.cartons, 2)

            line_items.append(li)

    return line_items, raw_labels


def _parse_totals_from_tables(
    tables: list[list[list[str]]],
) -> tuple[Totals, dict[str, str]]:
    """Extract totals from the TOTAL/summary row in structured tables.

    Returns (totals, raw_field_labels).
    """
    totals = Totals()
    raw_labels: dict[str, str] = {}

    for table in tables:
        header_idx, col_map = _detect_header_row(table)
        if header_idx < 0:
            continue

        # Look for total row
        for row in table[header_idx + 1 :]:
            # Check if any cell says "total" or "totale"
            is_total_row = any(
                (cell or "").strip().lower() in ("total", "totale", "montant")
                or (cell or "").strip() in ("المجموع", "الإجمالي", "اجمالي")
                for cell in row
            )
            if not is_total_row:
                continue

            for col_idx, canon in col_map.items():
                if col_idx < len(row):
                    cell = (row[col_idx] or "").strip()
                    if not cell:
                        continue
                    if canon == "cartons" and totals.cartons is None:
                        totals.cartons = parse_int(cell)
                        raw_labels.setdefault("cartons", (table[header_idx][col_idx] or "").strip())
                    elif canon == "net_kg" and totals.net_kg is None:
                        totals.net_kg = parse_number(cell)
                        raw_labels.setdefault("net_kg", (table[header_idx][col_idx] or "").strip())
                    elif canon == "gross_kg" and totals.gross_kg is None:
                        totals.gross_kg = parse_number(cell)
                        raw_labels.setdefault("gross_kg", (table[header_idx][col_idx] or "").strip())
                    elif canon == "amount" and totals.value is None:
                        totals.value = parse_number(cell)
                        raw_labels.setdefault("value", (table[header_idx][col_idx] or "").strip())

    return totals, raw_labels


# ── Legacy fixed-width text parsing ──────────────────────────────────────────


def _detect_legacy_columns(header_line: str) -> tuple[list[str], dict[str, str]]:
    """Detect which columns are present in a legacy packing list header.

    Returns (ordered_list_of_canonical_names, {canonical: raw_label}).
    Uses keyword PRESENCE (not position) since headers may have columns
    running together without spaces (e.g. "No. of PkgsPeso Neto kg").
    """
    header_lower = header_line.lower()
    raw_labels: dict[str, str] = {}
    cols: list[str] = []

    # Always present
    if "lot" in header_lower or "لوط" in header_line or "الدفعة" in header_line or "numéro de lot" in header_lower or "n° de lot" in header_lower:
        cols.append("lot")
        raw_labels["lot"] = "LOT"
    if "description" in header_lower or "descrizione" in header_lower or "الوصف" in header_line or "désignation" in header_lower:
        cols.append("description")
        raw_labels["description"] = "Description"

    # Cartons
    cartons_kw = ["cartons", "colli", "no. of pkgs", "no. of packages", "ctns", "pkgs", "nombre de cartons", "nb de cartons", "colis"]
    cartons_ar = ["الصناديق", "كراتين", "عدد الصناديق", "طرود"]
    found_cartons = False
    for kw in cartons_kw:
        if kw in header_lower:
            cols.append("cartons")
            raw_labels["cartons"] = kw.upper()
            found_cartons = True
            break
    if not found_cartons:
        for kw in cartons_ar:
            if kw in header_line:
                cols.append("cartons")
                raw_labels["cartons"] = kw
                break

    # Net weight
    net_kw = ["peso neto kg", "peso netto kg", "n.w. (kgs)", "net wt",
              "net weight", "peso neto", "peso netto", "n.w.", "net",
              "poids net", "poids net kg", "p. net"]
    net_ar = ["الوزن الصافي", "وزن صافي"]
    found_net = False
    for kw in net_kw:
        if kw in header_lower:
            cols.append("net_kg")
            raw_labels["net_kg"] = kw.upper()
            found_net = True
            break
    if not found_net:
        for kw in net_ar:
            if kw in header_line:
                cols.append("net_kg")
                raw_labels["net_kg"] = kw
                break

    # Gross weight
    gross_kw = ["peso bruto kg", "peso lordo kg", "gross wt", "gross weight",
                "peso bruto", "peso lordo", "g.w.", "gross",
                "poids brut", "poids brut kg", "p. brut"]
    gross_ar = ["الوزن الإجمالي", "الوزن الخام", "وزن إجمالي"]
    found_gross = False
    for kw in gross_kw:
        if kw in header_lower:
            cols.append("gross_kg")
            raw_labels["gross_kg"] = kw.upper()
            found_gross = True
            break
    if not found_gross:
        for kw in gross_ar:
            if kw in header_line:
                cols.append("gross_kg")
                raw_labels["gross_kg"] = kw
                break

    return cols, raw_labels


def _find_data_boundaries(lines: list[str], header_idx: int) -> list[int]:
    """Find column start positions from a data line's space-gap structure.

    Uses 2+ space gaps as column separators (single spaces within fields
    like "Spaghetti No.5" are NOT treated as boundaries).

    Returns a list of character positions where each column starts.
    """
    for line in lines[header_idx + 1 :]:
        stripped = line.strip()
        if not stripped or re.match(r"^[\-=]+$", stripped):
            continue
        if not re.match(r"^[A-Z]\d{4}[A-Z]", stripped, re.IGNORECASE):
            continue

        # Find non-space segments preceded by 2+ spaces (or start of line)
        boundaries: list[int] = []
        i = 0
        while i < len(line):
            if line[i] != " ":
                # Check if preceded by 2+ spaces or at start of line
                if i == 0 or (i >= 2 and line[i - 1] == " " and line[i - 2] == " "):
                    boundaries.append(i)
                # Skip to end of this non-space segment
                while i < len(line) and line[i] != " ":
                    i += 1
            else:
                i += 1
        return boundaries

    return []


def _parse_legacy_packing_list(
    text: str,
) -> tuple[list[LineItem], dict[str, str]]:
    """Parse line items from legacy fixed-width packing list format.

    Uses data-line space-gap detection for column boundaries (more robust
    than header keyword position matching, which fails when columns run
    together without spaces).

    Returns (line_items, raw_field_labels).
    """
    lines = text.split("\n")

    # Find the header line
    header_idx = -1
    for i, line in enumerate(lines):
        lower = line.lower()
        if any(
            kw in lower
            for kw in [
                "description", "descrizione", "net", "gross", "peso",
                "cartons", "colli", "ctns", "packages", "pkgs",
            ]
        ) or any(
            kw in line
            for kw in ["الوصف", "الوزن", "الصناديق", "كراتين"]
        ):
            if re.match(r"^[\-=]+$", line.strip()):
                continue
            header_idx = i
            break

    if header_idx < 0:
        return [], {}

    # Detect which columns are present from the header keywords
    expected_cols, raw_labels = _detect_legacy_columns(lines[header_idx])

    if len(expected_cols) < 3:
        return [], {}

    # Find column boundaries from the first data line
    boundaries = _find_data_boundaries(lines, header_idx)

    if len(boundaries) < len(expected_cols):
        return [], {}

    # Parse data lines
    line_items: list[LineItem] = []
    for line in lines[header_idx + 1 :]:
        stripped = line.strip()
        if not stripped or re.match(r"^[\-=]+$", stripped):
            continue
        if stripped.lower().startswith("total"):
            continue
        if not re.match(r"^[A-Z]\d{4}[A-Z]", stripped, re.IGNORECASE):
            continue

        item = LineItem()

        for i, canon in enumerate(expected_cols):
            pos = boundaries[i]
            end = boundaries[i + 1] if i + 1 < len(boundaries) else len(line)
            cell = line[pos:end].strip() if pos < len(line) else ""

            if not cell:
                continue

            if canon == "lot":
                item.lot = cell
            elif canon == "description":
                item.description = cell
            elif canon == "cartons":
                item.cartons = parse_int(cell)
            elif canon == "net_kg":
                item.net_kg = parse_number(cell)
            elif canon == "gross_kg":
                item.gross_kg = parse_number(cell)

        line_items.append(item)

    return line_items, raw_labels


def _parse_legacy_totals(text: str) -> tuple[Totals, dict[str, str]]:
    """Extract totals from a legacy packing list TOTAL line.

    Uses the same data-line boundary detection as _parse_legacy_packing_list.
    Returns (totals, raw_field_labels).
    """
    totals = Totals()
    raw_labels: dict[str, str] = {}
    lines = text.split("\n")

    # Find header
    header_idx = -1
    for i, line in enumerate(lines):
        lower = line.lower()
        if any(
            kw in lower
            for kw in [
                "description", "descrizione", "net", "gross", "peso",
                "cartons", "colli", "ctns", "packages", "pkgs",
            ]
        ) or any(
            kw in line
            for kw in ["الوصف", "الوزن", "الصناديق", "كراتين"]
        ):
            if re.match(r"^[\-=]+$", line.strip()):
                continue
            header_idx = i
            break

    if header_idx < 0:
        return totals, raw_labels

    expected_cols, _ = _detect_legacy_columns(lines[header_idx])
    boundaries = _find_data_boundaries(lines, header_idx)

    if len(boundaries) < len(expected_cols):
        return totals, raw_labels

    # Find the TOTAL line
    for line in lines[header_idx + 1 :]:
        stripped = line.strip()
        if not stripped.lower().startswith("total"):
            continue

        for i, canon in enumerate(expected_cols):
            pos = boundaries[i]
            end = boundaries[i + 1] if i + 1 < len(boundaries) else len(line)
            cell = line[pos:end].strip() if pos < len(line) else ""
            if not cell or cell.lower() == "total":
                continue

            if canon == "cartons" and totals.cartons is None:
                totals.cartons = parse_int(cell)
                raw_labels.setdefault("cartons", "cartons")
            elif canon == "net_kg" and totals.net_kg is None:
                totals.net_kg = parse_number(cell)
                raw_labels.setdefault("net_kg", canon)
            elif canon == "gross_kg" and totals.gross_kg is None:
                totals.gross_kg = parse_number(cell)
                raw_labels.setdefault("gross_kg", canon)

        break  # Only process the first TOTAL line

    return totals, raw_labels


# ── Confirmation document extraction ─────────────────────────────────────────

def _extract_confirmation_line_items(text: str) -> tuple[list[LineItem], Totals]:
    """Extract line items and totals from confirmation free text.

    Confirmations often have a summary line like:
    'Total: 4967 cartons, net 47,634.83 kg, gross 50,829.00 kg.'
    """
    totals = Totals()

    m = re.search(
        r"total[:\s]*(\d[\d,]*)\s*cartons?,\s*net\s*([\d,\.]+)\s*kg,\s*gross\s*([\d,\.]+)\s*kg",
        text,
        re.IGNORECASE,
    )
    if m:
        totals.cartons = parse_int(m.group(1))
        totals.net_kg = parse_number(m.group(2))
        totals.gross_kg = parse_number(m.group(3))

    return [], totals


# ── Main extraction functions ────────────────────────────────────────────────

def _normalize_container_no(raw: str | None) -> str | None:
    """Strip container type/size suffix (e.g. \"40'HC\", \"20'GP\") from container number.

    B/L documents often embed the container type after the number:
    'WSHZ2980815  40\\'HC' -> 'WSHZ2980815'
    """
    if raw is None:
        return None
    # Strip suffix like "  40'HC", " 20'GP", " 45'R", etc.
    cleaned = re.sub(r"\s+\d{2}'[A-Z]{2}\s*$", "", raw)
    return cleaned.strip() or None


def _normalize_party_name(raw: str | None) -> str | None:
    """Extract just the company name from a party field that may include address.

    Takes the first line (before newline) and strips trailing punctuation.
    'Company Name\\nAddress...' -> 'Company Name'
    'Co.' -> 'Co'
    """
    if raw is None:
        return None
    name = raw.split("\n")[0].strip()
    # Strip trailing commas, periods, and whitespace
    name = re.sub(r"[,.\s]+$", "", name)
    return name or None


def extract_one(raw: RawDoc, use_llm: bool = False) -> CanonicalDoc:
    """Extract canonical fields from a single RawDoc record.

    Deterministic extraction is the primary path. If use_llm=True AND there
    are unresolved labels, the Gemini LLM fallback is called for ONLY those.
    Never raises on a bad doc — fills what it can, sets rest to None.
    """
    raw_field_labels: dict[str, str] = {}
    confidence_deductions = 0.0
    total_checks = 0

    # 1. Classify doc type
    doc_type, type_confidence = classify_doc_type(raw.text)

    # 2. Extract metadata from multiple sources
    # Priority: structured tables > free text > confirmation patterns
    kv_meta: dict[str, str] = {}

    # Structured table metadata (two-column key-value tables)
    table_kv = _extract_kv_from_tables(raw.tables)
    kv_meta.update(table_kv)

    # Free-text metadata (legacy format "KEY : VALUE" lines)
    text_kv = _extract_kv_from_text(raw.text)
    # Only add text-KV entries not already found in tables
    for k, v in text_kv.items():
        if k not in kv_meta:
            kv_meta[k] = v

    # Confirmation-style free text
    if doc_type == DocType.confirmation:
        conf_kv = _extract_confirmation_fields(raw.text)
        for k, v in conf_kv.items():
            if k not in kv_meta:
                kv_meta[k] = v

    # Record raw field labels
    for canon, value in kv_meta.items():
        raw_field_labels.setdefault(canon, value)

    # 3. Build identifiers (with container_no normalization)
    identifiers = Identifiers(
        order_no=kv_meta.get("order_no"),
        bl_no=kv_meta.get("bl_no"),
        reference=kv_meta.get("reference"),
        container_no=_normalize_container_no(kv_meta.get("container_no")),
        seal_no=kv_meta.get("seal_no"),
    )

    # 4. Build parties (with name-only normalization)
    parties = Parties(
        shipper=_normalize_party_name(kv_meta.get("shipper")),
        consignee=_normalize_party_name(kv_meta.get("consignee")),
    )

    # 5. Build logistics
    vessel_raw = kv_meta.get("vessel", "")
    # Vessel/Voyage may be combined: "JOHNSON STAR / 875E" or "JOHNSON STAR 875E"
    vessel_name = None
    voyage_num = None
    if vessel_raw:
        parts = re.split(r"\s*/\s*", vessel_raw, maxsplit=1)
        vessel_name = parts[0].strip() if parts[0].strip() else None
        if len(parts) > 1:
            voyage_num = parts[1].strip()
        else:
            # Try to split "VESSEL 875E" style
            m = re.match(r"^(.+?)\s+(\d+\w*)$", vessel_raw)
            if m:
                vessel_name = m.group(1).strip()
                voyage_num = m.group(2).strip()

    logistics = Logistics(
        vessel=vessel_name,
        voyage=voyage_num,
        pol=kv_meta.get("pol"),
        pod=kv_meta.get("pod"),
        ship_date=kv_meta.get("ship_date"),
    )

    # 6. Parse line items
    has_structured_tables = any(
        len(table) > 1 and any(len(row) >= 2 for row in table)
        for table in raw.tables
    )

    line_items: list[LineItem] = []
    li_labels: dict[str, str] = {}

    if has_structured_tables:
        line_items, li_labels = _parse_line_items_from_tables(raw.tables)

    # Fallback: legacy fixed-width if no line items found from tables
    if not line_items and not has_structured_tables:
        line_items, li_labels = _parse_legacy_packing_list(raw.text)

    raw_field_labels.update(li_labels)

    # 7. Parse totals
    totals = Totals()
    tot_labels: dict[str, str] = {}

    if has_structured_tables:
        totals, tot_labels = _parse_totals_from_tables(raw.tables)

    # Fallback: totals from paragraph text (invoices, proformas)
    if totals.net_kg is None and totals.gross_kg is None and totals.cartons is None:
        text_totals = _extract_totals_from_text(raw.text)
        for k, v in text_totals.items():
            if k == "net_kg" and totals.net_kg is None:
                totals.net_kg = parse_number(v)
                tot_labels.setdefault("net_kg", v)
            elif k == "gross_kg" and totals.gross_kg is None:
                totals.gross_kg = parse_number(v)
                tot_labels.setdefault("gross_kg", v)
            elif k == "cartons" and totals.cartons is None:
                totals.cartons = parse_int(v)
                tot_labels.setdefault("cartons", v)
            elif k == "value" and totals.value is None:
                totals.value = parse_number(v)
                tot_labels.setdefault("value", v)

    # Confirmation totals
    if doc_type == DocType.confirmation:
        _, conf_totals = _extract_confirmation_line_items(raw.text)
        if conf_totals.cartons and totals.cartons is None:
            totals.cartons = conf_totals.cartons
        if conf_totals.net_kg and totals.net_kg is None:
            totals.net_kg = conf_totals.net_kg
        if conf_totals.gross_kg and totals.gross_kg is None:
            totals.gross_kg = conf_totals.gross_kg

    # Fallback: legacy fixed-width totals from TOTAL line
    if totals.net_kg is None and totals.gross_kg is None and totals.cartons is None:
        legacy_totals, legacy_tot_labels = _parse_legacy_totals(raw.text)
        if legacy_totals.cartons is not None or legacy_totals.net_kg is not None or legacy_totals.gross_kg is not None:
            if totals.cartons is None:
                totals.cartons = legacy_totals.cartons
            if totals.net_kg is None:
                totals.net_kg = legacy_totals.net_kg
            if totals.gross_kg is None:
                totals.gross_kg = legacy_totals.gross_kg
            for k, v in legacy_tot_labels.items():
                tot_labels.setdefault(k, v)

    # Fallback: compute totals from line items when the TOTAL row was empty
    # or contained uncached formulas (common in xlsx with data_only=True).
    if line_items:
        if totals.cartons is None:
            val = sum(li.cartons for li in line_items if li.cartons is not None)
            if val > 0:
                totals.cartons = val
        if totals.net_kg is None:
            val = sum(li.net_kg for li in line_items if li.net_kg is not None)
            if val > 0:
                totals.net_kg = round(val, 2)
        if totals.gross_kg is None:
            val = sum(li.gross_kg for li in line_items if li.gross_kg is not None)
            if val > 0:
                totals.gross_kg = round(val, 2)
        if totals.value is None:
            val = sum(li.amount for li in line_items if li.amount is not None)
            if val > 0:
                totals.value = round(val, 2)

    raw_field_labels.update(tot_labels)

    # Currency: from metadata or inferred from table content
    totals.currency = kv_meta.get("currency")

    # 8. Compute extraction confidence
    # Base: type confidence
    # Boost for each key field resolved; deduct for missing critical fields
    confidence = type_confidence

    key_fields = [
        identifiers.order_no,
        identifiers.bl_no,
        identifiers.container_no,
        parties.shipper,
        parties.consignee,
    ]
    resolved_count = sum(1 for f in key_fields if f is not None)
    confidence += 0.05 * resolved_count

    if line_items:
        confidence += 0.1
    if totals.net_kg is not None or totals.gross_kg is not None:
        confidence += 0.05
    if totals.cartons is not None:
        confidence += 0.05

    # Cap at 1.0
    confidence = min(confidence, 1.0)

    # 9. Optional LLM fallback for unresolved labels
    if use_llm:
        # Build context snippet (first ~500 chars of text, no full doc)
        context = raw.text[:500]
        # Find labels in text that the synonym dict couldn't resolve
        unresolved: list[str] = []
        for line in raw.text.split("\n"):
            line = line.strip()
            m = _KV_FINDER.match(line)
            if m:
                label = m.group(1).strip()
                if canonical_field(label) is None and label not in unresolved:
                    unresolved.append(label)

        # Also check table headers
        for table in raw.tables:
            for row in table[:1]:  # header rows
                for cell in row:
                    label = (cell or "").strip()
                    if label and canonical_field(label) is None and label not in unresolved:
                        unresolved.append(label)

        if unresolved:
            from docverify.extraction.llm_fallback import resolve

            llm_map = resolve(unresolved, context)
            # Merge LLM results — this is informational; we don't override
            # existing deterministic results.
            logger.debug("LLM resolved %d/%d labels", len(llm_map), len(unresolved))

    # 10. Build and return CanonicalDoc
    return CanonicalDoc(
        doc_id=raw.doc_id,
        source_path=raw.source_path,
        doc_type=doc_type,
        source_format=raw.source_format,
        identifiers=identifiers,
        parties=parties,
        logistics=logistics,
        line_items=line_items,
        totals=totals,
        extraction_confidence=round(confidence, 2),
        raw_field_labels=raw_field_labels,
    )


def extract(raw_docs: list[RawDoc], use_llm: bool = False) -> list[CanonicalDoc]:
    """Extract canonical fields from a list of RawDoc records."""
    return [extract_one(raw, use_llm=use_llm) for raw in raw_docs]


# ── CLI entrypoint ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Extract canonical fields from raw documents"
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        default=False,
        help="Enable Gemini LLM fallback for unresolved labels",
    )
    parser.add_argument(
        "--input",
        type=str,
        default="data/out/raw_docs.json",
        help="Path to raw_docs.json (default: data/out/raw_docs.json)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/out/canonical_docs.json",
        help="Path to write canonical_docs.json (default: data/out/canonical_docs.json)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Error: {input_path} not found. Run ingestion first.")
        exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    raw_docs = [RawDoc(**item) for item in raw_data]
    print(f"Loaded {len(raw_docs)} raw documents from {input_path}")

    canonical_docs = extract(raw_docs, use_llm=args.use_llm)

    # Validate every output against CanonicalDoc before writing
    validated = []
    for doc in canonical_docs:
        validated.append(doc.model_dump(mode="json"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(validated, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(validated)} canonical documents to {output_path}")
    print(f"LLM fallback: {'enabled' if args.use_llm else 'disabled'}")
