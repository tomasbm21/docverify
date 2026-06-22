# Canonical Pydantic models for the docverify engine.
# Source of truth: MVP_BUILD_PROMPT.md §2 + CONTRACTS.md §4
# All extractors MUST emit CanonicalDoc. All downstream modules consume it.
# Field names are contractual — do not rename without a CONTRACT_CHANGE_REQUESTS.md entry.

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class DocType(str, Enum):
    bill_of_lading = "bill_of_lading"
    packing_list = "packing_list"
    commercial_invoice = "commercial_invoice"
    proforma_invoice = "proforma_invoice"
    confirmation = "confirmation"
    unknown = "unknown"


class SourceFormat(str, Enum):
    docx = "docx"
    xlsx = "xlsx"
    pdf = "pdf"


class Identifiers(BaseModel):
    order_no: Optional[str] = None
    bl_no: Optional[str] = None
    reference: Optional[str] = None
    container_no: Optional[str] = None
    seal_no: Optional[str] = None


class Parties(BaseModel):
    shipper: Optional[str] = None
    consignee: Optional[str] = None


class Logistics(BaseModel):
    vessel: Optional[str] = None
    voyage: Optional[str] = None
    pol: Optional[str] = None       # port of loading
    pod: Optional[str] = None       # port of discharge
    ship_date: Optional[str] = None


class LineItem(BaseModel):
    description: Optional[str] = None
    lot: Optional[str] = None
    cartons: Optional[int] = None
    net_kg: Optional[float] = None
    gross_kg: Optional[float] = None
    unit_price: Optional[float] = None
    units: Optional[int] = None
    amount: Optional[float] = None


class Totals(BaseModel):
    cartons: Optional[int] = None
    net_kg: Optional[float] = None
    gross_kg: Optional[float] = None
    value: Optional[float] = None
    currency: Optional[str] = None     # "EUR" | "USD"


class CanonicalDoc(BaseModel):
    """The universal document record. Every extractor emits this."""
    doc_id: str                        # sha256 of normalized content, NOT filename
    source_path: str                   # original path, for human reports only
    doc_type: DocType
    source_format: SourceFormat
    identifiers: Identifiers = Field(default_factory=Identifiers)
    parties: Parties = Field(default_factory=Parties)
    logistics: Logistics = Field(default_factory=Logistics)
    line_items: list[LineItem] = Field(default_factory=list)
    totals: Totals = Field(default_factory=Totals)
    extraction_confidence: float = 0.0
    raw_field_labels: dict[str, str] = Field(default_factory=dict)  # canonical -> original label


# --- Stage I/O models ---

class RawDoc(BaseModel):
    """Output of Ingestion (Agent A). Input to Extraction (Agent B)."""
    doc_id: str                        # sha256 of normalized text
    source_path: str
    source_format: SourceFormat
    text: str                          # normalized plain-text dump
    tables: list[list[list[str]]]      # list of tables; each table = rows of cells


class ShipmentGroup(BaseModel):
    """Output of Matching (Agent C). Input to Verification (Agent D)."""
    group_id: str                      # stable id, e.g. "G01"
    doc_ids: list[str]
    grouping_key: dict[str, str]       # the consensus identifiers used to group
    match_certainty: dict[str, float]  # doc_id -> certainty this doc belongs here


class Severity(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Finding(BaseModel):
    """A single cross-document discrepancy (Agent D)."""
    group_id: str
    field: str                         # e.g. "identifiers.order_no", "totals.net_kg"
    doc_a: str                         # doc_id (consensus representative)
    value_a: Optional[str] = None
    doc_b: str                         # doc_id (deviating document)
    value_b: Optional[str] = None
    severity: Severity
    message: str


class ShipmentVerdict(BaseModel):
    """Per-shipment result (Agent D)."""
    group_id: str
    verdict: str                       # "PASS" | "FAIL"
    suspect_doc_ids: list[str] = Field(default_factory=list)  # majority-vote outliers
    findings: list[Finding] = Field(default_factory=list)
