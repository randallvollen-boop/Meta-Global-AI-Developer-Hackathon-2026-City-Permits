"""Deterministic candidate generation.

The registry compares a source record with the canonical entities it may
belong to and records the evidence for and against every candidate.  A name, a
shared address or a score is never enough on its own, and no candidate is ever
linked automatically: the proposal is evidence for a steward decision.
"""
# REQUIRES: MDM-02, MDM-03
# Candidates come from declared keys and comparison evidence. Similar names,
# shared addresses and scores never establish an identity on their own, and unit,
# issuer and credential distinctions are preserved as conflicting evidence.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.ingestion.normalization import (
    NormalizedAddress,
    NormalizedName,
    address_building_matches,
    address_unit_conflicts,
    name_token_overlap,
    normalize_address,
    normalize_identifier,
    normalize_name,
)
from acme_city.persistence.models import permit, registry

#: The token overlap above which a name is offered as a weak candidate.
NAME_OVERLAP_THRESHOLD = 0.5

#: The evidence that identifies a party on its own.  A shared address or a
#: similar name is not in this set: neither one establishes an identity.
STRONG_METHODS: frozenset[str] = frozenset(
    {
        "source_reference_exact",
        "credential_exact",
        "name_normalized_exact",
        "alias_normalized_exact",
        "parcel_identifier_exact",
        "address_identifier_exact",
        "address_source_string_exact",
    }
)

#: The weights of the evidence.  They order the candidates; they are not a
#: calibrated probability.
SUPPORTING_WEIGHTS: dict[str, float] = {
    "source_reference_exact": 0.40,
    "credential_exact": 0.30,
    "name_normalized_exact": 0.30,
    "alias_normalized_exact": 0.30,
    "name_token_overlap": 0.10,
    "address_exact": 0.20,
    "legacy_account_same_holder": 0.20,
    "parcel_identifier_exact": 0.40,
    "address_identifier_exact": 0.40,
    "address_source_string_exact": 0.35,
}

CONFLICTING_WEIGHTS: dict[str, float] = {
    "source_reference_mismatch": 0.50,
    "credential_number_conflict": 0.40,
    "credential_issuer_conflict": 0.40,
    "address_unit_conflict": 0.40,
    "name_mismatch": 0.30,
    "parcel_identifier_conflict": 0.40,
    "address_identifier_conflict": 0.40,
}


@dataclass(frozen=True)
class Evidence:
    """One comparison fact about one candidate."""

    field: str
    direction: str
    method: str
    raw_value: Any = None
    normalized_value: Any = None
    source_snapshot_id: str | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the stable dictionary form of the evidence."""
        return {
            "field": self.field,
            "source_snapshot_id": self.source_snapshot_id,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "direction": self.direction,
            "method": self.method,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class Candidate:
    """One canonical entity the source record may belong to."""

    entity_id: str
    entity_type: str
    supporting: tuple[Evidence, ...] = ()
    conflicting: tuple[Evidence, ...] = ()

    @property
    def score(self) -> float:
        """Return the uncalibrated ordering score of the candidate."""
        total = 0.0
        for item in self.supporting:
            total += SUPPORTING_WEIGHTS.get(item.method, 0.1)
        for item in self.conflicting:
            total -= CONFLICTING_WEIGHTS.get(item.method, 0.2)
        return round(max(0.0, min(1.0, total)), 4)


@dataclass(frozen=True)
class CandidateSet:
    """Every candidate the comparison found, with the disposition it implies."""

    entity_type: str
    candidates: tuple[Candidate, ...] = ()
    compared_fields: tuple[str, ...] = ()
    method: str = "deterministic"

    @property
    def disposition(self) -> str:
        """Return the disposition the evidence supports.

        ``no_match`` means nothing was found.  ``supported`` means one
        candidate stands without a contradiction.  ``unresolved`` means a
        steward has to decide.
        """
        if not self.candidates:
            return "no_match"
        if len(self.candidates) > 1:
            return "unresolved"
        only = self.candidates[0]
        if only.conflicting:
            return "unresolved"
        return "supported"

    @property
    def best(self) -> Candidate | None:
        """Return the candidate with the highest ordering score."""
        if not self.candidates:
            return None
        return max(self.candidates, key=lambda candidate: candidate.score)


#: The entity type each dataset proposes against.
DATASET_ENTITY_TARGETS: dict[str, str] = {
    "applicant_profiles": "party",
    "applications_and_permits": "party",
    "business_licensing_register": "party",
    "contractor_register": "party",
    "finance_accounts": "party",
    "parcel_register": "parcel",
    "address_register": "address",
}


def entity_target_for(dataset_key: str, entity_type: str | None = None) -> str:
    """Return the entity type a dataset proposes against."""
    if entity_type:
        return entity_type
    return DATASET_ENTITY_TARGETS.get(dataset_key, "party")


def _party_names(session: Session, party_id: str) -> list[tuple[str, registry.PartyAlias | None]]:
    """Return the display names and aliases of a party."""
    party = session.get(registry.Party, party_id)
    names: list[tuple[str, registry.PartyAlias | None]] = []
    if party is None:
        return names
    names.append((party.display_name, None))
    if party.legal_name and party.legal_name != party.display_name:
        names.append((party.legal_name, None))
    aliases = session.execute(
        select(registry.PartyAlias).where(registry.PartyAlias.party_id == party_id)
    ).scalars().all()
    for alias in aliases:
        names.append((alias.alias_value, alias))
    return names


def _party_credentials(session: Session, party_id: str) -> list[registry.Credential]:
    """Return the credentials a party holds."""
    return list(
        session.execute(
            select(registry.Credential).where(registry.Credential.holder_party_id == party_id)
        ).scalars().all()
    )


def _party_addresses(session: Session, party_id: str) -> list[str]:
    """Return the official address strings known for a party."""
    rows = session.execute(
        select(registry.Address.source_string)
        .join(
            permit.ApplicationSite,
            permit.ApplicationSite.address_id == registry.Address.id,
        )
        .join(
            permit.ApplicationParty,
            permit.ApplicationParty.application_id == permit.ApplicationSite.application_id,
        )
        .where(permit.ApplicationParty.party_id == party_id)
    ).all()
    return sorted({str(row[0]) for row in rows if row[0]})


def _all_parties(session: Session) -> list[registry.Party]:
    """Return every canonical party."""
    return list(
        session.execute(select(registry.Party).order_by(registry.Party.id)).scalars().all()
    )


def _name_comparison(
    payload_names: list[tuple[str, str]],
    candidate_names: list[tuple[str, registry.PartyAlias | None]],
) -> tuple[str, float, str, str] | None:
    """Compare the source names with the candidate names.

    Returns the method, the token overlap, a detail and the compared field, or
    ``None`` when no candidate name was compared.
    """
    best: tuple[str, float, str, str] | None = None
    for payload_field, payload_value in payload_names:
        payload_name: NormalizedName = normalize_name(payload_value)
        if not payload_name.core_tokens:
            continue
        for candidate_value, alias in candidate_names:
            candidate_name: NormalizedName = normalize_name(candidate_value)
            if not candidate_name.core_tokens:
                continue
            if payload_name.core_tokens == candidate_name.core_tokens:
                method = "alias_normalized_exact" if alias is not None else "name_normalized_exact"
                detail = (
                    f"{payload_field} equals the recorded alias"
                    if alias is not None
                    else f"{payload_field} equals the recorded name"
                )
                return method, 1.0, detail, payload_field
            overlap = name_token_overlap(payload_name, candidate_name)
            if best is None or overlap > best[1]:
                detail = (
                    f"{payload_field} shares {overlap:.0%} of its name tokens with the candidate"
                )
                best = ("name_token_overlap", overlap, detail, payload_field)
    if best is None:
        return None
    method, overlap, detail, payload_field = best
    if overlap < NAME_OVERLAP_THRESHOLD:
        return "name_mismatch", overlap, detail, payload_field
    return method, overlap, detail, payload_field


def _address_comparison(
    payload_addresses: list[tuple[str, str]],
    candidate_addresses: list[str],
) -> tuple[str, float, str] | None:
    """Compare the source addresses with the official addresses of a candidate."""
    best: tuple[str, float, str] | None = None
    for payload_field, payload_value in payload_addresses:
        source_address: NormalizedAddress = normalize_address(payload_value)
        if not source_address.building_key:
            continue
        for candidate_value in candidate_addresses:
            candidate_address: NormalizedAddress = normalize_address(candidate_value)
            if not candidate_address.building_key:
                continue
            if not address_building_matches(source_address, candidate_address):
                continue
            if address_unit_conflicts(source_address, candidate_address):
                method = "address_unit_conflict"
                detail = (
                    f"{payload_field} names unit "
                    f"{source_address.unit_number or 'none'} while the official address names "
                    f"unit {candidate_address.unit_number or 'none'}"
                )
                if best is None or best[1] < 0.0:
                    best = (method, 0.0, detail)
                continue
            return (
                "address_exact",
                1.0,
                f"{payload_field} names the official address of the candidate",
            )
    return best


def _party_candidates(
    session: Session, payload: dict[str, Any], source_snapshot_id: str | None
) -> tuple[tuple[Candidate, ...], tuple[str, ...]]:
    """Return the party candidates of a source payload and the compared fields."""
    compared: set[str] = set()
    reference_value: str | None = None
    reference_field: str | None = None
    for field_name in ("party_ref", "holder_ref"):
        raw_value = payload.get(field_name)
        if raw_value:
            reference_value = str(raw_value)
            reference_field = field_name
            compared.add(field_name)
            break

    payload_names: list[tuple[str, str]] = []
    for field_name in ("display_name", "organization_name", "holder_name"):
        raw_value = payload.get(field_name)
        if raw_value:
            payload_names.append((field_name, str(raw_value)))
            compared.add(field_name)

    payload_addresses: list[tuple[str, str]] = []
    for field_name in ("business_address", "submitted_site_text"):
        raw_value = payload.get(field_name)
        if raw_value:
            payload_addresses.append((field_name, str(raw_value)))
            compared.add(field_name)

    credential_values: list[tuple[str, str]] = []
    for field_name in ("license_number", "registration_number"):
        raw_value = payload.get(field_name)
        if raw_value:
            credential_values.append((field_name, str(raw_value)))
            compared.add(field_name)

    legacy_account = payload.get("legacy_account_ref")
    if legacy_account:
        compared.add("legacy_account_ref")

    candidates: list[Candidate] = []
    for party in _all_parties(session):
        supporting: list[Evidence] = []
        conflicting: list[Evidence] = []

        if reference_value is not None and reference_field is not None:
            if reference_value == party.entity_id:
                supporting.append(
                    Evidence(
                        field=reference_field,
                        direction="supporting",
                        method="source_reference_exact",
                        raw_value=reference_value,
                        normalized_value=normalize_identifier(reference_value),
                        source_snapshot_id=source_snapshot_id,
                        detail=(
                            f"{reference_field} names the candidate exactly"
                        ),
                    )
                )
            else:
                conflicting.append(
                    Evidence(
                        field=reference_field,
                        direction="conflicting",
                        method="source_reference_mismatch",
                        raw_value=reference_value,
                        normalized_value=normalize_identifier(reference_value),
                        source_snapshot_id=source_snapshot_id,
                        detail=(
                            f"{reference_field} names another party than the candidate"
                        ),
                    )
                )

        candidate_names = _party_names(session, party.id)
        comparison = _name_comparison(payload_names, candidate_names)
        if comparison is not None:
            method, _, detail, compared_field = comparison
            raw_value = dict(payload_names).get(compared_field)
            evidence = Evidence(
                field=compared_field,
                direction="conflicting" if method == "name_mismatch" else "supporting",
                method=method,
                raw_value=raw_value,
                normalized_value=normalize_name(raw_value).normalized,
                source_snapshot_id=source_snapshot_id,
                detail=(
                    f"{detail}; a similar name never establishes an identity"
                    if method == "name_token_overlap"
                    else detail
                ),
            )
            (conflicting if method == "name_mismatch" else supporting).append(evidence)

        candidate_addresses = _party_addresses(session, party.id)
        address_result = _address_comparison(payload_addresses, candidate_addresses)
        if address_result is not None:
            method, _, detail = address_result
            raw_value = payload_addresses[0][1] if payload_addresses else None
            evidence = Evidence(
                field=payload_addresses[0][0] if payload_addresses else "address",
                direction="supporting" if method == "address_exact" else "conflicting",
                method=method,
                raw_value=raw_value,
                normalized_value=normalize_address(raw_value).normalized,
                source_snapshot_id=source_snapshot_id,
                detail=detail,
            )
            (supporting if method == "address_exact" else conflicting).append(evidence)

        candidate_credentials = _party_credentials(session, party.id)
        for field_name, value in credential_values:
            matching = [
                credential
                for credential in candidate_credentials
                if normalize_identifier(credential.number) == normalize_identifier(value)
            ]
            if matching:
                credential = matching[0]
                supporting.append(
                    Evidence(
                        field=field_name,
                        direction="supporting",
                        method="credential_exact",
                        raw_value=value,
                        normalized_value=normalize_identifier(value),
                        source_snapshot_id=source_snapshot_id,
                        detail=(
                            f"the candidate holds {credential.credential_type} "
                            f"{credential.number} issued by {credential.issuing_authority_id} "
                            f"with status {credential.status}"
                        ),
                    )
                )
            elif candidate_credentials:
                numbers = sorted(
                    credential.number for credential in candidate_credentials
                )
                issuers = sorted(
                    {credential.issuing_authority_id for credential in candidate_credentials}
                )
                conflicting.append(
                    Evidence(
                        field=field_name,
                        direction="conflicting",
                        method="credential_number_conflict",
                        raw_value=value,
                        normalized_value=normalize_identifier(value),
                        source_snapshot_id=source_snapshot_id,
                        detail=(
                            f"the candidate holds {numbers} issued by {issuers}, not {value}"
                        ),
                    )
                )

        if legacy_account:
            legacy_holder = _legacy_account_holder(session, str(legacy_account))
            if legacy_holder is not None:
                holder_comparison = _name_comparison(payload_names, [(legacy_holder, None)])
                if holder_comparison is not None and holder_comparison[1] >= 1.0:
                    supporting.append(
                        Evidence(
                            field="legacy_account_ref",
                            direction="supporting",
                            method="legacy_account_same_holder",
                            raw_value=str(legacy_account),
                            normalized_value=normalize_identifier(str(legacy_account)),
                            source_snapshot_id=source_snapshot_id,
                            detail=(
                                f"the legacy account {legacy_account} names the same holder"
                            ),
                        )
                    )

        if supporting:
            retained = any(item.method in STRONG_METHODS for item in supporting)
            near_miss = any(item.method == "name_token_overlap" for item in supporting)
            if retained or near_miss:
                candidates.append(
                    Candidate(
                        entity_id=party.entity_id,
                        entity_type="party",
                        supporting=tuple(supporting),
                        conflicting=tuple(conflicting),
                    )
                )

    candidates.sort(key=lambda candidate: (-candidate.score, candidate.entity_id))
    return tuple(candidates), tuple(sorted(compared))


def _legacy_account_holder(session: Session, source_account_id: str) -> str | None:
    """Return the holder name a legacy finance account declares."""
    account = session.execute(
        select(registry.FinanceAccount).where(
            registry.FinanceAccount.source_account_id == source_account_id
        )
    ).scalar_one_or_none()
    if account is None:
        return None
    return _finance_account_holder_name(session, account)


def _finance_account_holder_name(
    session: Session, account: registry.FinanceAccount
) -> str | None:
    """Return the holder name a finance account record declares."""
    from acme_city.persistence.models import source

    snapshot = session.execute(
        select(source.SourceSnapshot).where(
            source.SourceSnapshot.source_system_id == account.source_system_id,
            source.SourceSnapshot.source_dataset_id == "finance_accounts",
            source.SourceSnapshot.source_record_id == account.source_account_id,
            source.SourceSnapshot.record_status == "accepted",
        )
    ).scalars().first()
    if snapshot is None or not snapshot.raw_payload:
        return None
    holder = snapshot.raw_payload.get("holder_name")
    return str(holder) if holder else None


def _parcel_candidates(
    session: Session, payload: dict[str, Any], source_snapshot_id: str | None
) -> tuple[tuple[Candidate, ...], tuple[str, ...]]:
    """Return the parcel candidates of a source payload."""
    compared: set[str] = set()
    candidates: list[Candidate] = []
    parcels = session.execute(
        select(registry.Parcel).order_by(registry.Parcel.id)
    ).scalars().all()
    for field_name in ("parcel_number", "submitted_parcel"):
        raw_value = payload.get(field_name)
        if not raw_value:
            continue
        compared.add(field_name)
        for parcel in parcels:
            if normalize_identifier(parcel.source_parcel_number) != normalize_identifier(
                str(raw_value)
            ):
                continue
            candidates.append(
                Candidate(
                    entity_id=parcel.parcel_id,
                    entity_type="parcel",
                    supporting=(
                        Evidence(
                            field=field_name,
                            direction="supporting",
                            method="parcel_identifier_exact",
                            raw_value=str(raw_value),
                            normalized_value=normalize_identifier(str(raw_value)),
                            source_snapshot_id=source_snapshot_id,
                            detail=(
                                f"{field_name} names the official parcel {parcel.parcel_id}"
                            ),
                        ),
                    ),
                )
            )
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.entity_id))
    return tuple(candidates), tuple(sorted(compared))


def _address_candidates(
    session: Session, payload: dict[str, Any], source_snapshot_id: str | None
) -> tuple[tuple[Candidate, ...], tuple[str, ...]]:
    """Return the address candidates of a source payload.

    The official address carries its own identifier and its own address text.
    A source record that repeats the same address text names the same place
    only when the unit matches as well.
    """
    compared: set[str] = set()
    candidates: list[Candidate] = []
    addresses = session.execute(
        select(registry.Address).order_by(registry.Address.id)
    ).scalars().all()
    for field_name in ("address_id", "address_ref"):
        raw_value = payload.get(field_name)
        if not raw_value:
            continue
        compared.add(field_name)
        for address in addresses:
            if normalize_identifier(address.address_id) != normalize_identifier(str(raw_value)):
                continue
            candidates.append(
                Candidate(
                    entity_id=address.address_id,
                    entity_type="address",
                    supporting=(
                        Evidence(
                            field=field_name,
                            direction="supporting",
                            method="address_identifier_exact",
                            raw_value=str(raw_value),
                            normalized_value=normalize_identifier(str(raw_value)),
                            source_snapshot_id=source_snapshot_id,
                            detail=(
                                f"{field_name} names the official address {address.address_id}"
                            ),
                        ),
                    ),
                )
            )
    source_string = payload.get("source_string")
    if source_string:
        compared.add("source_string")
        source_address = normalize_address(str(source_string))
        for address in addresses:
            if not address.source_string:
                continue
            official_address = normalize_address(address.source_string)
            if source_address.building_key != official_address.building_key:
                continue
            if address_unit_conflicts(source_address, official_address):
                continue
            candidates.append(
                Candidate(
                    entity_id=address.address_id,
                    entity_type="address",
                    supporting=(
                        Evidence(
                            field="source_string",
                            direction="supporting",
                            method="address_source_string_exact",
                            raw_value=str(source_string),
                            normalized_value=source_address.normalized,
                            source_snapshot_id=source_snapshot_id,
                            detail=(
                                "source_string names the official address with the same unit"
                            ),
                        ),
                    ),
                )
            )
    unique: dict[str, Candidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.entity_id, candidate)
    ordered = tuple(unique.values())
    ordered = tuple(sorted(ordered, key=lambda candidate: (-candidate.score, candidate.entity_id)))
    return ordered, tuple(sorted(compared))


def generate_candidates(
    session: Session,
    payload: dict[str, Any],
    entity_type: str,
    source_snapshot_id: str | None = None,
) -> CandidateSet:
    """Return the candidates of one source payload.

    Args:
        session: The open session.
        payload: The raw payload of the source record.
        entity_type: The entity family to compare against.
        source_snapshot_id: The snapshot the payload came from, recorded with
            every piece of evidence.

    Returns:
        The candidates, their evidence and the disposition they support.
    """
    if entity_type == "parcel":
        candidates, compared = _parcel_candidates(session, payload, source_snapshot_id)
    elif entity_type == "address":
        candidates, compared = _address_candidates(session, payload, source_snapshot_id)
    else:
        candidates, compared = _party_candidates(session, payload, source_snapshot_id)
    return CandidateSet(
        entity_type=entity_type,
        candidates=candidates,
        compared_fields=compared,
    )


__all__ = [
    "CONFLICTING_WEIGHTS",
    "Candidate",
    "CandidateSet",
    "DATASET_ENTITY_TARGETS",
    "Evidence",
    "NAME_OVERLAP_THRESHOLD",
    "STRONG_METHODS",
    "SUPPORTING_WEIGHTS",
    "entity_target_for",
    "generate_candidates",
]
