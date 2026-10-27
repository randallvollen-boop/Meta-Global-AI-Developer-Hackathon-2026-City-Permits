"""Safe normalization for comparison.

Normalization produces a comparison form beside the raw value.  It never
discards the raw value, never merges two unit distinctions, and never states
that two records describe the same thing: a normalized pair is evidence for a
steward, not a decision.
"""
# REQUIRES: ING-04
# Normalization keeps the raw value, keeps unit boundaries, and never establishes
# authority or identity.

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_WHITESPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^0-9a-z]+")
_DIGITS = re.compile(r"\d+")

#: Legal-form tokens are separated from the comparable name instead of being
#: dropped, because "Cedarline Coffee Roasters LLC" and "Cedarline Coffee
#: Roasters" are the same spelling of a name but a missing legal form is a
#: fact the steward may still want to see.
LEGAL_FORM_TOKENS: frozenset[str] = frozenset(
    {
        "llc",
        "lc",
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "ltd",
        "limited",
        "lp",
        "llp",
        "plc",
        "gmbh",
        "pllc",
        "pc",
    }
)

#: Tokens that describe a unit rather than a street.
UNIT_TOKENS: frozenset[str] = frozenset(
    {"unit", "suite", "ste", "space", "spc", "floor", "fl", "room", "rm", "#"}
)

#: Tokens that describe a street type.
STREET_TYPE_TOKENS: frozenset[str] = frozenset(
    {
        "street",
        "st",
        "road",
        "rd",
        "avenue",
        "ave",
        "av",
        "boulevard",
        "blvd",
        "lane",
        "ln",
        "drive",
        "dr",
        "court",
        "ct",
        "circle",
        "cir",
        "place",
        "pl",
        "terrace",
        "ter",
        "row",
        "way",
        "parkway",
        "pkwy",
        "highway",
        "hwy",
    }
)


@dataclass(frozen=True)
class NormalizedName:
    """A name in comparison form beside the raw name."""

    raw: str
    normalized: str
    tokens: tuple[str, ...] = ()
    core_tokens: tuple[str, ...] = ()
    legal_forms: tuple[str, ...] = ()
    token_set: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class NormalizedAddress:
    """An address in comparison form beside the raw address.

    The unit is kept apart from the street: two addresses that share a
    building and differ in unit are not the same place.
    """

    raw: str
    normalized: str = ""
    street_number: str | None = None
    street_name: str | None = None
    street_type: str | None = None
    unit_type: str | None = None
    unit_number: str | None = None
    municipality: str | None = None
    region: str | None = None
    postcode: str | None = None
    building_key: str = ""
    unit_key: str = ""
    tokens: tuple[str, ...] = ()

    @property
    def has_unit(self) -> bool:
        """Return whether the address carries a unit distinction."""
        return bool(self.unit_number)


def normalize_text(raw: str | None) -> str:
    """Return the comparison form of a free-text value."""
    if raw is None:
        return ""
    folded = unicodedata.normalize("NFKC", str(raw)).casefold()
    return _WHITESPACE.sub(" ", folded).strip()


def normalize_identifier(raw: str | None) -> str:
    """Return the comparison form of an identifier.

    Separators are removed so that ``CR-2026 00188`` and ``cr202600188``
    compare equal, but the raw identifier is never replaced.
    """
    if raw is None:
        return ""
    folded = unicodedata.normalize("NFKC", str(raw)).casefold()
    return _NON_WORD.sub("", folded)


def normalize_email(raw: str | None) -> str:
    """Return the comparison form of an email address."""
    if raw is None:
        return ""
    return unicodedata.normalize("NFKC", str(raw)).casefold().strip()


def normalize_phone(raw: str | None) -> str:
    """Return the comparison form of a telephone number.

    Only the digits survive, so formatting differences do not create a
    different number.  An extension or other non-numeric content is dropped
    rather than silently folded into the number.
    """
    if raw is None:
        return ""
    digits = "".join(_DIGITS.findall(str(raw)))
    return digits


def normalize_name(raw: str | None) -> NormalizedName:
    """Return the comparison form of a person or organization name.

    The legal form is separated instead of dropped, and the token order is
    preserved so that a reordered name is still visibly different.
    """
    text = normalize_text(raw)
    tokens = tuple(token for token in _NON_WORD.sub(" ", text).split() if token)
    legal_forms = tuple(token for token in tokens if token in LEGAL_FORM_TOKENS)
    core_tokens = tuple(token for token in tokens if token not in LEGAL_FORM_TOKENS)
    return NormalizedName(
        raw="" if raw is None else str(raw),
        normalized=" ".join(tokens),
        tokens=tokens,
        core_tokens=core_tokens,
        legal_forms=legal_forms,
        token_set=frozenset(core_tokens),
    )


def _split_unit(tokens: list[str]) -> tuple[list[str], str | None, str | None]:
    """Split the unit tokens away from the street tokens."""
    unit_type: str | None = None
    unit_number: str | None = None
    remainder: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in UNIT_TOKENS:
            unit_type = token
            if index + 1 < len(tokens) and tokens[index + 1] not in UNIT_TOKENS:
                unit_number = tokens[index + 1]
                index += 2
                continue
            index += 1
            continue
        remainder.append(token)
        index += 1
    return remainder, unit_type, unit_number


def normalize_address(raw: str | None) -> NormalizedAddress:
    """Return the comparison form of a postal address.

    The street number, street name, street type, unit and locality stay
    separate so that a unit distinction survives normalization.  The building
    key carries the street only: two addresses in the same building that name
    the unit differently are still the same building.
    """
    text = normalize_text(raw)
    if not text:
        return NormalizedAddress(raw="" if raw is None else str(raw))

    working = text.replace(",", " ")
    working = re.sub(r"#\s*", " # ", working)
    tokens = [token for token in _NON_WORD.sub(" ", working).split() if token]

    street_tokens, unit_type, unit_number = _split_unit(tokens)

    street_number: str | None = None
    if street_tokens and street_tokens[0].isdigit():
        street_number = street_tokens[0]
        street_tokens = street_tokens[1:]

    street_type: str | None = None
    street_name_tokens: list[str] = []
    locality_tokens: list[str] = []
    for index, token in enumerate(street_tokens):
        if street_type is None and token in STREET_TYPE_TOKENS:
            street_type = token
            street_name_tokens = street_tokens[:index]
            locality_tokens = street_tokens[index + 1 :]
            break
    else:
        street_name_tokens = list(street_tokens)

    street_name = " ".join(street_name_tokens) if street_name_tokens else None
    municipality = " ".join(locality_tokens) if locality_tokens else None

    building_key = " ".join(part for part in (street_number, street_name, street_type) if part)
    unit_key = " ".join(part for part in (unit_type, unit_number) if part)

    return NormalizedAddress(
        raw="" if raw is None else str(raw),
        normalized=" ".join(tokens),
        street_number=street_number,
        street_name=street_name,
        street_type=street_type,
        unit_type=unit_type,
        unit_number=unit_number,
        municipality=municipality,
        building_key=building_key,
        unit_key=unit_key,
        tokens=tuple(tokens),
    )


def name_token_overlap(left: NormalizedName, right: NormalizedName) -> float:
    """Return the token overlap of two normalized names.

    The result is an uncalibrated similarity measure.  A high value is a
    reason to look closer; it is never a reason to link two records.
    """
    if not left.token_set or not right.token_set:
        return 0.0
    shared = len(left.token_set & right.token_set)
    return shared / len(left.token_set | right.token_set)


def address_building_matches(left: NormalizedAddress, right: NormalizedAddress) -> bool:
    """Return whether two addresses share the same building."""
    if not left.building_key or not right.building_key:
        return False
    return left.building_key == right.building_key


def address_unit_conflicts(left: NormalizedAddress, right: NormalizedAddress) -> bool:
    """Return whether two addresses share a building but differ in unit.

    The unit number decides, not the word that introduces it: ``Suite 2`` and
    ``Unit 2`` name the same unit, while ``Unit 2`` and ``Unit 5`` do not.
    """
    if not address_building_matches(left, right):
        return False
    return (left.unit_number or None) != (right.unit_number or None)


def address_unit_matches(left: NormalizedAddress, right: NormalizedAddress) -> bool:
    """Return whether two addresses share a building and name the same unit."""
    if not address_building_matches(left, right):
        return False
    return (left.unit_number or None) == (right.unit_number or None)


__all__ = [
    "LEGAL_FORM_TOKENS",
    "NormalizedAddress",
    "NormalizedName",
    "STREET_TYPE_TOKENS",
    "UNIT_TOKENS",
    "address_building_matches",
    "address_unit_conflicts",
    "address_unit_matches",
    "name_token_overlap",
    "normalize_address",
    "normalize_email",
    "normalize_identifier",
    "normalize_name",
    "normalize_phone",
    "normalize_text",
]
