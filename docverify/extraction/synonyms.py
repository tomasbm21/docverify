"""Synonym dictionary for canonical label mapping.

OWNER: Agent 02 (Extraction)
Maps multilingual field labels (EN/IT/ES/AR/FR) to canonical field names.
Data-driven dict — not a wall of ifs.

Normalization: lowercase, strip leading/trailing whitespace, collapse internal
whitespace to single space, remove trailing colons.
"""

import re

# Canonical field names used in schemas/models.py
# Identifiers: order_no, bl_no, reference, container_no, seal_no
# Parties: shipper, consignee
# Logistics: vessel, voyage, pol, pod, ship_date
# LineItem / Totals: description, lot, cartons, net_kg, gross_kg, tare_kg, unit_price, units, amount, value, currency
# Metadata: invoice_no, invoice_date, buyer, incoterm, pack

# Each key is a normalized label (lowercased, stripped, single-space).
# Multiple keys can map to the same canonical field.
_SYN_MAP: dict[str, str] = {
    # ── Identifiers ──────────────────────────────────────────────────────────
    # order_no
    "order no": "order_no",
    "order no.": "order_no",
    "order number": "order_no",
    "ordine": "order_no",
    "n. ordine": "order_no",
    "n ordine": "order_no",
    "po": "order_no",
    "p/o no": "order_no",
    "p/o": "order_no",
    "order ref": "order_no",
    "order reference": "order_no",
    "purchase order": "order_no",
    "ord. no": "order_no",
    "ord. no.": "order_no",
    "رقم طلب الشراء": "order_no",
    "رقم الأمر": "order_no",
    "رقم امر الشراء": "order_no",
    "طلب شراء": "order_no",
    "رقم الاورد": "order_no",
    "رقم الطلب": "order_no",
    "أمر شراء": "order_no",
    "numéro de commande": "order_no",
    "n° de commande": "order_no",
    "n de commande": "order_no",
    "commande": "order_no",
    "n° commande": "order_no",
    "bon de commande": "order_no",
    "réf. commande": "order_no",

    # bl_no
    "b/l no": "bl_no",
    "b/l no.": "bl_no",
    "bill of lading no": "bl_no",
    "bill of lading no.": "bl_no",
    "bl number": "bl_no",
    "bl no": "bl_no",
    "bl no.": "bl_no",
    "polizza di carico": "bl_no",
    "b/l": "bl_no",
    "بوليصة الشحن": "bl_no",
    "بوليصة": "bl_no",
    "رقم بوليصة الشحن": "bl_no",
    "سند الشحن": "bl_no",
    "connaissement": "bl_no",
    "n° de connaissement": "bl_no",
    "n de connaissement": "bl_no",
    "n° connaissement": "bl_no",
    "numéro de connaissement": "bl_no",

    # reference
    "reference": "reference",
    "ref": "reference",
    "riferimento": "reference",
    "our ref": "reference",
    "referencia": "reference",
    "rif.": "reference",
    "المرجع": "reference",
    "رقم المرجع": "reference",
    "مرجع": "reference",
    "الرقم المرجعي": "reference",
    "référence": "reference",
    "n° de référence": "reference",
    "n de référence": "reference",
    "numéro de référence": "reference",
    "réf.": "reference",
    "réf": "reference",

    # container_no
    "container no": "container_no",
    "container no.": "container_no",
    "container": "container_no",
    "container/seal": "container_no",
    "contenitore": "container_no",
    "container / type": "container_no",
    "رقم الحاوية": "container_no",
    "حاوية": "container_no",
    "الحاوية": "container_no",
    "رقم الحاوي": "container_no",
    "رقم الكونتينر": "container_no",

    # seal_no
    "seal no": "seal_no",
    "seal no.": "seal_no",
    "seal": "seal_no",
    "sigillo": "seal_no",
    "precinto": "seal_no",
    "رقم الختم": "seal_no",
    "ختم": "seal_no",
    "الختم": "seal_no",
    "رقم الصمام": "seal_no",
    "رقم السيل": "seal_no",
    "numéro de scellé": "seal_no",
    "n° de scellé": "seal_no",
    "n de scellé": "seal_no",
    "scellé": "seal_no",

    # ── Parties ──────────────────────────────────────────────────────────────
    # shipper
    "shipper": "shipper",
    "mittente": "shipper",
    "exporter": "shipper",
    "from": "shipper",
    "speditore": "shipper",
    "المرسل": "shipper",
    "الشاحن": "shipper",
    "المصدر": "shipper",
    "شركة الشحن": "shipper",
    "الشاحنة": "shipper",
    "expéditeur": "shipper",
    "chargeur": "shipper",

    # consignee
    "consignee": "consignee",
    "destinatario": "consignee",
    "importer": "consignee",
    "to": "consignee",
    "المستلم": "consignee",
    "المتلقي": "consignee",
    "المستورد": "consignee",
    "المستوردة": "consignee",
    "destinataire": "consignee",
    "réceptionnaire": "consignee",

    # ── Logistics ────────────────────────────────────────────────────────────
    "vessel": "vessel",
    "vessel / voyage": "vessel",
    "nave": "vessel",
    "السفينة": "vessel",
    "اسم السفينة": "vessel",
    "الباخرة": "vessel",
    "navire": "vessel",
    "vaisseau": "vessel",
    "nom du navire": "vessel",
    "voyage": "voyage",
    "viaggio": "voyage",
    "الرحلة": "voyage",
    "رقم الرحلة": "voyage",
    "رحلة": "voyage",
    "n° de voyage": "voyage",
    "port of loading": "pol",
    "pol": "pol",
    "porto di carico": "pol",
    "ميناء الشحن": "pol",
    "ميناء التحميل": "pol",
    "ميناء المصدر": "pol",
    "ميناء المغادرة": "pol",
    "port de chargement": "pol",
    "port d'embarquement": "pol",
    "port of discharge": "pod",
    "pod": "pod",
    "porto di scarico": "pod",
    "ميناء الوصول": "pod",
    "ميناء التفريغ": "pod",
    "ميناء الاستلام": "pod",
    "ميناب الوصول": "pod",
    "port de déchargement": "pod",
    "port de destination": "pod",
    "date": "ship_date",
    "ship date": "ship_date",
    "shipping date": "ship_date",
    "data di spedizione": "ship_date",
    "invoice date": "ship_date",
    "data fattura": "ship_date",
    "تاريخ الشحن": "ship_date",
    "تاريخ التحميل": "ship_date",
    "تاريخ الإرسال": "ship_date",
    "تاريخ الفاتورة": "ship_date",
    "تاريخ المغادرة": "ship_date",
    "date d'expédition": "ship_date",
    "date d'envoi": "ship_date",
    "date d'embarquement": "ship_date",
    "date de départ": "ship_date",
    "date de facture": "ship_date",

    # ── Line-item / Totals fields ────────────────────────────────────────────
    # description
    "description": "description",
    "descrizione": "description",
    "description of goods": "description",
    "descrizione merce": "description",
    "الوصف": "description",
    "وصف البضائع": "description",
    "وصف": "description",
    "البضائع": "description",
    "وصف البضاعة": "description",
    "البيان": "description",
    "description des marchandises": "description",
    "description de la marchandise": "description",
    "désignation": "description",

    # lot
    "lot": "lot",
    "lot no": "lot",
    "lot no.": "lot",
    "lotto": "lot",
    "marks & nos": "lot",
    "marks and nos": "lot",
    "marks & numbers": "lot",
    "رقم التشغيلة": "lot",
    "رقم اللوط": "lot",
    "لوط": "lot",
    "دفعة": "lot",
    "رقم الدفعة": "lot",
    "numéro de lot": "lot",
    "n° de lot": "lot",
    "n de lot": "lot",
    "lot n°": "lot",

    # cartons
    "cartons": "cartons",
    "colli": "cartons",
    "cartons/cases": "cartons",
    "no. of cartons": "cartons",
    "no of cartons": "cartons",
    "cajas": "cartons",
    "ctns": "cartons",
    "qty (ctns)": "cartons",
    "no. of packages": "cartons",
    "no of packages": "cartons",
    "no. of pkgs": "cartons",
    "n. colli": "cartons",
    "packages": "cartons",
    "pack": "pack",
    "الصناديق": "cartons",
    "كراتين": "cartons",
    "عدد الصناديق": "cartons",
    "علب": "cartons",
    "طرود": "cartons",
    "عدد الكراتين": "cartons",
    "صناديق": "cartons",
    "nombre de cartons": "cartons",
    "nb de cartons": "cartons",
    "caisses": "cartons",
    "colis": "cartons",
    "nombre de colis": "cartons",
    "paquets": "cartons",

    # net_kg
    "net weight (kg)": "net_kg",
    "peso netto (kg)": "net_kg",
    "n.w. (kgs)": "net_kg",
    "peso neto kg": "net_kg",
    "net wt": "net_kg",
    "net weight": "net_kg",
    "peso netto": "net_kg",
    "peso neto": "net_kg",
    "n.w.": "net_kg",
    "net kg": "net_kg",
    "peso netto kg": "net_kg",
    "الوزن الصافي": "net_kg",
    "وزن صافي": "net_kg",
    "الوزن الصافي كجم": "net_kg",
    "الوزن الصافي بالكيلو": "net_kg",
    "الوزن الصافي بالكيلوغرام": "net_kg",
    "poids net": "net_kg",
    "poids net (kg)": "net_kg",
    "poids net kg": "net_kg",
    "poids net en kg": "net_kg",
    "p. net": "net_kg",

    # gross_kg
    "gross weight (kg)": "gross_kg",
    "peso lordo (kg)": "gross_kg",
    "g.w. (kgs)": "gross_kg",
    "peso bruto kg": "gross_kg",
    "gross wt": "gross_kg",
    "gross weight": "gross_kg",
    "peso lordo": "gross_kg",
    "peso bruto": "gross_kg",
    "g.w.": "gross_kg",
    "gross kg": "gross_kg",
    "peso lordo kg": "gross_kg",
    "الوزن الإجمالي": "gross_kg",
    "الوزن الخام": "gross_kg",
    "وزن إجمالي": "gross_kg",
    "الوزن الإجمالي كجم": "gross_kg",
    "الوزن الإجمالي بالكيلو": "gross_kg",
    "الوزن الإجمالي بالكيلوغرام": "gross_kg",
    "poids brut": "gross_kg",
    "poids brut (kg)": "gross_kg",
    "poids brut kg": "gross_kg",
    "poids brut en kg": "gross_kg",
    "p. brut": "gross_kg",

    # unit_price
    "unit price": "unit_price",
    "prezzo unitario": "unit_price",
    "price": "unit_price",
    "prezzo": "unit_price",
    "unit cost": "unit_price",
    "السعر": "unit_price",
    "سعر الوحدة": "unit_price",
    "السعر لكل وحدة": "unit_price",
    "ثمن الوحدة": "unit_price",
    "سعر القطعة": "unit_price",
    "prix unitaire": "unit_price",
    "prix unit.": "unit_price",

    # units
    "units": "units",
    "unità": "units",
    "qty": "units",
    "quantity": "units",
    "quantità": "units",
    "pezzi": "units",
    "الوحدات": "units",
    "الكمية": "units",
    "عدد": "units",
    "قطع": "units",
    "quantité": "units",
    "qté": "units",
    "unités": "units",
    "pièces": "units",

    # amount
    "amount": "amount",
    "importo": "amount",
    "total": "amount",
    "totale": "amount",
    "line total": "amount",
    "المبلغ": "amount",
    "المبلغ الكلي": "amount",
    "المجموع": "amount",
    "montant": "amount",
    "montant total": "amount",

    # value (totals level)
    "value": "value",
    "valore": "value",
    "total value": "value",
    "invoice value": "value",
    "القيمة": "value",
    "القيمة الإجمالية": "value",
    "قيمة الفاتورة": "value",
    "valeur totale": "value",
    "valeur": "value",
    "montant net": "value",

    # currency
    "currency": "currency",
    "valuta": "currency",
    "divisa": "currency",
    "العملة": "currency",
    "النقود": "currency",
    "devise": "currency",

    # ── Metadata fields (for structured extraction) ──────────────────────────
    "invoice no": "invoice_no",
    "invoice no.": "invoice_no",
    "fattura n.": "invoice_no",
    "n. fattura": "invoice_no",
    "رقم الفاتورة": "invoice_no",
    "فاتورة رقم": "invoice_no",
    "n° de facture": "invoice_no",
    "n de facture": "invoice_no",
    "numéro de facture": "invoice_no",
    "facture n°": "invoice_no",

    "buyer": "buyer",
    "acquirente": "buyer",
    "cliente": "buyer",
    "customer": "buyer",
    "المشتري": "buyer",
    "المشتراة": "buyer",
    "acheteur": "buyer",

    "incoterm": "incoterm",
    "terms": "incoterm",
    "condizioni": "incoterm",
    "شروط التسليم": "incoterm",
    "شروط التجارة الدولية": "incoterm",
    "الشروط": "incoterm",

    "notify party": "notify_party",
    "notificare": "notify_party",
    "طرف الإخطار": "notify_party",
    "الطرف المُخطر": "notify_party",
    "partie notifiée": "notify_party",

    # ── Additional Arabic fields ──────────────────────────────────────────────
    "بلد المنشأ": "origin_country",
    "بلد الأصل": "origin_country",
    "منشأ البضائع": "origin_country",
    "بلد المصدر": "origin_country",
    "دولة المنشأ": "origin_country",
    "pays d'origine": "origin_country",

    "البائع": "shipper",
    "المرسل إليه": "consignee",

    # ── Container tare weight ─────────────────────────────────────────────────
    "tare weight": "tare_kg",
    "tara": "tare_kg",
    "tare kg": "tare_kg",
    "peso tara": "tare_kg",
    "poids tare": "tare_kg",
    "poids à vide": "tare_kg",
    "الوزن الصافي للحاوية": "tare_kg",
    "وزن الحاوية الفارغة": "tare_kg",
    "وزن التارة": "tare_kg",
}


def _normalize_label(label: str) -> str:
    """Normalize a label for dictionary lookup.

    Lowercase, strip, collapse whitespace, remove trailing punctuation like : or .
    """
    s = label.lower().strip()
    s = re.sub(r"\s+", " ", s)
    # Remove trailing colon/period (but not internal ones like "N.W.")
    s = re.sub(r"[:\s]+$", "", s)
    return s


def canonical_field(label: str) -> str | None:
    """Map a raw field label to its canonical name.

    Returns the canonical field name string (e.g. 'net_kg', 'order_no') or None
    if the label is not recognized. Comparison is case-insensitive after
    normalizing (lowercase, strip, collapse whitespace, strip trailing colons).
    """
    normalized = _normalize_label(label)
    return _SYN_MAP.get(normalized)


def all_canonical_fields() -> set[str]:
    """Return the set of all canonical field names in the dictionary."""
    return set(_SYN_MAP.values())


if __name__ == "__main__":
    # Quick smoke test
    tests = [
        ("Net Weight (kg)", "net_kg"),
        ("Peso Netto (kg)", "net_kg"),
        ("N.W. (KGS)", "net_kg"),
        ("Peso Neto kg", "net_kg"),
        ("Net Wt", "net_kg"),
        ("B/L No", "bl_no"),
        ("Bill of Lading No", "bl_no"),
        ("Polizza di carico", "bl_no"),
        ("Order No.", "order_no"),
        ("N. Ordine", "order_no"),
        ("CTNS", "cartons"),
        ("Colli", "cartons"),
        ("Cartons", "cartons"),
        ("Container / Type", "container_no"),
        ("Seal No.", "seal_no"),
        ("Shipper", "shipper"),
        ("Mittente", "shipper"),
        ("Consignee", "consignee"),
        ("Destinatario", "consignee"),
        ("Unit Price", "unit_price"),
        ("Currency", "currency"),
    ]
    passed = 0
    for label, expected in tests:
        result = canonical_field(label)
        status = "OK" if result == expected else "FAIL"
        if status == "FAIL":
            print(f"  {status}: '{label}' -> {result!r} (expected {expected!r})")
        passed += status == "OK"
    print(f"{passed}/{len(tests)} synonym lookups passed")
