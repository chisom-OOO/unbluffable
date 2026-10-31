"""Pack identifiers shared by offline forging and the data-only bank reader."""
import re

PACK_PREFIXES = {"quant": "family", "ib": "ib", "consulting": "co", "software": "sw", "quant_dev": "qd"}
# A new batch of families for a pack can take its own prefix (swf_, qx_, ibx_, swc_...), so its
# files never overwrite an existing pack's: two to eight lowercase letters or digits.
PREFIX = re.compile(r"[a-z][a-z0-9]{1,7}")


def pack_name(value="quant"):
    if value not in PACK_PREFIXES:
        raise ValueError("Unknown content pack")
    return value


def template_pack(template):
    return pack_name(template.get("pack", "quant"))


def output_prefix(pack, prefix=None):
    """The file prefix for a pack's families: its default, or a new batch's own prefix, which
    may never be another pack's default (so an ib batch can't write sw_ files)."""
    pack_name(pack)
    if prefix is None:
        return PACK_PREFIXES[pack]
    if not PREFIX.fullmatch(prefix) or prefix == "family" or (prefix in PACK_PREFIXES.values() and prefix != PACK_PREFIXES[pack]):
        raise ValueError("Invalid output prefix")
    return prefix


def pack_template_id(pack, family_id, prefix=None):
    head = output_prefix(pack, prefix)
    if pack == "quant" and prefix is None:
        return "family_" + family_id
    match = re.fullmatch(r"[A-Za-z]*(\d+)", family_id)
    if match is None:
        raise ValueError("Sector family IDs must have a numeric index")
    return head + "_F" + str(int(match[1])).zfill(3)
