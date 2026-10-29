"""Deterministic topic quotas: each source item occupies at most one slot."""
from collections import Counter


def parse_quotas(value):
    quotas = {}
    if not value:
        return quotas
    for entry in value.split(","):
        topic, count = entry.rsplit("=", 1)
        topic, count = " ".join(topic.casefold().split()), int(count)
        if not topic or count <= 0 or topic in quotas:
            raise ValueError("Invalid per-topic quota")
        quotas[topic] = count
    return quotas


def select_questions(questions, limit, priority, quotas=None):
    priority = tuple(priority)
    rank = lambda topic: priority.index(topic) if topic in priority else len(priority)
    questions = sorted(questions, key=lambda q: min(map(rank, q.topics), default=len(priority)))
    quotas = quotas or {}
    if not quotas:
        chosen = questions[:limit]
        assigned = {q.key: min(q.topics, key=rank) if q.topics else "other" for q in chosen}
        return chosen, assigned, {}
    if sum(quotas.values()) != limit or any(type(n) is not int or n <= 0 for n in quotas.values()):
        raise ValueError("Per-topic quotas must sum to --limit")
    slots = [topic for topic in sorted(quotas, key=rank) for _ in range(quotas[topic])]
    candidates = {topic: [q.key for q in questions if topic in q.topics] for topic in quotas}
    matched = {}
    def place(slot, seen):
        for key in candidates[slots[slot]]:
            if key in seen:
                continue
            seen.add(key)
            if key not in matched or place(matched[key], seen):
                matched[key] = slot
                return True
        return False
    for slot in range(len(slots)):
        place(slot, set())
    assigned = {key: slots[slot] for key, slot in matched.items()}
    counts = Counter(assigned.values())
    return ([q for q in questions if q.key in assigned], assigned,
            {topic: count - counts[topic] for topic, count in quotas.items()})
