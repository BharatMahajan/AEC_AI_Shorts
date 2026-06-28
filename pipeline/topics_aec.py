"""topics_aec.py — the AEC taxonomy and the domain lexicon.

This is the extensible knowledge base the rest of the system draws on (plan
§5.3). Buckets group concrete AI features inside the AEC industry; the lexicon
is what the L2 critic scores "AEC vocabulary density" against. Both are plain
data so they can be edited without touching loop logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Bucket:
    key: str
    name: str
    tools: tuple[str, ...]
    features: tuple[str, ...]


# Taxonomy buckets (extensible). Each "feature" is a concrete AI capability a
# script can be built around — never vague ("AI helps design") but specific.
BUCKETS: tuple[Bucket, ...] = (
    Bucket(
        "bim_authoring", "BIM authoring",
        ("Revit", "Autodesk Forma", "generative design"),
        ("generative floorplate layout", "automated room tagging",
         "AI-assisted family creation", "early-stage massing with Forma"),
    ),
    Bucket(
        "cad", "CAD",
        ("AutoCAD", "AutoCAD AI"),
        ("Markup Assist for digitizing redlines", "Smart Blocks placement prediction",
         "Activity Insights", "AI command suggestions"),
    ),
    Bucket(
        "civil_infra", "Civil / infrastructure",
        ("Civil 3D", "InfraWorks"),
        ("automated corridor modeling", "AI grading optimization",
         "pressure-pipe network design", "earthwork volume optimization"),
    ),
    Bucket(
        "coordination_clash", "Coordination & clash",
        ("Navisworks", "Autodesk Construction Cloud", "ACC"),
        ("ML-prioritized clash detection", "automated clash grouping",
         "model coordination in ACC", "issue auto-routing"),
    ),
    Bucket(
        "project_controls", "Project controls",
        ("Primavera P6", "Microsoft Project", "cost/risk ML"),
        ("ML schedule risk forecasting", "predictive cost overrun detection",
         "AI-driven resource leveling", "earned-value anomaly detection"),
    ),
    Bucket(
        "reality_capture", "Reality capture & digital twins",
        ("point cloud", "Scan-to-BIM", "digital twin"),
        ("automated Scan-to-BIM from point clouds", "ML object classification in scans",
         "digital twin sync from IoT sensors", "progress tracking from site scans"),
    ),
    Bucket(
        "structural", "Structural",
        ("structural analysis", "generative structural design"),
        ("AI member sizing optimization", "generative steel framing",
         "ML-based load prediction", "automated rebar detailing"),
    ),
    Bucket(
        "mep", "MEP",
        ("MEP routing", "energy modeling"),
        ("automated duct/pipe routing", "ML energy-use prediction",
         "AI load calculations", "clash-aware MEP layout"),
    ),
    Bucket(
        "transport", "Transport",
        ("traffic modeling", "pavement ML"),
        ("ML traffic flow prediction", "pavement-distress detection from imagery",
         "AI signal-timing optimization", "transit demand forecasting"),
    ),
    Bucket(
        "water_environmental", "Water & environmental",
        ("hydraulic model", "treatment optimization"),
        ("ML treatment-plant process optimization", "AI leakage detection in networks",
         "hydraulic model auto-calibration", "demand forecasting for water systems"),
    ),
    Bucket(
        "site_ops", "Site operations",
        ("computer vision", "drones", "robotics"),
        ("CV-based PPE/safety monitoring", "drone progress capture",
         "autonomous layout robots", "equipment-utilization tracking"),
    ),
    Bucket(
        "docs_specs", "Documents & specs",
        ("RFI", "submittal", "spec LLMs"),
        ("LLM RFI drafting and response", "automated submittal review",
         "spec compliance checking", "drawing-to-text extraction"),
    ),
    Bucket(
        "gis_planning", "GIS & planning",
        ("GIS", "site selection"),
        ("AI site-suitability analysis", "ML land-use classification",
         "automated zoning compliance", "flood-risk modeling"),
    ),
)

BUCKETS_BY_KEY: dict[str, Bucket] = {b.key: b for b in BUCKETS}


# Curated AEC lexicon for the critic's "vocabulary density" rubric (§5.2).
AEC_LEXICON: frozenset[str] = frozenset({
    "bim", "lod", "clash", "corridor", "rfi", "takeoff", "parametric",
    "point cloud", "digital twin", "hydraulic model", "boq", "revit",
    "autocad", "civil 3d", "navisworks", "acc", "mep", "hvac", "gis",
    "generative design", "scan-to-bim", "submittal", "rebar", "earthwork",
    "grading", "p6", "primavera", "earned value", "quantity", "clearance",
    "ifc", "coordination", "rendering", "geotechnical", "structural",
    "pavement", "leakage", "treatment plant", "site", "construction",
    "engineering", "model", "workflow", "design",
})


# Hook style templates used by the writer + scored by the critic (§5.2).
HOOK_STYLES: tuple[str, ...] = (
    "shocking_stat",      # "Engineers waste 40% of their week on this..."
    "question",           # "What if Revit modeled the building for you?"
    "bold_claim",         # "This kills manual clash detection."
    "pain_point",         # "Tired of chasing RFIs across email?"
    "future_tease",       # "The way we coordinate models is about to change."
)


def all_features() -> list[tuple[str, str, str]]:
    """Flatten to (bucket_key, tool_hint, feature) triples for selection."""
    out: list[tuple[str, str, str]] = []
    for b in BUCKETS:
        tool_hint = b.tools[0] if b.tools else ""
        for f in b.features:
            out.append((b.key, tool_hint, f))
    return out
