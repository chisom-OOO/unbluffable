"""Data-only forge bank: no generated code, model calls or engine rule changes."""
from fractions import Fraction
import json
from pathlib import Path
import random

from forge.packs import pack_name, template_pack


class NoTwinAvailable(ValueError):
    pass


def answer_value(instance):
    value = instance["answer"]
    if isinstance(value, bool):
        raise ValueError("An answer must be numeric")
    return Fraction(str(value))



def answer_matches(instance, committed_number_text):
    """Normalize an explicit spoken number span, then use only the stored tolerance."""
    from engine.answers import normalise_numbers, parse_number
    from forge.data import number
    from forge.errors import Reject
    import re

    text = normalise_numbers(committed_number_text)
    text = re.sub(r"^\s*minus\s+", "-", text, flags=re.I)
    try:
        # Parse the complete numeric span first: a fractional percent still needs /100.
        try:
            value = number(text)
        except Reject:
            if re.search(r"\bminus\b|-\s*\d", text, re.I):
                return False
            stated = parse_number(text)
            if stated is None:
                return False
            value = stated.value
        tolerance = Fraction(str(instance.get("tolerance", "0")))
        return tolerance >= 0 and abs(value - answer_value(instance)) <= tolerance
    except (Reject, ValueError, ArithmeticError):
        return False


class TemplateBank:
    def __init__(self, templates, *, pack="quant"):
        self.pack = pack_name(pack)
        self.templates = {}
        for source in templates:
            if template_pack(source) != self.pack:
                continue
            template = {**source, "pack": self.pack}
            key = template["template_id"]
            if key in self.templates:
                raise ValueError("Duplicate template ID")
            if not template.get("instances"):
                raise ValueError("Template has no instances")
            for instance in template["instances"]:
                answer_value(instance)
            self.templates[key] = template

    @classmethod
    def load(cls, root, *, pack="quant"):
        return cls([json.loads(path.read_text(encoding="utf-8")) for path in sorted(Path(root).glob("*.json"))],
                   pack=pack)

    def choose_instance(self, template_id, rng=None):
        rng = rng or random.SystemRandom()
        return rng.choice(self.templates[template_id]["instances"])

    def choose_twin(self, template_id, asked, rng=None):
        """A same-family twin must have different parameters AND a different exact answer."""
        rng = rng or random.SystemRandom()
        original = answer_value(asked)
        candidates = [row for row in self.templates[template_id]["instances"]
                      if answer_value(row) != original
                      and not ("params" in row and "params" in asked and row["params"] == asked["params"])]
        if not candidates:
            raise NoTwinAvailable("No different-answer twin available")
        return rng.choice(candidates)
