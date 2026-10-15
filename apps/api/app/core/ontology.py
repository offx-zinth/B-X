"""Universal Business Ontology: single source of truth for the 14 core primitives.

Principle: universal graph structure, configurable business behavior, pluggable
intelligence. A tea shop and an industrial manufacturer compile to the SAME
engine — domain concepts are configuration, never code branches.

14 core primitives (and only these are core):
  Operational nodes (7): ENTITY RESOURCE ACTOR PROCESS TASK EVENT TRANSACTION
  Relationships (2): DEPENDENCY FLOW
  Properties/rules (5): STATE CAPACITY CONSTRAINT TIME COST

Edge specializations (meanings of FLOW/DEPENDENCY, not new foundations):
  USES PRODUCES CONSUMES PERFORMED_BY TRIGGERS
Domain verbs (supplies, feeds, powers, places, ...) are allowed as extensions
and classify into FLOW or DEPENDENCY families.

Legacy kinds (Metric, Location, Decision, Relationship) are accepted on read
and normalized — never emitted for new graphs.
"""
from __future__ import annotations

# --- Core 14 ---------------------------------------------------------------
NODE_PRIMITIVES: tuple[str, ...] = (
    "ENTITY", "RESOURCE", "ACTOR", "PROCESS", "TASK", "EVENT", "TRANSACTION",
)

EDGE_PRIMITIVES: tuple[str, ...] = ("DEPENDENCY", "FLOW")

PROPERTY_PRIMITIVES: tuple[str, ...] = (
    "STATE", "CAPACITY", "CONSTRAINT", "TIME", "COST",
)

CORE_14: tuple[str, ...] = NODE_PRIMITIVES + EDGE_PRIMITIVES + PROPERTY_PRIMITIVES
assert len(CORE_14) == 14, f"core must be exactly 14, got {len(CORE_14)}"

EDGE_SPECIALIZATIONS: tuple[str, ...] = (
    "USES", "PRODUCES", "CONSUMES", "PERFORMED_BY", "TRIGGERS",
)

# Legacy kinds emitted by older IR versions — normalized on read.
LEGACY_KIND_MAP: dict[str, str] = {
    "Metric": "ENTITY",
    "Location": "ENTITY",
    "Decision": "TASK",
    "Relationship": "ENTITY",
}

# Domain verbs observed in the wild -> core family. Anything unknown ending in
# typical verb forms defaults to FLOW (movement) rather than failing.
FLOW_VERBS = {
    "supplies", "feeds", "powers", "produces", "fulfills", "stocks",
    "places", "contains", "listed_in", "settles", "relates_to",
    "provides", "consumed_by", "flows_to", "sends", "delivers",
    "uses", "produces", "consumes", "performed_by", "triggers",
    "handled_by", "supplied_by",
}
DEPENDENCY_VERBS = {"depends_on", "requires", "blocks", "approves"}


def normalize_kind(kind: str | None) -> str:
    """Normalize any node kind to one of the 7 operational node primitives.

    TitleCase legacy input (Entity, Actor) -> UPPER core. Unknown kinds fall
    back to ENTITY rather than failing — values are never invented, but the
    graph stays executable for unseen business vocabularies (tea shop or
    factory).
    """
    if not kind:
        return "ENTITY"
    k = str(kind).strip().upper()
    if k in NODE_PRIMITIVES:
        return k
    # TitleCase -> UPPER may already be handled; check legacy map (TitleCase keys)
    title = str(kind).strip().title()
    if title in LEGACY_KIND_MAP:
        return LEGACY_KIND_MAP[title]
    if k.title() in LEGACY_KIND_MAP:
        return LEGACY_KIND_MAP[k.title()]
    return "ENTITY"


def classify_edge(edge_type: str | None) -> str:
    """Classify any edge type into DEPENDENCY or FLOW family."""
    if not edge_type:
        return "FLOW"
    t = str(edge_type).strip()
    up = t.upper()
    if up in EDGE_PRIMITIVES:
        return up
    if up in EDGE_SPECIALIZATIONS:
        # USES/CONSUMES/TRIGGERS ride on FLOW; PERFORMED_BY is a dependency link
        if up in ("PERFORMED_BY",):
            return "DEPENDENCY"
        return "FLOW"
    low = t.lower()
    if low in DEPENDENCY_VERBS:
        return "DEPENDENCY"
    return "FLOW"


def validate_edge_type(edge_type: str | None) -> str:
    """Return normalized edge type; domain verbs pass through unchanged.

    Validation is permissive by design: the core family is enforced via
    classify_edge(), while the literal verb is preserved for provenance and UI.
    Only empty types are rejected upstream.
    """
    if not edge_type or not str(edge_type).strip():
        raise ValueError("edge type required")
    return str(edge_type).strip()


# --- Domain extensions (data, not code branches) ---------------------------
# A domain is a named mapping of business vocabulary onto core primitives.
# Adding a new industry means adding an entry here — never forking the engine.
DOMAIN_EXTENSIONS: dict[str, dict[str, str]] = {
    "manufacturing": {
        "ProductionBatch": "ENTITY",
        "Machine": "RESOURCE",
        "Supplier": "ACTOR",
        "Material": "RESOURCE",
        "Production": "PROCESS",
        "Shipment": "ENTITY",
    },
    "tea_shop": {
        "Cup": "ENTITY",
        "MilkStock": "RESOURCE",
        "SugarStock": "RESOURCE",
        "Brewer": "ACTOR",
        "Brew": "TASK",
        "Serve": "TASK",
        "Sale": "TRANSACTION",
        "MorningRush": "EVENT",
    },
    "office": {
        "SupportTicket": "ENTITY",
        "ApprovalRequest": "ENTITY",
        "Workflow": "PROCESS",
    },
    "logistics": {
        "Shipment": "ENTITY",
        "DeliveryRoute": "ENTITY",
    },
}


def kind_for(business_type: str, domain: str | None = None) -> str:
    """Resolve a business type name to a core node primitive via domain map."""
    if domain and domain in DOMAIN_EXTENSIONS and business_type in DOMAIN_EXTENSIONS[domain]:
        return DOMAIN_EXTENSIONS[domain][business_type]
    for _dom, mapping in DOMAIN_EXTENSIONS.items():
        if business_type in mapping:
            return mapping[business_type]
    return "ENTITY"


def describe() -> dict:
    return {
        "core_14": list(CORE_14),
        "operational_nodes": list(NODE_PRIMITIVES),
        "relationships": list(EDGE_PRIMITIVES),
        "edge_specializations": list(EDGE_SPECIALIZATIONS),
        "properties_rules": list(PROPERTY_PRIMITIVES),
        "domains": sorted(DOMAIN_EXTENSIONS.keys()),
    }
