"""Agent persona definitions for email simulation.

Each persona represents a role in the shipping workflow. They send documents
with realistic email bodies and may introduce deliberate errors.
"""

from dataclasses import dataclass, field


@dataclass
class AgentPersona:
    """A simulated shipping workflow participant."""
    name: str
    role: str
    email_alias: str  # used as FROM address (simulated)
    company: str
    language: str = "en"  # en, it, fr
    error_rate: float = 0.15  # probability of introducing a deliberate error
    description: str = ""

    def email_body(self, document_names: list[str], shipment_info: dict) -> str:
        """Generate a realistic email body for sending documents."""
        docs_list = ", ".join(document_names)
        order_ref = shipment_info.get("order_no", "N/A")

        templates = {
            "en": {
                "shipper": (
                    f"Dear Team,\n\n"
                    f"Please find attached the shipping documents for order {order_ref}.\n"
                    f"Documents included: {docs_list}\n\n"
                    f"Kindly verify and confirm receipt.\n\n"
                    f"Best regards,\n{self.name}\n{self.role}\n{self.company}"
                ),
                "logistics": (
                    f"Hi,\n\n"
                    f"Attached are the logistics docs for shipment {order_ref}.\n"
                    f"Files: {docs_list}\n\n"
                    f"Please process at your earliest convenience.\n\n"
                    f"Thanks,\n{self.name}\n{self.company}"
                ),
                "warehouse": (
                    f"To whom it may concern,\n\n"
                    f"Enclosed: packing list and related docs for {order_ref}.\n"
                    f"Attachments: {docs_list}\n\n"
                    f"Regards,\n{self.name}\nWarehouse Operations\n{self.company}"
                ),
                "consignee": (
                    f"Dear Shipping Team,\n\n"
                    f"We are expecting delivery for order {order_ref}.\n"
                    f"Attached for your reference: {docs_list}\n\n"
                    f"Please advise on ETA.\n\n"
                    f"Best,\n{self.name}\n{self.role}\n{self.company}"
                ),
            },
            "it": {
                "shipper": (
                    f"Gentili,\n\n"
                    f"in allegato i documenti di spedizione per l'ordine {order_ref}.\n"
                    f"Documenti: {docs_list}\n\n"
                    f"Cordiali saluti,\n{self.name}\n{self.company}"
                ),
                "logistics": (
                    f"Salve,\n\n"
                    f"trovate in allegato la documentazione logistica per {order_ref}.\n"
                    f"File: {docs_list}\n\n"
                    f"Grazie,\n{self.name}\n{self.company}"
                ),
            },
        }

        lang_templates = templates.get(self.language, templates["en"])
        role_key = self.role.lower().replace(" ", "_")
        return lang_templates.get(role_key, lang_templates.get("shipper", ""))

    def email_subject(self, shipment_info: dict) -> str:
        """Generate a realistic email subject line."""
        order_ref = shipment_info.get("order_no", "N/A")
        templates = {
            "shipper": f"Shipping Documents — Order {order_ref}",
            "logistics": f"Logistics Docs — {order_ref}",
            "warehouse": f"Packing List & Docs — {order_ref}",
            "consignee": f"Expected Delivery — {order_ref}",
        }
        role_key = self.role.lower().replace(" ", "_")
        return templates.get(role_key, f"Documents — {order_ref}")


# --- Default persona roster ---

PERSONAS = [
    AgentPersona(
        name="Marco Rossi",
        role="Shipper",
        email_alias="marco.rossi@pastagarovo.com",
        company="Pastagarovo S.r.l.",
        language="en",
        error_rate=0.10,
        description="Export manager at Pastagarovo. Sends invoices and bills of lading.",
    ),
    AgentPersona(
        name="Lucia Ferretti",
        role="Logistics Coordinator",
        email_alias="lucia.ferretti@pastagarovo.com",
        company="Pastagarovo S.r.l.",
        language="en",
        error_rate=0.15,
        description="Coordinates shipping schedules. Sometimes copies wrong order numbers.",
    ),
    AgentPersona(
        name="Ahmad Nasrallah",
        role="Warehouse Manager",
        email_alias="ahmad.n@pastagarovo-lb.com",
        company="Pastagarovo Lebanon",
        language="en",
        error_rate=0.20,
        description="Warehouse ops in Beirut. Packing lists occasionally have weight discrepancies.",
    ),
    AgentPersona(
        name="Sophie Khoury",
        role="Consignee",
        email_alias="sophie.khoury@garofalo-distribution.com",
        company="Garofalo Distribution MENA",
        language="en",
        error_rate=0.05,
        description="Receiving manager. Low error rate — mostly confirms clean docs.",
    ),
    AgentPersona(
        name="Giuseppe Bianchi",
        role="Shipper",
        email_alias="g.bianchi@garofalo.it",
        company="Garofalo S.p.A.",
        language="it",
        error_rate=0.12,
        description="Senior export clerk. Sometimes sends Italian-language documents.",
    ),
]


def get_persona(name: str) -> AgentPersona | None:
    """Look up a persona by name."""
    for p in PERSONAS:
        if p.name == name:
            return p
    return None


def get_random_persona(rng_seed: int | None = None) -> AgentPersona:
    """Get a random persona. Deterministic if rng_seed is provided."""
    import random
    rng = random.Random(rng_seed)
    return rng.choice(PERSONAS)
