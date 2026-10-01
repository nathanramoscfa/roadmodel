"""Find the claims in hand-written model prose that the catalog's data contradicts.

update/model_prose.py writes a model's ``best-for`` and ``headline-benchmarks``
from data, and leaves a hand-written field as it is, until the data contradicts
it. Text goes stale as the catalog moves: "Latest Grok release" once Grok 4.7
ships, "OpenAI's most capable frontier model" once GPT-6 Astra outscores it,
"HLE 47.0% (#1)" once three catalog models score higher. Such a ``best-for``
goes to the generator; such a ``headline-benchmarks`` loses the false claim and
keeps the rest.

Only claims the data can settle are checked; anything else ("native
multimodal", "near-Opus coding quality") stands as written.

    figures       an Artificial Analysis figure (Intelligence Index, HLE,
                  SciCode, Terminal-Bench 2.1 / 4.0 / Hard, AA-LCR, τ²-bench
                  banking, Output Speed) that differs from docs/benchmarks.json,
                  or a "(#N)" rank that the catalog alone already rules out
    prices        quoted "$in/$out" or "$x/M output" prices, none of them the
                  model's own
    promotions    "through <date>" with the date past
    letters       "S-tier coding", "multimodal-A" that differ from its letter
    superlatives  latest / cheapest / highest-cost / most capable / best at X,
                  within the scope the clause names (the model's maker, a family
                  such as "GPT-5" or "Claude", a cost tier); false when another
                  model in that scope is newer, cheaper, pricier, higher on the
                  AA Index, or holds a better letter in X

A vendor-reported figure ("... (DeepSeek-reported)") is the vendor's claim, not
Artificial Analysis's, and is not compared. A figure cited for another effort
variant than the one the catalog maps ("9.9 (non-reasoning)" beside a reasoning
row) is not compared either.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from model_prose import Model

LETTERS = "SABCD"
CATEGORIES = ("coding", "planning", "agentic", "multimodal", "long-context", "knowledge", "speed")
SPEED = "median_output_tokens_per_second"

# ---------------------------------------------------------------------------
# Who made a model, and which family a word names
# ---------------------------------------------------------------------------

# Mirrors web/lib/catalog-fields.ts modelProvider, except that gpt-oss is
# OpenAI's (its maker) rather than Groq's (its host). Order matters.
_MAKER_RULES = (
    (re.compile(r"gpt-oss"), "openai"),
    (re.compile(r"claude|opus|sonnet|haiku|fable"), "anthropic"),
    (re.compile(r"gpt"), "openai"),
    (re.compile(r"gemini"), "google"),
    (re.compile(r"grok"), "xai"),
    (re.compile(r"deepseek"), "deepseek"),
    (re.compile(r"mistral|codestral"), "mistral"),
    (re.compile(r"glm"), "zai"),
    (re.compile(r"composer"), "cursor"),
    (re.compile(r"kimi"), "moonshot"),
    (re.compile(r"muse"), "meta"),
)
_POSSESSIVE_MAKER = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google",
    "xai": "xai",
    "spacexai": "xai",
    "deepseek": "deepseek",
    "mistral": "mistral",
    "z.ai": "zai",
    "zhipu": "zai",
    "cursor": "cursor",
    "moonshot": "moonshot",
    "meta": "meta",
}


def maker_of(model_id: str) -> str | None:
    s = model_id.lower()
    return next((maker for rx, maker in _MAKER_RULES if rx.search(s)), None)


_FAMILY_RE = re.compile(
    r"\b(Claude|gpt-oss|GPT(?:-\d+(?:\.\d+)?)?|Gemini(?: \d+(?:\.\d+)?)?|Grok|GLM|Kimi|Codex|"
    r"Composer|DeepSeek|Opus|Sonnet|Haiku|Fable|Muse|Mistral)\b"
)


def in_family(m: Model, family: str) -> bool:
    """Whether the family a word names ("GPT-5", "Claude", "gpt-oss") holds m."""
    name, mid = m.name, m.id.lower()
    if family == "Claude":
        return m.maker == "anthropic"
    if family in ("Mistral", "DeepSeek"):
        return m.maker == family.lower()
    if family == "gpt-oss":
        return mid.startswith("gpt-oss")
    if family.startswith("GPT"):
        if not mid.startswith("gpt-") or mid.startswith("gpt-oss"):
            return False
        return family == "GPT" or bool(re.match(rf"{re.escape(family)}(?![\d])", name, re.I))
    if family.startswith("Gemini "):
        return bool(re.match(rf"{re.escape(family)}(?![\d])", name, re.I))
    return family.lower() in name.lower() or family.lower() in mid


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    kind: str  # figure | rank | price | promotion | letter | superlative
    claim: str  # the text that makes the claim
    why: str  # what the data says instead


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;])\s+", text) if s.strip()]


def _clauses(sentence: str) -> list[str]:
    return [c for c in re.split(r",|;|—| - |\(|\)", sentence) if c.strip()]


# --- Artificial Analysis figures -------------------------------------------

# (label, benchmarks.json key, scale from the stored fraction to the cited figure)
_FIGURES: tuple[tuple[str, str, float], ...] = (
    (
        r"(?:AA|Artificial Analysis) Intelligence Index(?: of)?\s*(\()?\s*",
        "artificial_analysis_intelligence_index",
        1,
    ),
    (r"\bHLE\s+()", "hle", 100),
    (r"\bSciCode\s+()", "scicode", 100),
    (r"\bTerminal-Bench 2\.1\s+()", "terminalbench_v2_1", 100),
    (r"\bTerminal-Bench 4\.0\s+()", "terminalbench_v4_0", 100),
    (r"\bTerminal-Bench Hard\s+()", "terminalbench_hard", 100),
    (r"\bAA-LCR\s+()", "lcr", 1),
    (r"τ²-bench banking(?: pass_1)?\s+()", "tau_banking", 100),
    (r"\bOutput Speed\s+()", SPEED, 1),
)
# The unit is consumed with the number, so the "(max)" / "(#1)" after it is found.
_FIGURE_RES = tuple(
    (re.compile(label + r"(\d+(?:\.\d+)?)(?:%|\s*tokens/s)?"), key, scale)
    for label, key, scale in _FIGURES
)
_NOTES_RE = re.compile(r"(?:\s*\([^()]*\)){0,2}")
_VARIANT_WORDS = {
    "max",
    "xhigh",
    "high",
    "medium",
    "low",
    "minimal",
    "reasoning",
    "non-reasoning",
    "adaptive",
}
_AA_VARIANT_RE = re.compile(r"\(([^()]+)\)\s*$")


@dataclass(frozen=True)
class Figure:
    start: int  # span of the cited number in the text
    end: int
    key: str
    cited: float
    decimals: int
    current: float | None
    rank_claim: int | None

    @property
    def stale(self) -> bool:
        if self.current is None:
            return False
        if self.key == SPEED:  # throughput moves daily; only a real gap counts
            return abs(self.cited - self.current) > 0.15 * self.current
        return abs(self.cited - self.current) > 10.0**-self.decimals + 1e-9

    def refreshed(self) -> str:
        """The current figure at the cited precision ("" when unmeasured)."""
        return "" if self.current is None else f"{self.current:.{self.decimals}f}"


def current_figure(m: Model, key: str) -> float | None:
    bench = m.bench or {}
    if key == SPEED:
        v = bench.get(SPEED)
        return float(v) if isinstance(v, (int, float)) and v > 0 else None
    v = (bench.get("evaluations") or {}).get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    scale = next(s for _, k, s in _FIGURES if k == key)
    return float(v) * scale


def _same_variant(qualifier: str, m: Model) -> bool:
    """False when the qualifier names an effort variant the catalog does not map."""
    words = set(re.findall(r"[a-z][a-z-]*", qualifier.lower())) & _VARIANT_WORDS
    if not words:
        return True
    variant = _AA_VARIANT_RE.search(str((m.bench or {}).get("aa_name", "")))
    if variant is None:
        return True
    return bool(words & set(re.findall(r"[a-z][a-z-]*", variant.group(1).lower())))


def figures(text: str, m: Model) -> list[Figure]:
    """Every Artificial Analysis figure the text cites for this model."""
    out: list[Figure] = []
    for rx, key, _scale in _FIGURE_RES:
        for hit in rx.finditer(text):
            number = hit.group(2)
            after = text[hit.end() :]
            # Up to two parentheticals follow the number: an effort variant
            # "(max)" and a rank "(#3)", in either order. In "Index (47.0 max)"
            # the variant sits inside the parenthesis the label opened.
            lead = _NOTES_RE.match(after)
            notes = re.findall(r"\(([^()]*)\)", lead.group(0) if lead else "")
            if hit.group(1):
                notes.insert(0, after.split(")", 1)[0])
            ranks = [int(n[1:]) for n in notes if re.fullmatch(r"#\d+", n.strip())]
            if not all(_same_variant(n, m) for n in notes):
                continue
            out.append(
                Figure(
                    start=hit.start(2),
                    end=hit.end(2),
                    key=key,
                    cited=float(number),
                    decimals=len(number.split(".")[1]) if "." in number else 0,
                    current=current_figure(m, key),
                    rank_claim=ranks[0] if ranks else None,
                )
            )
    return out


def _vendor_reported(text: str) -> bool:
    return "reported" in text.lower()


def refresh_figures(text: str, m: Model) -> str:
    """The text with each stale Artificial Analysis figure set to today's."""
    if _vendor_reported(text):
        return text
    for f in sorted(figures(text, m), key=lambda f: -f.start):
        if f.stale:
            text = text[: f.start] + f.refreshed() + text[f.end :]
    return text


def _figure_findings(sentence: str, m: Model, catalog: list[Model]) -> list[Finding]:
    if _vendor_reported(sentence):
        return []
    out: list[Finding] = []
    for f in figures(sentence, m):
        claim = sentence[max(0, f.start - 40) : f.end].strip()
        if f.stale:
            out.append(Finding("figure", claim, f"Artificial Analysis now shows {f.refreshed()}"))
        if f.rank_claim is not None and f.current is not None:
            above = [
                o
                for o in catalog
                if o.id != m.id and (v := current_figure(o, f.key)) is not None and v > f.current
            ]
            if len(above) + 1 > f.rank_claim:
                out.append(
                    Finding(
                        "rank",
                        f"{claim} (#{f.rank_claim})",
                        f"{len(above)} catalog models score higher",
                    )
                )
    return out


# --- Prices and promotions -------------------------------------------------

_PAIR_RE = re.compile(r"\$(\d+(?:\.\d+)?)\s*/\s*\$(\d+(?:\.\d+)?)")
_OUTPUT_RE = re.compile(r"\$(\d+(?:\.\d+)?)/M output")


def _price_findings(text: str, m: Model) -> list[Finding]:
    """A text that quotes prices must quote the model's own somewhere: "(was
    $5/$30 at initial listing)" beside "($4/$20)" is history, not a mistake."""
    out: list[Finding] = []
    if m.input_price is None or m.output_price is None:
        return out

    def same(a: str, b: float) -> bool:
        return abs(float(a) - b) < 0.005

    pairs = _PAIR_RE.findall(text)
    if pairs and not any(same(i, m.input_price) and same(o, m.output_price) for i, o in pairs):
        out.append(
            Finding(
                "price",
                f"${pairs[0][0]}/${pairs[0][1]}",
                f"its price is ${m.input_price:g}/${m.output_price:g}",
            )
        )
    outputs = _OUTPUT_RE.findall(text)
    if outputs and not any(same(o, m.output_price) for o in outputs):
        out.append(
            Finding(
                "price", f"${outputs[0]}/M output", f"its output price is ${m.output_price:g}/M"
            )
        )
    return out


_MONTHS = {
    m: i
    for i, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for m in names
}
_UNTIL_RE = re.compile(
    r"\b(?:through|until|ending|ends)\s+(?:([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})|(\d{4})-(\d{2})-(\d{2}))"
)


def _promotion_findings(text: str, today: dt.date) -> list[Finding]:
    out: list[Finding] = []
    for hit in _UNTIL_RE.finditer(text):
        try:
            if hit.group(4):
                end = dt.date(int(hit.group(4)), int(hit.group(5)), int(hit.group(6)))
            else:
                month = _MONTHS.get(hit.group(1).lower())
                if month is None:
                    continue
                end = dt.date(int(hit.group(3)), month, int(hit.group(2)))
        except ValueError:
            continue
        if end < today:
            out.append(Finding("promotion", hit.group(0), f"{end.isoformat()} has passed"))
    return out


# --- Letters ---------------------------------------------------------------

_CAT = r"(?:coding|planning|agentic|multimodal|long-context|knowledge|speed)"
_TIER_CLAIM_RE = re.compile(
    rf"\b([SABCD])-tier\s+(?:(?:across|in|on|for)\s+)?({_CAT}(?:\s*(?:,|\+|/|and)\s*{_CAT})*)"
)
_SUFFIX_CLAIM_RE = re.compile(rf"\b({_CAT})-([SABCD])\b")
_POSSESSIVE_RE = re.compile(r"\b([\w.\-]+)'s\s+(?:[\w-]+\s+){0,3}$")


def _about_another(clause: str, at: int, m: Model) -> bool:
    """'lacks Gemini's native multimodal-A rating': the letter is Gemini's."""
    owner = _POSSESSIVE_RE.search(clause[max(0, at - 40) : at])
    if owner is None:
        return False
    word = owner.group(1).lower()
    own = {m.maker or "", *re.findall(r"[a-z0-9.\-]+", m.name.lower())}
    return word not in own and _POSSESSIVE_MAKER.get(word) != m.maker


def _letter_findings(clause: str, m: Model) -> list[Finding]:
    claims: list[tuple[int, str, str]] = []
    for hit in _TIER_CLAIM_RE.finditer(clause):
        for cat in re.findall(_CAT, hit.group(2)):
            claims.append((hit.start(), cat, hit.group(1)))
    for hit in _SUFFIX_CLAIM_RE.finditer(clause):
        claims.append((hit.start(), hit.group(1), hit.group(2)))
    out: list[Finding] = []
    for at, cat, letter in claims:
        actual = m.letters.get(cat, "")
        if actual in LETTERS and actual != letter and not _about_another(clause, at, m):
            out.append(Finding("letter", clause.strip(), f"it is rated {actual} for {cat}"))
    return out


# --- Superlatives ----------------------------------------------------------

_SUPERLATIVE_RE = re.compile(
    r"\b(?P<recency>latest|newest|most recent)\b"
    r"|\b(?P<cheap>cheapest|lowest[- ]cost|least expensive)\b"
    r"|\b(?P<pricey>highest[- ]cost|most expensive|priciest)\b"
    r"|\b(?P<best>most capable|most intelligent|smartest|strongest|deepest|broadest|fastest"
    r"|top[- ]ranked|leading|leads|leader|highest|best(?![- ]suited|\s+(?:for|fit|when|used|suited|value))"
    r"|top(?![- ](?:tier|of)))\b",
    re.IGNORECASE,
)
_CATEGORY_WORDS = {
    "coding": r"\bcod(?:e|ing)\b|programming|algorithmic",
    "agentic": r"\bagent|tool[- ](?:use|calling|calls)|terminal|autonomous",
    "planning": r"\bplanning",
    "multimodal": r"multimodal|\bvision|\bimage|\bvideo|\baudio",
    "long-context": r"long[- ]context|\brecall\b|context window",
    "knowledge": r"knowledge|expertise|factual",
    "speed": r"\bspeed|latency|throughput|fastest",
}
_GENERAL_RE = re.compile(r"capable|intelligen|reasoning|\bmodel\b|overall|smartest", re.IGNORECASE)
_TIER_SCOPE_RE = re.compile(
    r"\bthe (low|medium|high|very[- ]high)[- ](?:cost[- ])?tier\b(?![- ]pric)", re.IGNORECASE
)
_MAKER_POSSESSIVE_RE = re.compile(r"\b([\w.]+)'s\b")


def _scope(clause: str, m: Model, catalog: list[Model], *, default_maker: bool) -> list[Model]:
    """The models a superlative in this clause ranges over: narrowed by every
    cue that holds the model itself (its maker's possessive, a family word, a
    cost tier), so a scope never excludes the model it describes."""
    scope = list(catalog)
    narrowed = False
    for word in _MAKER_POSSESSIVE_RE.findall(clause):
        if _POSSESSIVE_MAKER.get(word.lower()) == m.maker and m.maker:
            scope = [o for o in scope if o.maker == m.maker]
            narrowed = True
    for family in _FAMILY_RE.findall(clause):
        if in_family(m, family):
            scope = [o for o in scope if in_family(o, family)]
            narrowed = True
    tier = _TIER_SCOPE_RE.search(clause)
    if tier and tier.group(1).lower().replace(" ", "-") == m.tier_cost:
        scope = [o for o in scope if o.tier_cost == m.tier_cost]
    if default_maker and not narrowed and m.maker:
        scope = [o for o in scope if o.maker == m.maker]
    return scope


def _qualified(subject: str, scope: list[Model]) -> list[Model]:
    """'the lowest-cost S-tier coding model': only models rated S for coding."""
    for hit in _TIER_CLAIM_RE.finditer(subject):
        for cat in re.findall(_CAT, hit.group(2)):
            scope = [o for o in scope if o.letters.get(cat) == hit.group(1)]
    return scope


def _names_another(clause: str, m: Model, catalog: list[Model]) -> bool:
    """'prefer gpt-5.3-codex when latest-generation Codex quality matters': the
    superlative is about the model the clause names. A family use of a name
    ("GPT-5 family") is not a mention."""
    lowered = clause.lower()
    for o in catalog:
        if o.id == m.id:
            continue
        for label in {o.id, o.name.lower()}:
            if re.search(rf"(?<![\w.-]){re.escape(label)}(?![\w.-]|\s+family)", lowered):
                return True
    return False


def _superlative_findings(clause: str, m: Model, catalog: list[Model]) -> list[Finding]:
    hits = list(_SUPERLATIVE_RE.finditer(clause))
    if not hits or _names_another(clause, m, catalog):
        return []
    out: list[Finding] = []
    for n, hit in enumerate(hits):
        end = hits[n + 1].start() if n + 1 < len(hits) else len(clause)
        word = hit.group(0).lower()
        subject = clause[hit.end() : end]
        if word in ("leader", "leads"):
            subject = clause[max(0, hit.start() - 30) : end]
        claim = clause.strip()
        kind = hit.lastgroup
        if kind == "recency":
            if not m.release:
                continue
            newer = [
                o
                for o in _scope(clause, m, catalog, default_maker=True)
                if o.release and o.release > m.release
            ]
            if newer:
                top = max(newer, key=lambda o: o.release or "")
                out.append(
                    Finding(
                        "superlative", claim, f"{top.name} is newer ({top.release} vs {m.release})"
                    )
                )
        elif kind in ("cheap", "pricey"):
            scope = _qualified(subject, _scope(clause, m, catalog, default_maker=False))
            if m not in scope or m.output_price is None or m.blended is None:
                continue
            sign = 1 if kind == "cheap" else -1
            beats = [
                o
                for o in scope
                if o.output_price is not None
                and o.blended is not None
                and sign * (m.output_price - o.output_price) > 0.005
                and sign * (m.blended - o.blended) > 0.005
            ]
            if beats:
                top = min(beats, key=lambda o: sign * (o.output_price or 0))
                out.append(
                    Finding(
                        "superlative",
                        claim,
                        f"{top.name} is {'cheaper' if kind == 'cheap' else 'pricier'} "
                        f"(${top.output_price:g} vs ${m.output_price:g}/M output)",
                    )
                )
        else:
            scope = _scope(clause, m, catalog, default_maker=False)
            cats = [c for c, rx in _CATEGORY_WORDS.items() if re.search(rx, subject, re.IGNORECASE)]
            if word == "fastest":
                cats = ["speed"]
            for cat in cats:
                mine = m.letters.get(cat, "")
                best = min((o.letters.get(cat, "D") for o in scope), key=_letter_rank, default="D")
                if mine in LETTERS and _letter_rank(best) < _letter_rank(mine):
                    top = min(
                        (o for o in scope if o.letters.get(cat) == best),
                        key=lambda o: (-(o.index or 0), o.name),
                    )
                    out.append(
                        Finding(
                            "superlative", claim, f"{top.name} is rated {best} for {cat}, it {mine}"
                        )
                    )
            if not cats and (_GENERAL_RE.search(subject) or _GENERAL_RE.search(word)):
                if m.index is None:
                    continue
                above = [o for o in scope if o.index is not None and o.index > m.index]
                if above:
                    top = max(above, key=lambda o: o.index or 0)
                    out.append(
                        Finding(
                            "superlative",
                            claim,
                            f"{top.name} scores higher on the AA Intelligence Index ({top.index:.1f} vs {m.index:.1f})",
                        )
                    )
    return out


def _letter_rank(letter: str) -> int:
    return LETTERS.index(letter) if letter in LETTERS else len(LETTERS)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def claims(text: str, m: Model, catalog: list[Model], today: dt.date) -> list[Finding]:
    """Every claim in the text that the data contradicts."""
    out = _price_findings(text, m) + _promotion_findings(text, today)
    for sentence in _sentences(text):
        out += _figure_findings(sentence, m, catalog)
        for clause in _clauses(sentence):
            out += _letter_findings(clause, m)
            out += _superlative_findings(clause, m, catalog)
    return out
