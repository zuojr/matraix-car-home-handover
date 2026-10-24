"""Use the repository's native persona loader/template on both execution paths."""

import hashlib
import os
from pathlib import Path


def runtime_contract(catalog):
    from matraix.agents.persona import loader, templating
    from matraix import persona_dimension_catalog

    files = {
        "loader.py": Path(loader.__file__),
        "templating.py": Path(templating.__file__),
        "persona_dimension_catalog.py": Path(persona_dimension_catalog.__file__),
        "dimensions.json": Path(catalog),
    }
    files.update({p.name: p for p in templating.default_templates_dir().glob("*.j2")})
    return {
        "files": {
            name: hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for name, path in files.items()
        },
        "profile_max_chars": os.getenv("MATRAIX_PERSONA_PROFILE_MAX_CHARS", ""),
    }


def render(case, plan, plan_path):
    if not case["native_persona"]["dimensions"] and plan["purpose"] == "validation":
        return "Synthetic interface fixture only; no native persona identity is being represented."
    from matraix.agents.persona.loader import load_persona
    from matraix.agents.persona.templating import (
        PERSONA_SYSTEM_TEMPLATE,
        render_persona_template,
        resolve_persona_template,
    )

    plan_path = Path(plan_path)
    source = (
        plan_path
        / plan["sources"][case["domain"]]["pool"]
        / Path(case["native_persona"]["source_yaml"]).name
    )
    catalog = plan_path / "identity/dimensions.json"
    if runtime_contract(catalog) != plan.get("identity_contract"):
        raise ValueError(
            "Native persona renderer/schema changed after plan preparation"
        )
    persona = load_persona(source)
    if (
        persona.persona_id != case["source_persona_id"]
        or persona.dimensions != case["native_persona"]["dimensions"]
    ):
        raise ValueError("Native identity differs from bound source persona")
    return render_persona_template(
        resolve_persona_template(persona, None, PERSONA_SYSTEM_TEMPLATE),
        persona,
        catalog_path=catalog,
    )


def complete_parts(case, plan, plan_path):
    """Native narrative plus only the source dimensions it does not render.

    Native rendering deliberately skips defaults/metadata. Keeping that residual
    map gives every original dimension once, without repeating the whole map.
    No summarization, truncation or model-generated identity is involved.
    """
    from matraix.persona_dimension_catalog import (
        collect_dimension_items,
        resolve_profile_max_chars,
    )

    if resolve_profile_max_chars() is not None:
        raise ValueError(
            "Full persona required: disable profile truncation before execution"
        )
    narrative = render(case, plan, plan_path)
    original = case["native_persona"]["dimensions"]
    groups = (
        collect_dimension_items(
            original, catalog_path=str(Path(plan_path) / "identity/dimensions.json")
        )
        if original
        else {}
    )
    rendered = {item[0] for items in groups.values() for item in items}
    residual = {key: value for key, value in original.items() if key not in rendered}
    assert (
        rendered.isdisjoint(residual) and rendered | residual.keys() == original.keys()
    )
    return (
        narrative,
        residual,
        {
            "source_dimensions": len(original),
            "narrative_dimensions": sorted(rendered),
            "supplemental_dimensions": sorted(residual),
            "omitted_dimensions": 0,
        },
    )
