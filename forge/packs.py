"""Pack identifiers shared by offline forging and the data-only bank reader."""
import re

PACK_PREFIXES = {"quant": "family", "ib": "ib", "consulting": "co", "software": "sw"}


def pack_name(value="quant"):
    if value not in PACK_PREFIXES:
        raise ValueError("Unknown content pack")
    return value


def template_pack(template):
    return pack_name(template.get("pack", "quant"))


def pack_template_id(pack, family_id):
    pack_name(pack)
    if pack == "quant":
        return "family_" + family_id
    match = re.fullmatch(r"(?:F|IB|CO|SW)?(\d+)", family_id, flags=re.I)
    if match is None:
        raise ValueError("Sector family IDs must have a numeric index")
    return PACK_PREFIXES[pack] + "_F" + str(int(match[1])).zfill(3)
