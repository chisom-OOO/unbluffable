"""Private CSV ingestion and exact numeric answers."""
import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction

from forge.errors import Reject

PRIORITY = ("probability", "expected value", "combinatorics", "conditional probability",
            "statistics", "markov chains")
CLASSES = ("numeric_single", "symbolic", "multiple_choice", "multi_part", "proof_or_explanation", "code")


@dataclass(frozen=True)
class Question:
    question_id: str
    title: str
    difficulty: str
    topics: tuple
    statement: str
    solution: str
    statement_sha256: str

    @property
    def key(self):
        return hashlib.sha256((self.question_id + "\0" + self.statement_sha256 + "\0" + self.solution).encode()).hexdigest()


def topics(value):
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip().startswith("[") else re.split(r"[,;|]", value)
        except ValueError:
            value = [value]
    aliases = {"expected values": "expected value", "expectation": "expected value",
               "markov chain": "markov chains", "conditional probabilities": "conditional probability"}
    return tuple(dict.fromkeys(aliases.get(str(v).strip().casefold(), str(v).strip().casefold())
                               for v in value if str(v).strip())) or ("other",)


class LoadCounts(dict):
    def __init__(self, counts, per_topic):
        super().__init__(counts)
        self.per_topic = per_topic


def load_csv(path):
    seen, questions, per_topic = set(), [], {}
    counts = Counter({key: 0 for key in ("rows", "kept", "locked", "empty", "image", "duplicate")})
    with open(path, newline="", encoding="utf-8-sig") as stream:
        for raw in csv.DictReader(stream):
            row = {k.strip().casefold(): (v or "").strip() for k, v in raw.items() if k}
            counts["rows"] += 1
            row_topics = topics(row.get("topics", row.get("topic", row.get("tags", ""))))
            for topic in row_topics:
                per_topic.setdefault(topic, Counter())["rows"] += 1
            locked = any(row.get(k, "").casefold() in {"1", "true", "yes", "locked"}
                         for k in ("locked", "is_locked", "islocked", "is_premium", "premium"))
            statement = row.get("statement", row.get("question", row.get("question_text", "")))
            solution = row.get("solution", row.get("worked_solution", ""))
            qid = row.get("question_id", row.get("id", ""))
            image = bool(re.search(r"<(?:img|svg|picture|canvas)\b|data:image/|!\[|\[image\]|\.(?:png|jpe?g|gif|svg|webp)\b",
                                   statement + "\n" + solution, re.I))
            image |= any(v.casefold() not in {"", "0", "false", "none", "null", "[]"}
                         for k, v in row.items() if "image" in k or k == "diagram")
            sha = hashlib.sha256(" ".join(statement.split()).encode()).hexdigest()
            reason = "locked" if locked else "empty" if not qid or not statement or not solution else "image" if image else "duplicate" if sha in seen else None
            for topic in row_topics:
                per_topic[topic][reason or "kept"] += 1
            if reason:
                counts[reason] += 1
                continue
            seen.add(sha)
            questions.append(Question(qid, row.get("title", ""), row.get("difficulty", ""),
                                      topics(row.get("topics", row.get("topic", row.get("tags", "")))), statement, solution, sha))
            counts["kept"] += 1
    return questions, LoadCounts(counts, {k: dict(v) for k, v in per_topic.items()})


def number(text):
    text = str(text).strip().strip("$").strip()
    if len(text) > 512:
        raise Reject("answer", "numeric_too_large")
    exponent = re.search(r"[eE]([+-]?\d+)", text)
    if exponent and abs(int(exponent[1])) > 1000:
        raise Reject("answer", "numeric_too_large")
    text = re.sub(r"\s+percent$", "%", text, flags=re.I).replace(r"\%", "%")
    if text.startswith(r"\boxed{") and text.endswith("}"):
        text = text[7:-1]
    match = re.fullmatch(r"\\(?:d?frac)\{([+-]?\d+)\}\{(\d+)\}", text)
    if match:
        text = match[1] + "/" + match[2]
    if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
        text = text.replace(",", "")
    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()
    if not re.fullmatch(r"[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|\d+\s*/\s*\d+)", text):
        raise Reject("answer", "not_numeric")
    try:
        value = Fraction(text.replace(" ", ""))
    except (ValueError, ZeroDivisionError, OverflowError):
        raise Reject("answer", "not_numeric") from None
    return value / 100 if percent else value


@dataclass(frozen=True)
class Answer:
    value: Fraction
    tolerance: Fraction


def stored_answer(data, solution):
    quote, raw = data["quote"], data["answer"]
    if not quote or quote not in solution or raw not in quote:
        raise Reject("answer", "quote_not_verbatim")
    value = number(raw)
    tolerance = number(data["tolerance"]) if data["tolerance"] not in {"none", ""} else Fraction(0)
    if tolerance < 0:
        raise Reject("answer", "negative_tolerance")
    decimal = "." in raw or "e-" in raw.lower()
    if decimal and tolerance <= 0:
        raise Reject("answer", "decimal_tolerance_missing")
    if tolerance:
        tq = data["tolerance_quote"]
        if not tq or tq not in solution or data["tolerance"] not in tq:
            raise Reject("answer", "tolerance_not_stated")
    return Answer(value, tolerance)
