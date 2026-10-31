"""Large inputs for a coding round's Part 2 (decision log 29): "Now n is up to 100,000; make it
fast." The same source builds the inputs in the forge's sandbox (where the forge's verified
solver computes the expected outputs) and in the browser (Pyodide), so both sides build
identical inputs from (config, seed, n). Standard library only; no other imports.

A config lists the parameters in dependency order:
  {"key", "kind": "list", "lo", "hi", "sorted", "distinct", "same": key | None,
   "ge": {"of": key, "lo", "hi"} | None}       a list of n ints (or as long as `same`)
  {"key", "kind": "int", "choices": [...]}     one of the values seen in the tests
  {"key", "kind": "int", "len_plus": {"of": key, "lo", "hi"}}   at least a list's length
  {"key", "kind": "bool", "choices": [...]}
"""

import random


def generate(config, seed, n):
    rng = random.Random(seed)
    out = {}
    for p in config["params"]:
        key, kind = p["key"], p["kind"]
        if kind == "list":
            length = len(out[p["same"]]) if p.get("same") else n
            ge = p.get("ge")
            if ge:
                base = out[ge["of"]]
                values = [base[i] + rng.randint(ge["lo"], ge["hi"]) for i in range(length)]
            elif p.get("distinct"):
                top = max(p["hi"], p["lo"] + 4 * length)
                values = rng.sample(range(p["lo"], top + 1), length)
            else:
                values = [rng.randint(p["lo"], p["hi"]) for _ in range(length)]
            if p.get("sorted"):
                values.sort()
            out[key] = values
        elif kind == "int" and p.get("len_plus"):
            extra = p["len_plus"]
            out[key] = len(out[extra["of"]]) + rng.randint(extra["lo"], extra["hi"])
        else:
            out[key] = rng.choice(p["choices"])
    return out
