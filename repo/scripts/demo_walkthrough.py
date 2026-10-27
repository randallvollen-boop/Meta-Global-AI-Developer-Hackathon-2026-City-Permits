#!/usr/bin/env python3
"""Run the fictional D01 permit chain through the public loopback API."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = REPO_ROOT / "fixtures" / "documents" / "SYN-APP-001-application-v1.txt"
REPLAY_FIXTURE = REPO_ROOT / "fixtures" / "replay" / "extraction-success.json"
APPLICATION_ID = "app_synth_001"
LINKS = (
    ("erp_finance", "business_licensing_register", "ERP-BL-00412"),
    ("permitting", "applicant_profiles", "PER-AP-0003"),
    ("erp_finance", "finance_accounts", "ERP-ACC-77120-LEG"),
    ("permitting", "contractor_register", "PER-CR-00188"),
)


class WalkthroughFailure(RuntimeError):
    """A public API step did not produce the required result."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8266")
    parser.add_argument("--mode", choices=("live", "replay"), required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument(
        "--stop-after",
        choices=("muse", "ready-for-review", "issued"),
        default="issued",
    )
    parser.add_argument("--timeout", type=float, default=45.0)
    return parser.parse_args(argv)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def checked(response: httpx.Response, label: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as error:
        evidence.append({"step": label, "status_code": response.status_code, "status": "failed"})
        raise WalkthroughFailure(f"{label} returned a non-JSON response") from error
    if response.status_code != 200:
        code = body.get("code") if isinstance(body, dict) else None
        message = body.get("message") if isinstance(body, dict) else None
        detail = None
        if isinstance(body, dict):
            detail = body.get("details") or body.get("detail")
            if detail is None:
                detail = {key: value for key, value in body.items() if key not in {"code", "message"}}
        evidence.append(
            {
                "step": label,
                "status_code": response.status_code,
                "status": "failed",
                "code": code,
                "detail": detail,
            }
        )
        raise WalkthroughFailure(
            f"{label} failed ({response.status_code}, {code}): {message}; detail={detail}"
        )
    evidence.append({"step": label, "status_code": 200, "status": "passed"})
    if not isinstance(body, dict):
        raise WalkthroughFailure(f"{label} returned an unexpected response shape")
    return body


def select_actor(client: httpx.Client, actor_id: str, evidence: list[dict[str, Any]]) -> None:
    body = checked(
        client.post("/api/session/select", json={"actor_id": actor_id}),
        f"select {actor_id}",
        evidence,
    )
    if body.get("actor_id") != actor_id:
        raise WalkthroughFailure(f"the server did not establish {actor_id}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = datetime.now(UTC)
    steps: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "kind": "acme_city_demo_walkthrough",
        "mode": args.mode,
        "status": "running",
        "application_id": APPLICATION_ID,
        "started_at": started.isoformat(),
        "base_url": args.base_url,
        "steps": steps,
        "model_run": {},
        "records": {},
    }
    with httpx.Client(base_url=args.base_url, timeout=args.timeout, follow_redirects=False) as client:
        health = checked(client.get("/healthz"), "health", steps)
        if health.get("status") != "ok":
            raise WalkthroughFailure("the application database is not healthy")

        select_actor(client, "persona_data_steward", steps)
        application = checked(
            client.get(f"/api/permits/applications/{APPLICATION_ID}"),
            "read submitted application",
            steps,
        )
        revision_payload = {
            "application_id": APPLICATION_ID,
            "facts": application["snapshot"],
            "parties": application.get("parties") or None,
            "site": (
                None
                if application.get("site") is None
                else {
                    "parcel_id": application["site"].get("parcel_id"),
                    "address_id": application["site"].get("address_id"),
                    "address_text": application["site"].get("submitted_address_text"),
                }
            ),
            "reason": "Applicant materials received and recorded as a versioned submission.",
            "expected_version": application["application_version"],
        }
        revision = checked(
            client.post(
                f"/api/permits/applications/{APPLICATION_ID}/revisions",
                json=revision_payload,
            ),
            "record applicant submission revision",
            steps,
        )
        result["records"]["revision_id"] = revision["revision_id"]

        content = DOCUMENT.read_bytes()
        document = checked(
            client.post(
                f"/api/permits/applications/{APPLICATION_ID}/documents",
                data={"document_type": "construction_plans"},
                files={"file": (DOCUMENT.name, content, "text/plain")},
            ),
            "store submitted document",
            steps,
        )
        result["records"]["document_id"] = document["document_id"]
        result["records"]["document_hash"] = document["content_hash"]

        muse_payload: dict[str, Any] = {
            "task": "extraction",
            "mode": args.mode,
            "application_id": APPLICATION_ID,
            "document_ids": [document["document_id"]],
        }
        if args.mode == "replay":
            fixture = json.loads(REPLAY_FIXTURE.read_text(encoding="utf-8"))
            muse_payload.update(
                {
                    "replay_fixture": REPLAY_FIXTURE.name,
                    "replay_of_run_id": fixture["source_run_id"],
                }
            )
        muse = checked(client.post("/api/muse/run", json=muse_payload), "run Muse extraction", steps)
        result["model_run"] = {
            "run_id": muse.get("run_id"),
            "mode": muse.get("mode"),
            "status": muse.get("status"),
            "provider": muse.get("provider"),
            "model": muse.get("model"),
            "prompt_version": muse.get("prompt_version"),
            "schema_version": muse.get("schema_version"),
            "response_id": muse.get("response_id"),
            "response_status": muse.get("response_status"),
            "latency_ms": muse.get("latency_ms"),
            "error": muse.get("error"),
        }
        if muse.get("status") != "succeeded":
            raise WalkthroughFailure(
                f"Muse extraction was recorded as {muse.get('status')}",
                details={"model_run": result["model_run"], "steps": steps},
            )
        if args.mode == "live" and muse.get("mode") != "live":
            raise WalkthroughFailure("a non-live model run cannot satisfy live evidence")
        if args.stop_after == "muse":
            result["status"] = "passed"
            return result

        crosswalk_ids: list[str] = []
        for source_system_id, dataset_key, source_record_id in LINKS:
            proposal = checked(
                client.post(
                    "/api/registry/proposals",
                    json={
                        "source_system_id": source_system_id,
                        "dataset_key": dataset_key,
                        "source_record_id": source_record_id,
                        "scenario_id": "D01",
                    },
                ),
                f"propose link {source_record_id}",
                steps,
            )
            entity_id = proposal.get("entity_id")
            if not entity_id:
                raise WalkthroughFailure(f"no candidate was proposed for {source_record_id}")
            decision = checked(
                client.post(
                    "/api/registry/decisions",
                    json={
                        "source_system_id": source_system_id,
                        "dataset_key": dataset_key,
                        "source_record_id": source_record_id,
                        "entity_id": entity_id,
                        "decision": "approve",
                        "reason": "The data steward compared the source evidence with the canonical record.",
                        "evidence": [
                            {
                                "field": "source_record_id",
                                "value": source_record_id,
                                "note": "Synthetic D01 evidence was reviewed.",
                            }
                        ],
                        "scenario_id": "D01",
                    },
                ),
                f"approve link {source_record_id}",
                steps,
            )
            value = decision.get("value") or decision
            crosswalk_ids.append(value["crosswalk_id"])
        result["records"]["crosswalk_ids"] = crosswalk_ids
        if args.stop_after == "ready-for-review":
            result["status"] = "passed"
            return result

        select_actor(client, "persona_permit_reviewer", steps)
        evaluation = checked(
            client.post(f"/api/permits/applications/{APPLICATION_ID}/evaluate"),
            "evaluate deterministic rules",
            steps,
        )
        application = checked(
            client.get(f"/api/permits/applications/{APPLICATION_ID}"),
            "read evaluated application",
            steps,
        )
        decision = checked(
            client.post(
                f"/api/permits/applications/{APPLICATION_ID}/decisions",
                json={
                    "outcome": "approved",
                    "reason": "All deterministic checks passed for the fictional demonstration.",
                    "expected_application_version": application["application_version"],
                    "expected_evaluation_version": evaluation["version"],
                },
            ),
            "record reviewer approval",
            steps,
        )
        decision_value = decision.get("value") or decision
        result["records"]["evaluation_id"] = evaluation["evaluation_id"]
        result["records"]["decision_id"] = decision_value["decision_id"]

        select_actor(client, "persona_city_administrator", steps)
        assessment = checked(
            client.post("/api/finance/assessments", json={"application_id": APPLICATION_ID}),
            "create assessment",
            steps,
        )
        allocation = checked(
            client.post(
                "/api/finance/allocations",
                json={
                    "payment_id": "payment_d01_settled",
                    "assessment_id": assessment["assessment_id"],
                    "amount": "150.00",
                    "idempotency_key": "alloc:walkthrough:d01",
                },
            ),
            "allocate settled payment",
            steps,
        )
        reconciliation = checked(
            client.post(
                "/api/finance/reconciliations",
                json={
                    "assessment_id": assessment["assessment_id"],
                    "payment_ids": ["payment_d01_settled"],
                },
            ),
            "reconcile assessment",
            steps,
        )
        if reconciliation.get("status") != "exact":
            raise WalkthroughFailure("the D01 assessment did not reconcile exactly")
        result["records"]["assessment_id"] = assessment["assessment_id"]
        result["records"]["allocation_id"] = allocation["allocation_id"]
        result["records"]["reconciliation_status"] = reconciliation["status"]

        select_actor(client, "persona_permit_reviewer", steps)
        application = checked(
            client.get(f"/api/permits/applications/{APPLICATION_ID}"),
            "read approved application",
            steps,
        )
        issue_payload = {
            "decision_id": decision_value["decision_id"],
            "expected_application_version": application["application_version"],
            "expected_decision_version": decision_value["version"],
            "command_key": "issue:walkthrough:d01",
            "reason": "Separate authorized issuance after exact reconciliation.",
        }
        issued = checked(
            client.post(f"/api/permits/applications/{APPLICATION_ID}/issue", json=issue_payload),
            "issue simulated permit",
            steps,
        )
        retry = checked(
            client.post(f"/api/permits/applications/{APPLICATION_ID}/issue", json=issue_payload),
            "retry issuance after simulated response loss",
            steps,
        )
        first_value = issued.get("value") or issued
        retry_value = retry.get("value") or retry
        identity = ("permit_id", "permit_number", "artifact_hash")
        if any(first_value.get(key) != retry_value.get(key) for key in identity):
            raise WalkthroughFailure("the issuance retry returned a different permit artifact")
        result["records"].update({key: first_value.get(key) for key in identity})

    result["status"] = "passed"
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    evidence_path = args.evidence_dir / "demo-walkthrough.json"
    try:
        result = run(args)
        result["completed_at"] = datetime.now(UTC).isoformat()
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
        result["record_hash"] = hashlib.sha256(encoded).hexdigest()
        atomic_json(evidence_path, result)
        print(f"walkthrough passed: {evidence_path}")
        return 0
    except (WalkthroughFailure, httpx.HTTPError, OSError, ValueError, KeyError) as error:
        failure = {
            "kind": "acme_city_demo_walkthrough",
            "mode": args.mode,
            "status": "failed",
            "application_id": APPLICATION_ID,
            "completed_at": datetime.now(UTC).isoformat(),
            "failure": str(error),
        }
        if isinstance(error, WalkthroughFailure):
            failure.update(error.details)
        atomic_json(evidence_path, failure)
        print(f"walkthrough failed: {error}", file=sys.stderr)
        print(f"failure evidence: {evidence_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
