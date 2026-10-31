"""Target roles (decision log 30, setup redesign): each track's roles, and for each role its
topic chips in three tiers, Core / Supporting / Specialist. A chip maps to one or more
underlying topics (forge topic names, or coding-spec topics for Software), or to a special
round: market making, behavioural, conversational, full cases. Only chips with live content
are offered; with none selected, a role-weighted mix draws about 70% Core, 25% Supporting
and 5% Specialist. The profile radar and rating areas follow the role's Core chips.
"""

from __future__ import annotations

from dataclasses import dataclass

TIERS = ("core", "supporting", "specialist")
MIX = {"core": 0.70, "supporting": 0.25, "specialist": 0.05}

# Special rounds (each runs on its own, like Behavioural): the chip's "kind".
MARKET, BEHAVIOURAL, CONVERSATIONAL, DESIGN, CASES = "market", "behavioural", "conversational", "design", "cases"


@dataclass(frozen=True)
class Chip:
    name: str
    topics: tuple[str, ...] = ()  # underlying topics; empty for a special round
    kind: str = "topic"  # "topic" or one of the special rounds
    case_type: str | None = None  # a case-type chip filters full cases

    @property
    def id(self) -> str:
        return self.name


def C(name, *topics, kind="topic", case_type=None) -> Chip:
    return Chip(name, tuple(topics) or ((name,) if kind == "topic" else ()), kind, case_type)


# Chips shared across roles, by name.
Q = {
    "Conditional probability": C("Conditional probability"),
    "Probability": C("Probability", "Discrete probability", "Continuous probability"),
    "Expected value": C("Expected value", "Expectations", "Market-style expected value puzzles"),
    "Combinatorics": C("Combinatorics"),
    "Mental math": C("Mental math", "Mental math and estimation", "Quantitative arithmetic"),
    "Market making": C("Market making", kind=MARKET),
    "Game theory": C("Game theory", "Game theory and strategic decisions", "Optimal decisions"),
    "Betting & sizing": C("Betting & sizing", "Betting, bankroll and optimal staking", "Expected utility and risk"),
    "Statistics": C("Statistics", "Statistics", "Variance, covariance and correlation"),
    "Distributions": C("Distributions", "Probability distributions and sampling"),
    "Bayesian statistics": C("Bayesian statistics"),
    "Stochastic processes": C("Stochastic processes"),
    "Optimisation": C("Optimisation", "Optimisation", "Discrete optimisation"),
    "Linear algebra": C("Linear algebra"),
    "Calculus": C("Calculus"),
    "Pricing-model maths": C("Pricing-model maths", "Pricing-model mathematics"),
    "Probability inequalities": C("Probability inequalities"),
    "Number theory": C("Number theory"),
    "Geometry": C("Geometry"),
    "Sequences": C("Sequences", "Sequences and recurrences"),
    "Statistical inference": C("Statistical inference", "Statistical inference and hypothesis testing"),
}
QD = {  # quant-dev coding families (qd_), live once merged
    name: C(name, name) for name in ("Order books", "P&L accounting", "Time series", "Probability in code",
                                     "Trading data structures", "Event processing")
}
I = {
    "Accounting": C("Accounting", "Accounting and three-statement linkages", "Accounting"),
    "DCF": C("DCF"),
    "Valuation multiples": C("Valuation multiples", "Valuation multiples", "Valuation"),
    "Trading comps": C("Trading comps", "Trading comparables"),
    "WACC": C("WACC"),
    "EV to equity value": C("EV to equity value", "Enterprise value and equity value bridge", "Share count"),
    "Free cash flow & working capital": C("Free cash flow & working capital", "Working capital and free cash flow"),
    "Behavioural": C("Behavioural", kind=BEHAVIOURAL),
    "LBO": C("LBO"),
    "M&A": C("M&A"),
    "Accretion/dilution": C("Accretion/dilution"),
    "Precedent transactions": C("Precedent transactions"),
    "Financial statement analysis": C("Financial statement analysis"),
    "Capital structure": C("Capital structure", "Capital structure and financing"),
    "Capital raising & IPOs": C("Capital raising & IPOs", "Capital raising and IPOs"),
    "Conceptual questions": C("Conceptual questions", kind=CONVERSATIONAL),
}
K = {
    "Market sizing": C("Market sizing", "Market sizing with stated assumptions", "Market sizing"),
    "Profitability": C("Profitability"),
    "Growth rates": C("Growth rates", "Growth"),
    "Pricing": C("Pricing"),
    "Investment decisions": C("Investment decisions", "Investment"),
    "Behavioural": C("Behavioural", kind=BEHAVIOURAL),
    "Unit economics": C("Unit economics"),
    "Breakeven": C("Breakeven"),
    "Mix & weighted averages": C("Mix & weighted averages", "Weighted averages and mix effects"),
    "Operations": C("Operations"),
    "Full case": C("Full case", kind=CASES),
}
CASE_TYPES = ("Market entry", "Cost reduction", "Growth strategy", "Pricing", "M&A due diligence", "Operations", "Segmentation")
# Case-type chips filter full cases by case_type ("Pricing case": "Pricing" is already a topic chip).
CASE_CHIPS = tuple(C(f"{t} case", kind=CASES, case_type=t) for t in CASE_TYPES)
S = {
    # swf_ fundamentals (hidden until merged): names as the families may spell them.
    "Arrays & strings": C("Arrays & strings", "Arrays & strings", "Arrays and strings", "Arrays", "Strings"),
    "Hash maps & sets": C("Hash maps & sets", "Hash maps & sets", "Hash maps and sets", "Hash maps", "Hashing"),
    "Linked lists": C("Linked lists"),
    "Stacks & queues": C("Stacks & queues", "Stacks & queues", "Stacks and queues", "Stacks", "Queues"),
    "Trees": C("Trees", "Trees", "Binary trees"),
    "Recursion": C("Recursion"),
    "Sorting & searching": C("Sorting & searching", "Sorting & searching", "Sorting and searching", "Sorting", "Searching"),
    "Two pointers & sliding window": C("Two pointers & sliding window", "Two pointers", "Sliding window", "Prefix sums"),
    "Binary search": C("Binary search", "Binary search on the answer", "Binary search"),
    "Graphs": C("Graphs", "Graphs", "Union-find"),
    "Heaps & greedy": C("Heaps & greedy", "Heaps", "Greedy"),
    "Intervals": C("Intervals"),
    "Dynamic programming": C("Dynamic programming"),
    "Backtracking": C("Backtracking"),
    "Tries": C("Tries"),
    "Bit manipulation": C("Bit manipulation"),
    "Monotonic stack": C("Monotonic stack"),
    "Design concepts": C("Design concepts", kind=DESIGN),
}


@dataclass(frozen=True)
class Role:
    id: str
    track: str
    name: str
    core: tuple[Chip, ...]
    supporting: tuple[Chip, ...] = ()
    specialist: tuple[Chip, ...] = ()
    coding: bool = False  # Software: a coding round; chips filter coding problems
    opener: bool = False  # Quant development: a spoken opener, then a coding round
    design_questions: int = 1  # Design concepts questions after the coding round, if time remains

    def tiers(self):
        return (("core", self.core), ("supporting", self.supporting), ("specialist", self.specialist))


def pick(table, *names):
    return tuple(table[n] for n in names)


ROLES: tuple[Role, ...] = (
    Role("quant_trading", "quant", "Quantitative Trading",
         pick(Q, "Conditional probability", "Probability", "Expected value", "Combinatorics", "Mental math", "Market making",
              "Game theory", "Betting & sizing"),
         pick(Q, "Statistics", "Distributions", "Bayesian statistics", "Stochastic processes"),
         pick(Q, "Optimisation", "Linear algebra", "Calculus", "Pricing-model maths", "Probability inequalities", "Number theory",
              "Geometry", "Sequences")),
    Role("quant_research", "quant", "Quantitative Research",
         pick(Q, "Probability", "Conditional probability", "Expected value", "Statistics", "Statistical inference", "Distributions",
              "Bayesian statistics", "Linear algebra", "Stochastic processes"),
         pick(Q, "Calculus", "Optimisation", "Probability inequalities", "Pricing-model maths", "Combinatorics"),
         pick(Q, "Mental math", "Game theory", "Betting & sizing", "Market making", "Number theory", "Geometry", "Sequences")),
    # A spoken opener (Probability, Expected value), then a coding round on the quant-dev families.
    Role("quant_dev", "quant", "Quantitative Development", pick(Q, "Probability", "Expected value") + tuple(QD.values()),
         opener=True, coding=True),
    Role("ib_analyst", "ib", "Investment Banking Analyst",
         pick(I, "Accounting", "DCF", "Valuation multiples", "Trading comps", "WACC", "EV to equity value",
              "Free cash flow & working capital", "Behavioural", "Conceptual questions"),
         pick(I, "LBO", "M&A", "Accretion/dilution", "Precedent transactions", "Financial statement analysis"),
         pick(I, "Capital structure", "Capital raising & IPOs")),
    Role("ma_analyst", "ib", "M&A Analyst",
         pick(I, "M&A", "Accretion/dilution", "Precedent transactions", "Trading comps", "DCF", "EV to equity value", "LBO",
              "Behavioural", "Conceptual questions"),
         pick(I, "Accounting", "Valuation multiples", "WACC", "Free cash flow & working capital"),
         pick(I, "Capital structure", "Capital raising & IPOs", "Financial statement analysis")),
    Role("ecm_analyst", "ib", "Capital Markets Analyst",
         pick(I, "Capital raising & IPOs", "Capital structure", "WACC", "Valuation multiples", "Trading comps",
              "Financial statement analysis", "Behavioural", "Conceptual questions"),
         pick(I, "Accounting", "DCF", "EV to equity value", "Free cash flow & working capital"),
         pick(I, "LBO", "M&A", "Accretion/dilution", "Precedent transactions")),
    Role("strategy", "consulting", "Strategy Consulting",
         pick(K, "Market sizing", "Profitability", "Growth rates", "Pricing", "Investment decisions", "Behavioural", "Full case"),
         pick(K, "Unit economics", "Breakeven", "Mix & weighted averages"),
         pick(K, "Operations") + CASE_CHIPS),
    Role("management", "consulting", "Management Consulting",
         pick(K, "Profitability", "Breakeven", "Pricing", "Unit economics", "Mix & weighted averages", "Market sizing",
              "Behavioural", "Full case"),
         pick(K, "Growth rates", "Investment decisions", "Operations"),
         CASE_CHIPS),
    Role("operations", "consulting", "Operations Consulting",
         pick(K, "Operations", "Breakeven", "Unit economics", "Mix & weighted averages", "Profitability", "Behavioural", "Full case"),
         pick(K, "Investment decisions", "Pricing", "Market sizing"),
         pick(K, "Growth rates") + CASE_CHIPS),
    Role("swe", "software", "Software Engineer",
         pick(S, "Arrays & strings", "Hash maps & sets", "Linked lists", "Stacks & queues", "Trees", "Recursion",
              "Sorting & searching", "Two pointers & sliding window", "Binary search", "Graphs", "Design concepts"),
         pick(S, "Heaps & greedy", "Intervals", "Dynamic programming", "Backtracking"),
         pick(S, "Tries", "Bit manipulation", "Monotonic stack"), coding=True),
    # Coding first, then two Design concepts questions (probe and twist each) if time remains.
    Role("backend", "software", "Backend Engineer",
         pick(S, "Design concepts", "Hash maps & sets", "Arrays & strings", "Trees", "Graphs", "Sorting & searching"),
         pick(S, "Heaps & greedy", "Intervals", "Two pointers & sliding window", "Binary search", "Stacks & queues", "Linked lists"),
         pick(S, "Dynamic programming", "Backtracking", "Tries", "Bit manipulation", "Monotonic stack"),
         coding=True, design_questions=2),
)
BY_ID = {r.id: r for r in ROLES}


def roles_for(track: str) -> list[Role]:
    return [r for r in ROLES if r.track == track]


def default_role(track: str) -> Role | None:
    found = roles_for(track)
    return found[0] if found else None


def chip_for(role: Role, topic: str | None) -> tuple[str, Chip] | None:
    """The role's chip (and tier) holding a topic; Core first."""
    for tier, chips in role.tiers():
        for chip in chips:
            if topic and topic.casefold() in {t.casefold() for t in chip.topics}:
                return tier, chip
    return None


def area_for(role: Role, topic: str | None) -> str | None:
    """A rated answer counts toward the role's chip holding its topic (the radar draws Core)."""
    found = chip_for(role, topic)
    return found[1].name if found else None


# --- Choosing questions for a role ---------------------------------------------------------

def topic_chips(role: Role, chosen: list[str] | None = None) -> list[tuple[str, Chip]]:
    """(tier, chip) for the role's topic chips (not special rounds), optionally only the chosen ones."""
    out = [(tier, chip) for tier, chips in role.tiers() for chip in chips if chip.kind == "topic"]
    return [(t, c) for t, c in out if not chosen or c.id in chosen]


def weights(role: Role, live_topics: set[str], chosen: list[str] | None = None) -> dict[str, float]:
    """A weight per underlying topic. Chosen chips: equal weight per chip. None chosen: the
    role-weighted mix, MIX[tier] shared equally by that tier's live chips (a tier with no live
    chip passes nothing on, so the live tiers keep their ratio)."""
    pairs = [(t, c, [x for x in c.topics if x in live_topics]) for t, c in topic_chips(role, chosen)]
    pairs = [(t, c, ts) for t, c, ts in pairs if ts]
    out: dict[str, float] = {}
    for tier in TIERS:
        group = [(c, ts) for t, c, ts in pairs if t == tier]
        if not group:
            continue
        share = (1.0 / len(pairs) * len(group)) if chosen else MIX[tier]
        for c, ts in group:
            for topic in ts:
                out[topic] = out.get(topic, 0.0) + share / len(group) / len(ts)
    total = sum(out.values()) or 1.0
    return {k: v / total for k, v in out.items()}


def weighted_source(bank, role: Role, start: str, rng, chosen: list[str] | None = None, pack: str | None = None):
    """A BankSource over the role's topics whose next new question is drawn by topic weight
    (within the ladder's nearest level), so a role-weighted mix is about 70/25/5."""
    from engine.bank import DIFFICULTIES, BankSource

    live = {t for t, _ in bank.topics(pack or role.track)}
    w = weights(role, live, chosen)
    if not w:
        raise ValueError("no live topics for this role")

    class Weighted(BankSource):
        def candidates(self):
            if self._next is not None and self._next[0] == self.level and self._next[1] in self.unused:
                return [self._next[1]]
            if not self.unused:
                return []
            distance = lambda tid: abs(DIFFICULTIES.index(self.templates[tid].difficulty) - self.level)  # noqa: E731
            best = min(distance(tid) for tid in self.unused)
            pool = sorted(tid for tid in self.unused if distance(tid) == best)
            per_topic = {}
            for tid in self.templates:
                per_topic[self.templates[tid].topic] = per_topic.get(self.templates[tid].topic, 0) + 1
            mass = [w.get(self.templates[tid].topic, 0.0) / per_topic[self.templates[tid].topic] for tid in pool]
            choice = self.rng.choices(pool, weights=mass)[0] if sum(mass) > 0 else self.rng.choice(pool)
            self._next = (self.level, choice)
            return [choice]

    return Weighted(bank, tuple(sorted(w)), start, rng=rng, pack=pack or role.track), w


# --- What the setup page gets ---------------------------------------------------------------

def live_topics(bank, role: Role) -> set[str]:
    """Underlying topics with content for this role: forge topics on the role's track, or the
    coding specs' topics for a coding role (quant_dev families for Quantitative Development)."""
    from app import coding
    if role.opener:  # the opener's quant topics and the quant-dev coding topics
        return {t for t, _ in bank.topics("quant")} | {s["topic"] for s in coding.specs("quant_dev").values()}
    if role.coding:
        return {s["topic"] for s in coding.specs(role.track).values()}
    return {t for t, _ in bank.topics(role.track)}


def special_live(chip: Chip, track: str, bank) -> bool:
    from app import behavioural, conversational, market
    if chip.kind == MARKET:
        return market.enabled() and bool(bank.topics("quant"))
    if chip.kind == BEHAVIOURAL:
        return bool(behavioural.rows_for(track))
    if chip.kind == CONVERSATIONAL:
        return conversational.enabled() and bool(conversational.load("ib"))
    if chip.kind == DESIGN:
        return conversational.enabled() and bool(conversational.load("software"))
    if chip.kind == CASES:  # full cases (item 4): hidden until that module is in
        try:
            from app import cases
        except ImportError:
            return False
        return cases.enabled() and bool(cases.load(chip.case_type))
    return False


def live_chips(bank, role: Role) -> list[tuple[str, Chip]]:
    """The role's chips that have content now (a chip with nothing merged yet is hidden)."""
    topics = live_topics(bank, role)
    out = []
    for tier, chips in role.tiers():
        for chip in chips:
            if chip.kind == "topic" and any(t in topics for t in chip.topics):
                out.append((tier, chip))
            elif chip.kind != "topic" and special_live(chip, role.track, bank):
                out.append((tier, chip))
    return out


def view(bank, role: Role) -> dict:
    """A role for the setup page: its live chips by tier, its rating areas (Core chips) and,
    for Quantitative Development, whether its own coding questions are in yet."""
    from app import coding, quant_dev
    chips = live_chips(bank, role)
    note, available = None, bool(chips)
    if role.opener:
        own = bool(coding.specs("quant_dev"))
        available = bool(quant_dev.opener_topics(bank)) and (own or bool(coding.specs("software")))
        note = None if own else "Coding questions being added"
    return {"id": role.id, "name": role.name, "available": available, "note": note,
            "coding": role.coding, "opener": role.opener,
            "chips": [{"id": c.id, "name": c.name, "tier": tier, "kind": c.kind} for tier, c in chips],
            "areas": [c.name for tier, c in chips if tier == "core" and c.kind in {"topic", MARKET}]
                     + (["Coding"] if role.opener else []),
            # The profile counts an answer toward a Core chip by its topic (placement answers too).
            "area_topics": {c.name: list(c.topics) or [c.name] for tier, c in chips if tier == "core" and c.kind in {"topic", MARKET}}}
