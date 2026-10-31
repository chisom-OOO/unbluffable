"""Where a question came from (forge provenance, made visible): which model wrote the solver,
how many variants it reproduced, and which wrong methods were verified in code. Read from
each family's stored verification record in content/forge. The solver and wrong-method
code are not stored with the bank, so only these figures can be shown."""

from __future__ import annotations

from engine.bank import NAME_SEPARATOR, ForgeTemplate

AUTHORS = {"meta-models/muse-spark-open": "Muse Spark Open", "muse-spark-open": "Muse Spark Open"}


def author_name(model_id: str | None) -> str:
    for prefix, name in AUTHORS.items():
        if model_id and model_id.startswith(prefix):
            return name
    return model_id or "an unrecorded model"


def pretty(name: str) -> str:
    return name.replace("_", " ").strip()


def method_names(template: ForgeTemplate) -> list[str]:
    names = {part for inst in template.instances for nv in inst.wrong for part in nv.misconception.split(NAME_SEPARATOR) if part}
    return sorted(pretty(n) for n in names)


def provenance(template: ForgeTemplate | None) -> dict | None:
    if template is None:
        return None
    models = template.models if isinstance(template.models, dict) else {}
    v = template.verification if isinstance(template.verification, dict) else {}
    solver = v.get("solver") or {}
    verified = bool(v.get("misconceptions_verified"))
    variants = len(template.instances)
    return {
        "template_id": template.template_id, "pack": template.pack, "topic": template.topic, "difficulty": template.difficulty,
        "author": author_name(models.get("author")), "author_id": models.get("author"),
        "variants": variants, "solver_passed": bool(solver.get("passed")),
        "variants_checked": int(solver.get("variants_checked") or 0),
        "exact": str(solver.get("max_absolute_error")) == "0",
        "wrong_methods_verified": verified,
        "wrong_methods": method_names(template) if verified else [],
        "solver_source_stored": False,
    }


def rows(p: dict | None) -> list[dict]:
    """The receipt rows: label and text, for the page."""
    if not p:
        return []
    solver = (f"Written by {p['author']}; reproduced the verified answer on {p['variants_checked']}/{p['variants']} variants"
              + (" exactly." if p["exact"] else " within tolerance.")) if p["solver_passed"] else f"Written by {p['author']}; not verified."
    methods = (f"{len(p['wrong_methods'])} verified in code: {', '.join(p['wrong_methods'])}." if p["wrong_methods_verified"]
               and p["wrong_methods"] else "None verified for this family.")
    return [{"key": "solver", "label": "Solver", "text": solver},
            {"key": "wrong_methods", "label": "Wrong methods", "text": methods},
            {"key": "source", "label": "Solver code", "text": "Not stored with the question bank; these figures come from its verification record."}]


def matched_row(template: ForgeTemplate | None, puzzle, observation) -> dict | None:
    """When the answer matches a wrong method the forge verified, the receipt says so."""
    p = provenance(template)
    if not p or not p["wrong_methods_verified"] or observation is None:
        return None
    hit = [nv for nv in puzzle.named_values if nv.key in observation.matched]
    if not hit:
        return None
    names = ", ".join(pretty(part) for nv in hit for part in nv.misconception.split(NAME_SEPARATOR) if part)
    return {"key": "forge_method", "label": "Where this wrong method came from",
            "text": f"Matches a wrong method {p['author']} wrote and code verified: {names}."}


def catalogue(templates: dict[str, ForgeTemplate]) -> dict:
    """/ui/forge: every family by track, with totals."""
    families = sorted((provenance(t) for t in templates.values()), key=lambda p: (p["pack"], p["topic"], p["template_id"]))
    tracks = {}
    for p in families:
        tracks.setdefault(p["pack"], []).append(p)

    def totals(group):
        return {"families": len(group), "variants": sum(p["variants"] for p in group),
                "solvers_verified": sum(p["solver_passed"] for p in group),
                "variants_checked": sum(p["variants_checked"] for p in group),
                "wrong_methods_verified": sum(len(p["wrong_methods"]) for p in group),
                "families_with_verified_methods": sum(p["wrong_methods_verified"] for p in group)}
    return {"tracks": [{"id": pack, "families": group, "totals": totals(group)} for pack, group in tracks.items()],
            "totals": totals(families)}
