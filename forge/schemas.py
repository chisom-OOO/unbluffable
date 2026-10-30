def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def arr(item):
    return {"type": "array", "items": item}


S = {"type": "string"}
B = {"type": "boolean"}
ANSWER = obj({"class": {"type": "string", "enum": ["numeric_single", "symbolic", "multiple_choice",
    "multi_part", "proof_or_explanation", "code"]}, "answer": S, "quote": S, "tolerance": S, "tolerance_quote": S})
PARAM = obj({"name": S, "minimum": S, "maximum": S, "step": S, "original": S})
WRONG = obj({"misconception": S, "code": S})
PART = obj({"enabled": B, "text": S, "parameter": PARAM, "solver": S,
            "wrong": arr(WRONG), "step_names": arr(S)})
AUTHOR = obj({"text": S, "parameters": arr(PARAM), "solver": S, "wrong": arr(WRONG),
              "step_names": arr(S), "part2": PART})
SIMULATOR = obj({"code": S, "part2_code": S})
READINGS = obj({"alternatives": arr(obj({"reading": S, "answer": S, "tolerance": S}))})
BLIND = obj({"answer": S})

READING_TWINS = obj({"answers": arr(S)})
