"""Unit tests for the extraction module — deterministic synonym extractor.

OWNER: Agent 02 (Extraction)
Runs fully offline — no LLM calls, no network.
"""

import pytest

from docverify.extraction.synonyms import canonical_field, _normalize_label
from docverify.extraction.extract import (
    classify_doc_type,
    extract_one,
    extract,
    _extract_kv_from_text,
    _extract_kv_from_tables,
    _detect_header_row,
    _parse_line_items_from_tables,
    _parse_legacy_packing_list,
)
from docverify.schemas.models import (
    CanonicalDoc,
    DocType,
    RawDoc,
    SourceFormat,
)


# ── Synonym dictionary tests ─────────────────────────────────────────────────


class TestCanonicalField:
    """Verify the synonym dict resolves all multilingual label variants."""

    # net_kg variants
    @pytest.mark.parametrize(
        "label",
        [
            "Net Weight (kg)",
            "Peso Netto (kg)",
            "N.W. (KGS)",
            "Peso Neto kg",
            "Net Wt",
            "Net Weight",
            "Peso Netto",
            "N.W.",
            "Net Kg",
            "peso netto kg",
        ],
    )
    def test_net_kg_variants(self, label: str):
        assert canonical_field(label) == "net_kg"

    # gross_kg variants
    @pytest.mark.parametrize(
        "label",
        [
            "Gross Weight (kg)",
            "Peso Lordo (kg)",
            "G.W. (KGS)",
            "Peso Bruto kg",
            "Gross Wt",
            "Gross Weight",
            "Peso Lordo",
            "Gross Kg",
            "peso lordo kg",
        ],
    )
    def test_gross_kg_variants(self, label: str):
        assert canonical_field(label) == "gross_kg"

    # cartons variants
    @pytest.mark.parametrize(
        "label",
        [
            "Cartons",
            "Colli",
            "Cartons/Cases",
            "No. of Cartons",
            "Cajas",
            "CTNS",
            "No. of Packages",
            "No. of Pkgs",
            "N. Colli",
        ],
    )
    def test_cartons_variants(self, label: str):
        assert canonical_field(label) == "cartons"

    # order_no variants
    @pytest.mark.parametrize(
        "label",
        [
            "Order No",
            "Order No.",
            "Order Number",
            "Ordine",
            "N. Ordine",
            "PO",
            "P/O No",
            "Order Ref",
            "Order Reference",
        ],
    )
    def test_order_no_variants(self, label: str):
        assert canonical_field(label) == "order_no"

    # bl_no variants
    @pytest.mark.parametrize(
        "label",
        [
            "B/L No",
            "B/L No.",
            "Bill of Lading No",
            "Bill of Lading No.",
            "BL Number",
            "BL No",
            "Polizza di carico",
        ],
    )
    def test_bl_no_variants(self, label: str):
        assert canonical_field(label) == "bl_no"

    # reference variants
    @pytest.mark.parametrize(
        "label",
        [
            "Reference",
            "Ref",
            "Riferimento",
            "Our Ref",
            "Referencia",
        ],
    )
    def test_reference_variants(self, label: str):
        assert canonical_field(label) == "reference"

    # container_no variants
    @pytest.mark.parametrize(
        "label",
        [
            "Container No",
            "Container",
            "Container/Seal",
            "Contenitore",
            "Container / Type",
        ],
    )
    def test_container_no_variants(self, label: str):
        assert canonical_field(label) == "container_no"

    # seal_no variants
    @pytest.mark.parametrize(
        "label",
        [
            "Seal No",
            "Seal No.",
            "Seal",
            "Sigillo",
            "Precinto",
        ],
    )
    def test_seal_no_variants(self, label: str):
        assert canonical_field(label) == "seal_no"

    # shipper / consignee
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Shipper", "shipper"),
            ("Mittente", "shipper"),
            ("Exporter", "shipper"),
            ("From", "shipper"),
            ("Consignee", "consignee"),
            ("Destinatario", "consignee"),
            ("Importer", "consignee"),
            ("To", "consignee"),
        ],
    )
    def test_party_variants(self, label: str, expected: str):
        assert canonical_field(label) == expected

    # Financial fields
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Unit Price", "unit_price"),
            ("Prezzo Unitario", "unit_price"),
            ("Units", "units"),
            ("Amount", "amount"),
            ("Importo", "amount"),
            ("Currency", "currency"),
            ("Valuta", "currency"),
        ],
    )
    def test_financial_variants(self, label: str, expected: str):
        assert canonical_field(label) == expected

    # Logistics fields
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Vessel", "vessel"),
            ("Vessel / Voyage", "vessel"),
            ("Port of Loading", "pol"),
            ("Port of Discharge", "pod"),
            ("Date", "ship_date"),
        ],
    )
    def test_logistics_variants(self, label: str, expected: str):
        assert canonical_field(label) == expected

    # Unrecognized labels return None
    def test_unrecognized_returns_none(self):
        assert canonical_field("XYZZY_NOT_A_FIELD") is None
        assert canonical_field("") is None

    # Case insensitivity
    def test_case_insensitive(self):
        assert canonical_field("NET WEIGHT (KG)") == "net_kg"
        assert canonical_field("net weight (kg)") == "net_kg"
        assert canonical_field("Net Weight (Kg)") == "net_kg"

    # Trailing colon handling
    def test_trailing_colon(self):
        assert canonical_field("Shipper:") == "shipper"
        assert canonical_field("Consignee:") == "consignee"


class TestNormalizeLabel:
    def test_basic(self):
        assert _normalize_label("  Net Weight (kg)  ") == "net weight (kg)"

    def test_collapse_whitespace(self):
        assert _normalize_label("Net   Weight  (kg)") == "net weight (kg)"

    def test_trailing_colon(self):
        assert _normalize_label("Shipper:") == "shipper"

    def test_trailing_colon_space(self):
        assert _normalize_label("Shipper :  ") == "shipper"


# ── Document type classification tests ───────────────────────────────────────


class TestClassifyDocType:
    def test_bill_of_lading(self):
        text = "BILL OF LADING - Hapag-Lloyd\nB/L No. BL185831"
        dtype, conf = classify_doc_type(text)
        assert dtype == DocType.bill_of_lading
        assert conf >= 0.8

    def test_commercial_invoice(self):
        text = "Mediterraneo Foods Export S.r.l.\nCOMMERCIAL INVOICE\nInvoice No. INV-33562"
        dtype, conf = classify_doc_type(text)
        assert dtype == DocType.commercial_invoice

    def test_packing_list(self):
        text = "PACKING LIST\nOrder Ref ORD-2026-31160"
        dtype, conf = classify_doc_type(text)
        assert dtype == DocType.packing_list

    def test_proforma_invoice(self):
        text = "PRO FORMA INVOICE\nTotal net weight: 47,634.83 kg"
        dtype, conf = classify_doc_type(text)
        assert dtype == DocType.proforma_invoice

    def test_confirmation(self):
        text = "SHIPMENT CONFIRMATION\nThis confirms shipment of order ORD-2024-33562"
        dtype, conf = classify_doc_type(text)
        assert dtype == DocType.confirmation

    def test_legacy_packing_list(self):
        text = "P A C K I N G   L I S T\nSHIPPER : Mediterraneo Foods"
        dtype, conf = classify_doc_type(text)
        assert dtype == DocType.packing_list

    def test_unknown(self):
        text = "Some random document with no recognizable type keywords"
        dtype, conf = classify_doc_type(text)
        assert dtype == DocType.unknown
        assert conf == 0.0

    def test_italian_invoice(self):
        text = "Fattura Commerciale\nN. Fattura INV-12345"
        dtype, conf = classify_doc_type(text)
        assert dtype == DocType.commercial_invoice


# ── Key-value extraction tests ───────────────────────────────────────────────


class TestExtractKvFromText:
    def test_legacy_format(self):
        text = (
            "N. Ordine     : ORD-2024-33562        REF      : REF/HK/5919-H\n"
            "B/L NO        : BL185831              CONTAINER: WSHZ2980815 40'HC\n"
            "VESSEL        : JOHNSON STAR 875E         SEAL     : SL677814\n"
            "POL           : Naples, Italy         POD      : Hong Kong"
        )
        result = _extract_kv_from_text(text)
        assert result["order_no"] == "ORD-2024-33562"
        assert result["bl_no"] == "BL185831"
        assert result["container_no"] == "WSHZ2980815 40'HC"
        assert result["seal_no"] == "SL677814"
        assert result["pol"] == "Naples, Italy"
        assert result["pod"] == "Hong Kong"

    def test_unrecognized_label_ignored(self):
        text = "RandomLabel: some value"
        result = _extract_kv_from_text(text)
        assert "RandomLabel" not in result


class TestExtractKvFromTables:
    def test_two_column_table(self):
        tables = [
            [
                ["B/L No.", "BL185831"],
                ["Shipper", "Mediterraneo Foods Export S.r.l."],
                ["Consignee", "Levant Food Supplies Co."],
                ["Seal No.", "SL677814"],
            ]
        ]
        result = _extract_kv_from_tables(tables)
        assert result["bl_no"] == "BL185831"
        assert result["shipper"] == "Mediterraneo Foods Export S.r.l."
        assert result["consignee"] == "Levant Food Supplies Co."
        assert result["seal_no"] == "SL677814"


class TestDetectHeaderRow:
    def test_detects_header(self):
        table = [
            ["Invoice No.", "INV-33562"],
            ["Order No.", "ORD-2024-33562"],
            ["Description", "Pack", "Units", "Unit Price", "Cartons", "Amount"],
            ["Spaghetti No.5", "500g x 24", "26,856", "1.50", "1119", "40,284.00"],
        ]
        idx, col_map = _detect_header_row(table)
        assert idx == 2  # The "Description, Pack, Units..." row
        assert 0 in col_map  # Description
        assert 4 in col_map  # Cartons


# ── extract_one integration test ─────────────────────────────────────────────


class TestExtractOne:
    def _make_raw_doc(
        self,
        text: str,
        tables: list[list[list[str]]],
        source_format: SourceFormat = SourceFormat.docx,
    ) -> RawDoc:
        """Build a synthetic RawDoc for testing."""
        from docverify.utils import content_hash

        return RawDoc(
            doc_id=content_hash(text),
            source_path="test_doc.docx",
            source_format=source_format,
            text=text,
            tables=tables,
        )

    def test_modern_invoice_extraction(self):
        """Test extraction from a modern-style commercial invoice."""
        text = "Mediterraneo Foods Export S.r.l.\nCOMMERCIAL INVOICE\nTotal net weight: 47,634.83 kg   |   Total gross weight: 50,829.00 kg\nTotal cartons: 4967"
        tables = [
            [
                ["Invoice No.", "INV-33562"],
                ["Invoice Date", "23 Apr 2026"],
                ["Order No.", "ORD-2024-33562"],
                ["Reference", "REF/HK/5919-H"],
                ["Buyer", "Levant Food Supplies Co."],
                ["Currency", "EUR"],
            ],
            [
                ["Description", "Pack", "Units", "Unit Price", "Cartons", "Amount"],
                ["Spaghetti No.5", "500g x 24", "26,856", "1.50", "1119", "40,284.00"],
                ["Penne Rigate", "500g x 24", "22,776", "2.32", "949", "52,840.32"],
                ["", "", "", "", "TOTAL", "191,161.76"],
            ],
        ]
        raw = self._make_raw_doc(text, tables)
        result = extract_one(raw)

        assert isinstance(result, CanonicalDoc)
        assert result.doc_type == DocType.commercial_invoice
        assert result.identifiers.order_no == "ORD-2024-33562"
        assert result.identifiers.reference == "REF/HK/5919-H"
        assert result.totals.currency == "EUR"
        assert result.totals.net_kg == pytest.approx(47634.83)
        assert result.totals.gross_kg == pytest.approx(50829.00)
        assert result.totals.cartons == 4967
        assert len(result.line_items) == 2
        assert result.line_items[0].description == "Spaghetti No.5"
        assert result.line_items[0].cartons == 1119
        assert result.line_items[1].description == "Penne Rigate"
        assert result.raw_field_labels.get("order_no") is not None
        assert result.extraction_confidence > 0.0

    def test_modern_bl_extraction(self):
        """Test extraction from a modern Bill of Lading."""
        text = "BILL OF LADING - Hapag-Lloyd\nDescription of Goods\nShipped on board: 27 April 2026"
        tables = [
            [
                ["B/L No.", "BL185831"],
                ["Shipper", "Mediterraneo Foods Export S.r.l."],
                ["Consignee", "Levant Food Supplies Co."],
                ["Vessel / Voyage", "JOHNSON STAR / 875E"],
                ["Port of Loading", "Naples, Italy"],
                ["Port of Discharge", "Hong Kong"],
                ["Container / Type", "WSHZ2980815  40'HC"],
                ["Seal No.", "SL677814"],
                ["Order Reference", "ORD-2024-33562"],
            ],
            [
                ["Marks & Nos", "No. of Packages", "Description", "Gross Weight (kg)"],
                ["L2461A", "1119 CTNS", "Spaghetti No.5", "11,011.67"],
                ["L2561A", "949 CTNS", "Penne Rigate", "8,630.47"],
                ["", "4967 CTNS", "TOTAL", "50,829.00"],
            ],
        ]
        raw = self._make_raw_doc(text, tables)
        result = extract_one(raw)

        assert result.doc_type == DocType.bill_of_lading
        assert result.identifiers.bl_no == "BL185831"
        assert result.identifiers.order_no == "ORD-2024-33562"
        assert result.identifiers.container_no == "WSHZ2980815"
        assert result.identifiers.seal_no == "SL677814"
        assert result.parties.shipper == "Mediterraneo Foods Export S.r.l"
        assert result.parties.consignee == "Levant Food Supplies Co"
        assert result.logistics.pol == "Naples, Italy"
        assert result.logistics.pod == "Hong Kong"
        assert result.logistics.vessel == "JOHNSON STAR"
        assert result.logistics.voyage == "875E"

    def test_legacy_packing_list_extraction(self):
        """Test extraction from a legacy fixed-width packing list."""
        text = (
            "==============================================================================\n"
            "P A C K I N G   L I S T\n"
            "==============================================================================\n"
            "SHIPPER : Mediterraneo Foods Export S.r.l.\n"
            "CONSIGNEE: Levant Food Supplies Co.\n"
            "N. Ordine     : ORD-2024-33562        REF      : REF/HK/5919-H\n"
            "B/L NO        : BL185831              CONTAINER: WSHZ2980815 40'HC\n"
            "VESSEL        : JOHNSON STAR 875E         SEAL     : SL677814\n"
            "POL           : Naples, Italy         POD      : Hong Kong\n"
            "------------------------------------------------------------------------------\n"
            "LOT       DESCRIPTION               No. of PkgsPeso Neto kg  Peso Bruto kg\n"
            "------------------------------------------------------------------------------\n"
            "L2461A    Spaghetti No.5            1119    10518.60      11011.67\n"
            "L2561A    Penne Rigate              949     7952.62       8630.47\n"
            "L2434C    Lasagne Sheets            892     7421.44       7849.56\n"
            "------------------------------------------------------------------------------\n"
            "TOTAL                               4967    47634.83      50829.00\n"
            "=============================================================================="
        )
        raw = self._make_raw_doc(text, [])
        result = extract_one(raw)

        assert result.doc_type == DocType.packing_list
        assert result.identifiers.order_no == "ORD-2024-33562"
        assert result.identifiers.bl_no == "BL185831"
        assert result.identifiers.container_no == "WSHZ2980815"
        assert result.identifiers.seal_no == "SL677814"
        assert result.parties.shipper == "Mediterraneo Foods Export S.r.l"
        assert result.parties.consignee == "Levant Food Supplies Co"
        assert result.logistics.vessel == "JOHNSON STAR"
        assert result.logistics.voyage == "875E"
        assert result.logistics.pol == "Naples, Italy"
        assert result.logistics.pod == "Hong Kong"
        assert len(result.line_items) == 3
        assert result.line_items[0].lot == "L2461A"
        assert result.line_items[0].description == "Spaghetti No.5"
        assert result.line_items[0].cartons == 1119
        assert result.line_items[0].net_kg == pytest.approx(10518.60)
        assert result.line_items[0].gross_kg == pytest.approx(11011.67)

    def test_xlsx_packing_list(self):
        """Test extraction from an xlsx packing list."""
        text = "Mediterraneo Foods Export S.r.l.\nPACKING LIST"
        tables = [
            [
                ["Order No.", "ORD-2026-77566", "", "B/L No.", "CMAU786782", ""],
                ["Reference", "REF/HK/1884-H", "", "Container", "XUWU7583025 40'GP", ""],
                ["Consignee", "Moodlu Wholesale FZE", "", "Date", "16/03/2026", ""],
                ["Vessel", "WALKER SPIRIT 206W", "", "POD", "Beirut, Lebanon", ""],
            ],
            [
                ["#", "Description", "Lot", "CTNS", "Peso Netto (kg)", "Gross Weight (kg)"],
                ["1", "Tagliatelle Nest", "L2472D", "714", "8717.94", "9759.28"],
                ["2", "Penne Rigate", "L2429D", "790", "6438.5", "6933.85"],
                ["", "TOTAL", "", "", "", ""],
            ],
        ]
        raw = self._make_raw_doc(text, tables, SourceFormat.xlsx)
        result = extract_one(raw)

        assert result.doc_type == DocType.packing_list
        assert result.source_format == SourceFormat.xlsx
        assert result.identifiers.order_no == "ORD-2026-77566"
        assert result.identifiers.bl_no == "CMAU786782"
        assert result.identifiers.container_no == "XUWU7583025"
        assert result.parties.consignee == "Moodlu Wholesale FZE"
        assert result.logistics.vessel == "WALKER SPIRIT"
        assert result.logistics.voyage == "206W"
        assert result.logistics.pod == "Beirut, Lebanon"
        assert len(result.line_items) == 2
        assert result.line_items[0].description == "Tagliatelle Nest"
        assert result.line_items[0].lot == "L2472D"
        assert result.line_items[0].cartons == 714
        assert result.line_items[0].net_kg == pytest.approx(8717.94)

    def test_confirmation_extraction(self):
        """Test extraction from a confirmation document (free text, no tables)."""
        text = (
            "SHIPMENT CONFIRMATION\n"
            "Date: 27 April 2026\n"
            "This confirms shipment of order ORD-2024-33562 (reference REF/HK/5919-H) "
            "from Mediterraneo Foods Export S.r.l. to Levant Food Supplies Co., under "
            "bill of lading BL185831, container WSHZ2980815 (40'HC), vessel JOHNSON STAR "
            "voyage 875E, from Naples, Italy to Hong Kong.\n"
            "Total: 4967 cartons, net 47,634.83 kg, gross 50,829.00 kg."
        )
        raw = self._make_raw_doc(text, [])
        result = extract_one(raw)

        assert result.doc_type == DocType.confirmation
        assert result.identifiers.order_no == "ORD-2024-33562"
        assert result.identifiers.reference == "REF/HK/5919-H"
        assert result.identifiers.bl_no == "BL185831"
        assert result.identifiers.container_no == "WSHZ2980815"
        assert result.totals.cartons == 4967
        assert result.totals.net_kg == pytest.approx(47634.83)
        assert result.totals.gross_kg == pytest.approx(50829.00)

    def test_empty_document_no_crash(self):
        """extract_one must never raise — fill what it can, set rest to None."""
        raw = self._make_raw_doc("", [])
        result = extract_one(raw)

        assert isinstance(result, CanonicalDoc)
        assert result.doc_type == DocType.unknown
        assert result.identifiers.order_no is None
        assert result.line_items == []
        assert result.extraction_confidence == 0.0

    def test_raw_field_labels_populated(self):
        """raw_field_labels must record original labels for auditability."""
        text = "PACKING LIST\nOrder No. ORD-2026-77566"
        tables = [
            [
                ["Order No.", "ORD-2026-77566"],
                ["Reference", "REF/HK/1884-H"],
                ["Container", "XUWU7583025 40'GP"],
            ],
            [
                ["Description", "Lot", "CTNS", "Peso Netto (kg)", "Gross Weight (kg)"],
                ["Tagliatelle Nest", "L2472D", "714", "8717.94", "9759.28"],
            ],
        ]
        raw = self._make_raw_doc(text, tables)
        result = extract_one(raw)

        # The raw_field_labels dict should map canonical -> original label
        assert "order_no" in result.raw_field_labels
        assert "reference" in result.raw_field_labels
        assert "container_no" in result.raw_field_labels
        assert "cartons" in result.raw_field_labels or "net_kg" in result.raw_field_labels

    def test_vessel_voyage_parsing(self):
        """Vessel/Voyage combined field should be split correctly."""
        text = "BILL OF LADING"
        tables = [
            [
                ["Vessel / Voyage", "JOHNSON STAR / 875E"],
            ],
        ]
        raw = self._make_raw_doc(text, tables)
        result = extract_one(raw)

        assert result.logistics.vessel == "JOHNSON STAR"
        assert result.logistics.voyage == "875E"

    def test_doc_id_from_raw(self):
        """doc_id must come from RawDoc, not be recomputed."""
        text = "COMMERCIAL INVOICE"
        raw = self._make_raw_doc(text, [])
        result = extract_one(raw)
        assert result.doc_id == raw.doc_id

    def test_source_path_and_format(self):
        """source_path and source_format must come from RawDoc."""
        text = "PACKING LIST"
        raw = self._make_raw_doc(text, [], SourceFormat.xlsx)
        result = extract_one(raw)
        assert result.source_path == "test_doc.docx"
        assert result.source_format == SourceFormat.xlsx


class TestExtractList:
    def test_extract_list(self):
        """extract() maps extract_one over a list."""
        docs = [
            RawDoc(
                doc_id="a" * 64,
                source_path="a.docx",
                source_format=SourceFormat.docx,
                text="COMMERCIAL INVOICE",
                tables=[],
            ),
            RawDoc(
                doc_id="b" * 64,
                source_path="b.docx",
                source_format=SourceFormat.docx,
                text="BILL OF LADING",
                tables=[],
            ),
        ]
        results = extract(docs)
        assert len(results) == 2
        assert results[0].doc_type == DocType.commercial_invoice
        assert results[1].doc_type == DocType.bill_of_lading


# ── Offline / no-LLM tests ──────────────────────────────────────────────────


class TestOfflineOperation:
    def test_use_llm_false_no_import(self):
        """With use_llm=False, google-generativeai is never imported."""
        import sys

        # Ensure the module isn't already loaded
        modules_before = set(sys.modules.keys())

        text = "COMMERCIAL INVOICE\nOrder No. ORD-2024-33562"
        tables = [
            [["Order No.", "ORD-2024-33562"]],
        ]
        raw = RawDoc(
            doc_id="c" * 64,
            source_path="test.docx",
            source_format=SourceFormat.docx,
            text=text,
            tables=tables,
        )
        result = extract_one(raw, use_llm=False)

        modules_after = set(sys.modules.keys())
        new_modules = modules_after - modules_before
        assert not any("google" in m for m in new_modules), (
            f"google-generativeai was imported despite use_llm=False: {new_modules}"
        )

    def test_extract_confidence_range(self):
        """extraction_confidence must be between 0.0 and 1.0."""
        raw = RawDoc(
            doc_id="d" * 64,
            source_path="test.docx",
            source_format=SourceFormat.docx,
            text="PACKING LIST\nOrder No. ORD-2024-33562\nB/L No. BL185831\nContainer WSHZ2980815",
            tables=[
                [["Order No.", "ORD-2024-33562"], ["B/L No.", "BL185831"], ["Container", "WSHZ2980815"]],
                [
                    ["Description", "Cartons", "Net Weight (kg)", "Gross Weight (kg)"],
                    ["Spaghetti", "1119", "10518.60", "11011.67"],
                ],
            ],
        )
        result = extract_one(raw)
        assert 0.0 <= result.extraction_confidence <= 1.0
