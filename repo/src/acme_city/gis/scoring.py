"""Deterministic address normalisation and scoring for the simulated locator.

The scoring is a transparent rule list, not a model.  Every penalty is named,
so a clerk (or a test) can see why a candidate scored what it scored.  The
same query against the same address table always returns the same candidates in
the same order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Street type words, written out in full, in the ACME street names.
STREET_TYPES: frozenset[str] = frozenset(
    {
        "street", "road", "drive", "lane", "avenue", "row", "way", "court", "place",
        "circle", "boulevard", "terrace", "parkway", "highway", "trail", "alley",
    }
)

#: Abbreviations a person types, and what they mean.
ABBREVIATIONS: dict[str, str] = {
    "st": "street", "str": "street", "rd": "road", "dr": "drive", "drv": "drive",
    "ln": "lane", "ave": "avenue", "av": "avenue", "ct": "court", "crt": "court",
    "pl": "place", "cir": "circle", "blvd": "boulevard", "ter": "terrace",
    "terr": "terrace", "pkwy": "parkway", "hwy": "highway", "trl": "trail",
    "rdg": "ridge", "crk": "creek", "hts": "heights", "mt": "mount",
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
}

#: Unit designators; all of them mean "unit".
UNIT_WORDS: frozenset[str] = frozenset(
    {"unit", "suite", "ste", "apt", "apartment", "fl", "floor", "rm", "room"}
)

#: The fictional municipality and region of every address.
MUNICIPALITY_TOKENS: tuple[str, ...] = ("acme", "city")
REGION_TOKEN = "ac"

#: One penalty per edit in the street name, capped.
EDIT_PENALTY = 4
EDIT_PENALTY_CAP = 40
NUMBER_MISMATCH_PENALTY = 45
MISSING_NUMBER_PENALTY = 50
MISSING_TYPE_PENALTY = 8
WRONG_TYPE_PENALTY = 12
QUERY_UNIT_MISSING_FROM_ADDRESS = 15
ADDRESS_UNIT_NOT_IN_QUERY = 12
UNIT_MISMATCH_PENALTY = 20
POSTCODE_MISMATCH_PENALTY = 10
MUNICIPALITY_MISMATCH_PENALTY = 10

#: Candidates below this score are never returned.
DEFAULT_MIN_SCORE = 60


@dataclass(frozen=True)
class ParsedAddress:
    """An address split into the parts the scorer compares."""

    number: str = ""
    core: tuple[str, ...] = ()
    street_type: str = ""
    unit: str = ""
    postcode: str = ""
    municipality_given: bool = False
    municipality_ok: bool = True

    @property
    def street(self) -> str:
        return " ".join(self.core)


@dataclass
class Scored:
    """A candidate with its score and the reasons for it."""

    address_id: str
    score: int
    reasons: list[str] = field(default_factory=list)


def _tokens(text: str) -> list[str]:
    cleaned = text.lower().replace("#", " unit ")
    cleaned = re.sub(r"[.’']", "", cleaned)
    cleaned = re.sub(r"[,;/()]", " ", cleaned)
    return [token for token in cleaned.split() if token]


def parse_address(text: str) -> ParsedAddress:
    """Parse free address text into number, street, type, unit and postcode."""
    tokens = _tokens(text)
    postcode = ""
    kept: list[str] = []
    for index, token in enumerate(tokens):
        bare = token.replace("-", "")
        if index > 0 and (re.fullmatch(r"acm-?\d{5}", token) or re.fullmatch(r"\d{5}", token)):
            postcode = bare[-5:]
            continue
        kept.append(token)
    tokens = kept

    municipality_given = False
    municipality_ok = True
    if len(tokens) > 3 and tokens[-1] == REGION_TOKEN:
        tokens = tokens[:-1]
    if len(tokens) >= 2 and tuple(tokens[-2:]) == MUNICIPALITY_TOKENS:
        municipality_given = True
        tokens = tokens[:-2]
    elif tokens and tokens[-1] == "acme":
        municipality_given = True
        tokens = tokens[:-1]
    elif len(tokens) >= 3 and tokens[-1] == "city" and tokens[-2] not in STREET_TYPES:
        # Another city named after the street: "412 Maple Ridge Drive, Otherton City".
        municipality_given = True
        municipality_ok = False
        tokens = tokens[:-2]

    unit = ""
    rest: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in UNIT_WORDS:
            index += 1
            while index < len(tokens) and tokens[index] in UNIT_WORDS:
                index += 1  # "apt #4b" carries two designators
            follower = tokens[index] if index < len(tokens) else ""
            if follower and re.fullmatch(r"[a-z0-9-]+", follower) and follower not in STREET_TYPES:
                unit = follower
                index += 1
            continue  # a designator without a value names no unit
        rest.append(token)
        index += 1

    number = ""
    if rest and re.fullmatch(r"\d+[a-z]?", rest[0]):
        number = rest.pop(0)
    expanded = [ABBREVIATIONS.get(token, token) for token in rest]
    street_type = ""
    if expanded and expanded[-1] in STREET_TYPES:
        street_type = expanded.pop()
    return ParsedAddress(
        number=number,
        core=tuple(expanded),
        street_type=street_type,
        unit=unit,
        postcode=postcode,
        municipality_given=municipality_given,
        municipality_ok=municipality_ok,
    )


def parse_components(
    *,
    number: str | None,
    street_name: str | None,
    unit: str | None,
    postcode: str | None,
) -> ParsedAddress:
    """Parse an official address row (its street name carries its type)."""
    street = parse_address(f"{number or ''} {street_name or ''}")
    return ParsedAddress(
        number=(number or "").strip().lower(),
        core=street.core,
        street_type=street.street_type,
        unit=(unit or "").strip().lower(),
        postcode=(postcode or "").replace("-", "")[-5:],
    )


def edit_distance(left: str, right: str) -> int:
    """Return the optimal-string-alignment distance (a swap costs one edit)."""
    rows = len(left) + 1
    cols = len(right) + 1
    table = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        table[i][0] = i
    for j in range(cols):
        table[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if left[i - 1] == right[j - 1] else 1
            table[i][j] = min(
                table[i - 1][j] + 1,
                table[i][j - 1] + 1,
                table[i - 1][j - 1] + cost,
            )
            if i > 1 and j > 1 and left[i - 1] == right[j - 2] and left[i - 2] == right[j - 1]:
                table[i][j] = min(table[i][j], table[i - 2][j - 2] + 1)
    return table[-1][-1]


def score_candidate(query: ParsedAddress, official: ParsedAddress) -> tuple[int, list[str]]:
    """Return the score (0 to 100) of one official address and why."""
    score = 100
    reasons: list[str] = []

    if not query.number:
        score -= MISSING_NUMBER_PENALTY
        reasons.append("no house number given")
    elif query.number != official.number:
        score -= NUMBER_MISMATCH_PENALTY
        reasons.append(f"house number {query.number} differs from {official.number}")

    distance = edit_distance(query.street, official.street)
    allowed = max(3, len(official.street) // 3)
    if distance > allowed:
        return 0, [f"street name {query.street!r} is too far from {official.street!r}"]
    if distance:
        penalty = min(EDIT_PENALTY_CAP, distance * EDIT_PENALTY)
        score -= penalty
        reasons.append(f"street name needed {distance} edit(s)")

    if not query.street_type:
        score -= MISSING_TYPE_PENALTY
        reasons.append("no street type given")
    elif query.street_type != official.street_type:
        score -= WRONG_TYPE_PENALTY
        reasons.append(f"street type {query.street_type} differs from {official.street_type}")

    if query.unit and official.unit:
        if query.unit != official.unit:
            score -= UNIT_MISMATCH_PENALTY
            reasons.append(f"unit {query.unit} differs from {official.unit}")
    elif query.unit and not official.unit:
        score -= QUERY_UNIT_MISSING_FROM_ADDRESS
        reasons.append("the address has no unit")
    elif official.unit and not query.unit:
        score -= ADDRESS_UNIT_NOT_IN_QUERY
        reasons.append("no unit given for an address with units")

    if query.postcode and official.postcode and query.postcode != official.postcode:
        score -= POSTCODE_MISMATCH_PENALTY
        reasons.append("postcode differs")
    if query.municipality_given and not query.municipality_ok:
        score -= MUNICIPALITY_MISMATCH_PENALTY
        reasons.append("municipality differs")

    return max(0, score), reasons


def prefix_match(query_text: str, official_text: str) -> bool:
    """Return whether every typed word starts a word of the official address."""
    typed = [ABBREVIATIONS.get(token, token) for token in _tokens(query_text)]
    official = [ABBREVIATIONS.get(token, token) for token in _tokens(official_text)]
    if not typed:
        return False
    cursor = 0
    for word in typed:
        found = False
        while cursor < len(official):
            if official[cursor].startswith(word):
                found = True
                cursor += 1
                break
            cursor += 1
        if not found:
            return False
    return True


__all__ = [
    "DEFAULT_MIN_SCORE",
    "ParsedAddress",
    "Scored",
    "edit_distance",
    "parse_address",
    "parse_components",
    "prefix_match",
    "score_candidate",
]
