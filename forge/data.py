"""Private CSV ingestion and exact numeric answers."""
import ast
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
    """Parse whole topic labels, including CSV-encoded Python or JSON lists."""
    if isinstance(value, str):
        value = value.strip()
        if value.startswith(("[", "(")):
            try:
                value = json.loads(value)
            except ValueError:
                try:
                    value = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    return ()
        else:
            value = re.split(r"[,;|]", value)
    if not isinstance(value, (list, tuple)):
        return ()
    aliases = {"expected values": "expected value", "expectation": "expected value",
               "markov chain": "markov chains", "conditional probabilities": "conditional probability"}
    labels = []
    for raw in value:
        if not isinstance(raw, str):
            continue
        label = " ".join(raw.strip(" '\"").casefold().split())
        label = aliases.get(label, label)
        if (not 3 <= len(label) <= 80 or len(label.split()) > 8
                or not re.fullmatch(r"[a-z][a-z0-9 &+/'()-]*[a-z0-9+)]", label)
                or re.search(r"\b(?:contributor|contributed|author|solution|thanks|submitted|note|notes)\b", label)):
            continue
        labels.append(label)
    return tuple(dict.fromkeys(labels))


class LoadCounts(dict):
    def __init__(self, counts, per_topic, topic_vocabulary=None):
        super().__init__(counts)
        self.per_topic = per_topic
        self.topic_vocabulary = topic_vocabulary or {}


def load_csv(path):
    # Two passes over in-memory rows; vocabulary frequencies count rows, including
    # locked/duplicate rows. No source text is written outside private records.
    with open(path, newline="", encoding="utf-8-sig") as stream:
        rows = [{k.strip().casefold(): (v or "").strip() for k, v in raw.items() if k}
                for raw in csv.DictReader(stream)]
    labels = [topics(row.get("topics", row.get("topic", row.get("tags", "")))) for row in rows]
    frequencies = Counter(topic for row_topics in labels for topic in row_topics)
    vocabulary = {topic: count for topic, count in sorted(frequencies.items()) if count >= 5}
    seen, questions, per_topic = set(), [], {}
    counts = Counter({key: 0 for key in ("rows", "kept", "locked", "empty", "image", "duplicate")})
    for row, candidates in zip(rows, labels):
        counts["rows"] += 1
        row_topics = tuple(topic for topic in candidates if topic in vocabulary)
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
                                  row_topics, statement, solution, sha))
        counts["kept"] += 1
    return questions, LoadCounts(counts, {k: dict(v) for k, v in per_topic.items()}, vocabulary)


def numeric_parts(text):
    """Return a single numeric literal, percent scale and implied decimal precision."""
    text = str(text).strip()
    if len(text) > 512:
        raise Reject("answer", "numeric_too_large")
    text = text.replace(r"\%", "%").replace("$", "").replace(r"\(", "").replace(r"\)", "").strip()
    if text.startswith(r"\boxed{") and text.endswith("}"):
        text = text[7:-1].strip()
    text = re.sub(r"^(?:(?:=|\u2248|\u2243|~)|\\(?:approx|simeq|sim))\s*", "", text).strip()
    text = re.sub(r"\\(?:dfrac|tfrac|frac)\s*\{\s*([+-]?\d+)\s*\}\s*\{\s*([+-]?\d+)\s*\}",
                  lambda m: m[1] + "/" + m[2], text)
    text = re.sub(r"([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*(?:\\times|\\cdot|\u00d7|\*)\s*10\s*\^\s*\{?([+-]?\d+)\}?",
                  lambda m: m[1] + "e" + m[2], text)
    text = re.sub(r"\\(?:text|mathrm)\{([^{}]*)\}", r" \1", text)
    literal = r"[+-]?(?:\d+\s*/\s*[+-]?\d+|(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)"
    match = re.match(r"(" + literal + r")\s*(%|percent\b)?", text, re.I)
    if not match:
        raise Reject("answer", "not_numeric")
    token, percent = match[1].replace(",", "").replace(" ", ""), bool(match[2])
    remainder = text[match.end():].strip()
    # Permit trailing units/words, never an expression, second answer or number.
    if remainder and (not re.fullmatch(r"[A-Za-z\u00b5\u03bc\u00b0/' .,!;:()-]+", remainder)
                      or re.search(r"\b(?:or|and)\b", remainder, re.I)):
        raise Reject("answer", "not_numeric")
    exp = re.search(r"[eE]([+-]?\d+)$", token)
    if exp and abs(int(exp[1])) > 1000:
        raise Reject("answer", "numeric_too_large")
    implied = Fraction(0)
    if "/" not in token:
        mantissa = re.split("[eE]", token)[0]
        exponent = int(exp[1]) if exp else 0
        if "." in mantissa or exponent < 0:
            places = len(mantissa.partition(".")[2])
            power = exponent - places
            unit = Fraction(10 ** power) if power >= 0 else Fraction(1, 10 ** -power)
            implied = unit / 2 / (100 if percent else 1)
    return token, percent, implied


def list_answer(text):
    """A list answer ("[106, 110]", "[8,18,13]") as canonical JSON, or None for any other
    answer. Lists compare by exact JSON equality after normalising whitespace."""
    t = str(text or "").strip()
    if not t.startswith("["):
        return None
    try:
        value = json.loads(t, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    except ValueError:
        raise Reject("answer", "invalid_list") from None

    def ok(v):
        return isinstance(v, (str, bool, int)) or (isinstance(v, list) and all(ok(x) for x in v))
    if not isinstance(value, list) or not ok(value):
        raise Reject("answer", "invalid_list")
    return json.dumps(value, separators=(",", ":"))


def answer_value(text):
    """A family answer: its canonical list JSON (a coding-only family), else the exact number."""
    return list_answer(text) or number(text)


def number(text):
    token, percent, _ = numeric_parts(text)
    try:
        value = Fraction(*(int(part) for part in token.split('/'))) if '/' in token else Fraction(token)
    except (ValueError, ZeroDivisionError, OverflowError):
        raise Reject("answer", "not_numeric") from None
    return value / 100 if percent else value


@dataclass(frozen=True)
class Answer:
    value: Fraction
    tolerance: Fraction
    tolerance_source: str = "exact"


def stored_answer(data, solution):
    quote, raw = data["quote"], data["answer"]
    if quote and quote in solution and raw in {"none", ""}:
        raise Reject("answer", "not_numeric")
    if not quote or quote not in solution or raw not in quote:
        raise Reject("answer", "quote_not_verbatim")
    value = number(raw)
    _, _, implied = numeric_parts(raw)
    tolerance = number(data["tolerance"]) if data["tolerance"] not in {"none", ""} else Fraction(0)
    if tolerance < 0:
        raise Reject("answer", "negative_tolerance")
    if not implied:
        return Answer(value, Fraction(0), "exact")
    if tolerance:
        tq = data["tolerance_quote"]
        if not tq or tq not in solution or data["tolerance"] not in tq:
            raise Reject("answer", "tolerance_not_stated")
        return Answer(value, tolerance, "stated")
    return Answer(value, implied, "implied")
