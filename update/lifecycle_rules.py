"""The rules a model joins or leaves the catalog by, shared by the code that
writes the change and the gate that admits it.

update/dispose_discoveries.py adds a model a provider's own page prices, and
update/supersede.py tags and retires one a successor beats; both write fixed
text. update/automation_integrity.py rebuilds that text from these same
functions and admits a refresh only when its new and retired models match it,
so a new ``<model>`` carries nothing but validated values: an id and a name in
a narrow alphabet, prices, letters, a jurisdiction and a fixed pricing note.
Prose fields start empty and update/model_prose.py writes them from data.

This module is a reviewed validator (scripts/security_catalog.py
``VALIDATOR_FILES``): changing it needs a baseline admission.
"""

from __future__ import annotations

import datetime as dt
import re

PROVIDER_LABEL: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
    "xai": "xAI",
    "deepseek": "DeepSeek",
    "mistral": "Mistral",
    "zai": "z.ai",
    "groq": "Groq",
}
CATEGORIES = ("coding", "planning", "agentic", "multimodal", "long-context", "knowledge", "speed")
LETTERS = frozenset({"S", "A", "B", "C", "D"})

# Written at the end of an element, just before "/>": the day a model joined
# (update/stamp_added.py) and its lifecycle tags (update/supersede.py).
TAG_FIELDS = ("superseded-by", "superseded-on", "retired-on")
TRAILING_FIELDS = ("added-on", *TAG_FIELDS)
DATE_FIELDS = frozenset({"added-on", "superseded-on", "retired-on"})
TAG_ATTR_RE = re.compile(r'\s+(?:superseded-by|superseded-on|retired-on)="[^"]*"')

ID_RE = re.compile(r"[a-z0-9][a-z0-9.\-]{1,47}")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .\-]{0,39}")
NAME_MAX_WORDS = 5

# Decline reasons the discovery lane writes by rule (update/discovery.py,
# update/dispose_discoveries.py). A line with any other reason is the curation
# pass's own and waits for review.
NO_PRICE = "no price on the provider page; re-checked each run"
ONE_SOURCE = "named by one source only; re-checked each run"
SPECIALIZED = (
    "an image, audio, video, embedding, robotics or computer-use model; "
    "the catalog rates general text models"
)
NEW_SERIES = "a new series; new series join through the curation pass, which saw it with its price"
ALIAS_RE = re.compile(r"the provider page's name for `(?P<id>[a-z0-9][a-z0-9.\-]{1,47})`")
RULE_REASONS = frozenset({NO_PRICE, ONE_SOURCE, SPECIALIZED, NEW_SERIES})

DECLINED_HEADING = "## Declined Models (discovery lane)"
DECLINED_LINE_RE = re.compile(
    r"^- (?P<provider>[a-z0-9.-]+)/(?P<slug>\S(?:.*?\S)?) — (?P<reason>.+?) "
    r"\(declined (?P<date>\d{4}-\d{2}-\d{2})\)\s*$"
)


def alias_reason(model_id: str) -> str:
    return f"the provider page's name for `{model_id}`, which the catalog carries"


def pricing_note(provider: str) -> str:
    label = PROVIDER_LABEL.get(provider, provider)
    return f"Provider-direct {label} API per-token pricing (not via the Cursor pool)"


PRICING_NOTES = frozenset(pricing_note(p) for p in PROVIDER_LABEL)


def money(value: float) -> str:
    return f"${value:.2f}"


def model_element(
    model_id: str,
    name: str,
    input_price: str,
    output_price: str,
    jurisdiction: str,
    tiers: dict[str, str],
    note: str,
) -> str:
    """A new ``<model>`` as the discovery lane writes it: prices as written
    (``$8.00``), every letter, and empty prose for update/model_prose.py."""
    t = {c: tiers.get(c, "B") for c in CATEGORIES}
    return (
        f'      <model id="{model_id}" name="{name}"\n'
        f'             input-price-per-1m="{input_price}" output-price-per-1m="{output_price}"\n'
        f'             jurisdiction="{jurisdiction}"\n'
        f'             tier-coding="{t["coding"]}" tier-planning="{t["planning"]}" tier-agentic="{t["agentic"]}"\n'
        f'             tier-multimodal="{t["multimodal"]}" tier-long-context="{t["long-context"]}" tier-knowledge="{t["knowledge"]}"\n'
        f'             tier-speed="{t["speed"]}"\n'
        f'             headline-benchmarks=""\n'
        f'             pricing-notes="{note}"\n'
        f'             best-for="" />'
    )


def append_trailing(element: str, attrs: list[tuple[str, str]]) -> str:
    """``element`` with ``attrs`` written at its end, just before "/>", the way
    update/stamp_added.py and update/supersede.py write them."""
    if not attrs:
        return element
    close = element.rstrip().rfind("/>")
    written = " ".join(f'{key}="{value}"' for key, value in attrs)
    return f"{element[:close].rstrip()} {written}{element[close:]}"


def valid_id(value: str) -> bool:
    return bool(ID_RE.fullmatch(value))


def valid_name(value: str) -> bool:
    return bool(NAME_RE.fullmatch(value)) and len(value.split()) <= NAME_MAX_WORDS


def valid_date(value: str) -> bool:
    try:
        return dt.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False
