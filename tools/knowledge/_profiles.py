"""Industry profile presets for knowledge_v1 tools (no customer identity)."""

from __future__ import annotations

from bankflow_v2.knowledge.models import IndustryProfile
from bankflow_v2.knowledge import versioning


PRESETS: dict[str, IndustryProfile] = {
    "building_material": IndustryProfile(
        primary_industry_ids=("internal.building_material_trade",),
        secondary_industry_ids=("internal.environmental_engineering",),
        specialty_concept_ids=(
            "building_material",
            "sand",
            "cement",
            "environmental_engineering_service",
        ),
        taxonomy_version=versioning.TAXONOMY_VERSION,
        profile_name="building_material",
    ),
    "construction_coal": IndustryProfile(
        primary_industry_ids=("47",),
        secondary_industry_ids=("06",),
        specialty_concept_ids=("construction", "coal"),
        taxonomy_version=versioning.TAXONOMY_VERSION,
        profile_name="construction_coal",
    ),
    "alcohol_retail": IndustryProfile(
        primary_industry_ids=("internal.alcohol_tobacco_retail",),
        secondary_industry_ids=(),
        specialty_concept_ids=("alcohol", "tobacco", "supermarket"),
        taxonomy_version=versioning.TAXONOMY_VERSION,
        profile_name="alcohol_retail",
    ),
    "furniture_decoration": IndustryProfile(
        primary_industry_ids=("internal.furniture_appliance_sales",),
        secondary_industry_ids=("internal.decoration_engineering",),
        specialty_concept_ids=("furniture", "home_appliance", "decoration"),
        taxonomy_version=versioning.TAXONOMY_VERSION,
        profile_name="furniture_decoration",
    ),
}


def classify_profile_name(
    business_context: dict[str, str] | None,
) -> str:
    """Classify a legacy cache business context to one of the known presets."""
    if not business_context:
        return "building_material"
    text = " ".join(str(value) for value in business_context.values())
    if any(token in text for token in ("烟酒", "超市", "便利店")):
        return "alcohol_retail"
    if any(
        token in text
        for token in ("家具", "家电", "装饰装修", "装修")
    ):
        return "furniture_decoration"
    return "building_material"


def resolve_profile(
    preset: str | None = None,
    profile_json: str | None = None,
) -> IndustryProfile:
    if profile_json:
        import json
        from pathlib import Path

        data = json.loads(Path(profile_json).read_text(encoding="utf-8"))
        return IndustryProfile(
            primary_industry_ids=tuple(data.get("primary_industry_ids", [])),
            secondary_industry_ids=tuple(data.get("secondary_industry_ids", [])),
            specialty_concept_ids=tuple(data.get("specialty_concept_ids", [])),
            normalized_products_services=tuple(
                data.get("normalized_products_services", [])
            ),
            taxonomy_version=str(
                data.get("taxonomy_version", versioning.TAXONOMY_VERSION)
            ),
            profile_version=str(data.get("profile_version", "1")),
        )
    if preset in PRESETS:
        return PRESETS[preset]
    raise SystemExit(
        "请提供 --profile ("
        + "/".join(PRESETS)
        + ") 或 --profile-json"
    )
