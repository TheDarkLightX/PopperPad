from __future__ import annotations

import json
from typing import Any, Mapping

from ..core.imports import ImportTruthMode, TrustPolicy
from ..core.result import Reject
from ..core.values import FrozenDict, JsonValue, freeze_json
from ..core.verifier import verify_ed25519_signature
from ..core.verifier_receipts import (
    AuthenticatedVerifierReceiptV1,
    ReceiptSignatureAlgorithm,
    TruthReceiptBinding,
    VerifierReceiptV1,
    VerifierResult,
    admit_authenticated_verifier_receipt,
    parse_verifier_receipt_object,
    verifier_receipt_root,
    verifier_statement_signing_bytes,
)
from .bundle import LoadedBundle


def _reject(code: str, **details: JsonValue) -> Reject:
    frozen = freeze_json(details)
    assert isinstance(frozen, FrozenDict)
    return Reject(code, frozen)


def _loaded_objects(loaded: LoadedBundle) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for ref, payload in loaded.objects.items():
        parsed = json.loads(payload)
        if type(parsed) is not dict:
            raise TypeError(f"object payload is not an exact object: {ref}")
        result[ref] = parsed
    return result


def _authenticate(
    receipt: VerifierReceiptV1,
    policy: TrustPolicy,
) -> AuthenticatedVerifierReceiptV1 | Reject:
    trusted = {
        signer.key_id: signer for signer in policy.trusted_verifiers
    }.get(receipt.signer_key_id)
    if trusted is None:
        return _reject("UNTRUSTED_VERIFIER", verifier_id=receipt.signer_key_id)
    if (
        trusted.algorithm is not ReceiptSignatureAlgorithm.ED25519
        or receipt.algorithm is not ReceiptSignatureAlgorithm.ED25519
    ):
        return _reject(
            "VERIFIER_ALGORITHM_MISMATCH",
            verifier_id=receipt.signer_key_id,
        )
    if not verify_ed25519_signature(
        public_key=trusted.public_key,
        signature=receipt.signature,
        message=verifier_statement_signing_bytes(receipt.statement),
    ):
        return _reject(
            "INVALID_VERIFIER_SIGNATURE",
            verifier_id=receipt.signer_key_id,
        )
    return AuthenticatedVerifierReceiptV1(
        receipt=receipt,
        receipt_root=verifier_receipt_root(receipt),
    )


def _truth_binding(
    *,
    edge_ref: str,
    edge: Mapping[str, Any],
    evidence_ref: str,
    evidence: Mapping[str, Any],
) -> TruthReceiptBinding | Reject:
    edge_type = edge.get("edge_type")
    if edge_type not in ("supports", "refutes"):
        return _reject("INVALID_TRUTH_EDGE", edge_ref=edge_ref)
    if evidence.get("schema") != "popperpad/evidence/v1":
        return _reject(
            "TRUTH_EVIDENCE_SCHEMA_MISMATCH",
            edge_ref=edge_ref,
            evidence_ref=evidence_ref,
        )
    result = evidence.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "pass":
        return _reject(
            "TRUTH_EVIDENCE_NOT_PASSING",
            edge_ref=edge_ref,
            evidence_ref=evidence_ref,
        )
    claim_ref = edge.get("to_ref")
    subject_refs = evidence.get("subject_refs")
    if (
        type(subject_refs) is not list
        or subject_refs != sorted(set(subject_refs))
        or claim_ref not in subject_refs
    ):
        return _reject(
            "TRUTH_INPUT_ROOTS_MISMATCH",
            edge_ref=edge_ref,
            evidence_ref=evidence_ref,
        )
    edge_context = edge.get("context_ref")
    if edge_context != evidence.get("context_ref"):
        return _reject(
            "TRUTH_CONTEXT_MISMATCH",
            edge_ref=edge_ref,
            evidence_ref=evidence_ref,
        )

    output_roots: list[str] = []
    outputs = evidence.get("outputs", [])
    if type(outputs) is not list:
        return _reject("INVALID_TRUTH_OUTPUTS", evidence_ref=evidence_ref)
    for output in outputs:
        if not isinstance(output, Mapping) or type(output.get("ref")) is not str:
            return _reject("INVALID_TRUTH_OUTPUTS", evidence_ref=evidence_ref)
        output_roots.append(output["ref"])
    for field_name in ("stdout_ref", "stderr_ref"):
        value = evidence.get(field_name)
        if value:
            if type(value) is not str:
                return _reject("INVALID_TRUTH_OUTPUTS", evidence_ref=evidence_ref)
            output_roots.append(value)
    if len(output_roots) != len(set(output_roots)):
        return _reject("DUPLICATE_TRUTH_OUTPUT", evidence_ref=evidence_ref)
    try:
        return TruthReceiptBinding(
            claim_ref=claim_ref,
            context_ref=edge_context,
            recipe_ref=evidence.get("recipe_ref"),
            evidence_ref=evidence_ref,
            edge_ref=edge_ref,
            input_roots=tuple(subject_refs),
            result=VerifierResult(edge_type),
            output_roots=tuple(sorted(output_roots)),
        )
    except (TypeError, ValueError) as exc:
        return _reject(
            "INVALID_TRUTH_BINDING",
            edge_ref=edge_ref,
            reason=str(exc),
        )


def admit_trusted_truth(
    loaded: LoadedBundle,
    policy: TrustPolicy,
) -> tuple[str, ...] | Reject:
    """Authenticate every truth-bearing imported edge or quarantine the import."""

    if policy.truth_mode is ImportTruthMode.QUARANTINED:
        return ()

    objects = _loaded_objects(loaded)
    domain_refs = set(loaded.manifest.object_refs) | set(loaded.manifest.blob_refs)
    receipts_by_binding: dict[
        tuple[str, str],
        list[AuthenticatedVerifierReceiptV1],
    ] = {}
    receipt_object_refs: set[str] = set()
    for object_ref, value in objects.items():
        if value.get("schema") != "popperpad/verifier-receipt/v1":
            continue
        parsed = parse_verifier_receipt_object(value)
        if isinstance(parsed, Reject):
            return parsed
        authenticated = _authenticate(parsed, policy)
        if isinstance(authenticated, Reject):
            return authenticated
        statement = authenticated.receipt.statement
        referenced = {
            statement.claim_ref,
            statement.recipe_ref,
            statement.evidence_ref,
            statement.edge_ref,
            *statement.input_roots,
            *statement.output_roots,
        }
        if statement.context_ref is not None:
            referenced.add(statement.context_ref)
        if not referenced.issubset(domain_refs):
            return _reject(
                "RECEIPT_REF_OUTSIDE_BUNDLE",
                receipt_object_ref=object_ref,
            )
        receipts_by_binding.setdefault(
            (statement.edge_ref, statement.evidence_ref),
            [],
        ).append(authenticated)
        receipt_object_refs.add(object_ref)

    used_receipt_roots: set[str] = set()
    truth_edge_count = 0
    for edge_ref, edge in objects.items():
        if edge.get("schema") != "popperpad/edge/v1":
            continue
        if edge.get("edge_type") not in ("supports", "refutes"):
            continue
        truth_edge_count += 1
        evidence_refs = edge.get("evidence_refs")
        if (
            type(evidence_refs) is not list
            or not evidence_refs
            or evidence_refs != sorted(set(evidence_refs))
        ):
            return _reject("INVALID_TRUTH_EVIDENCE_REFS", edge_ref=edge_ref)
        for evidence_ref in evidence_refs:
            evidence = objects.get(evidence_ref)
            if evidence is None:
                return _reject(
                    "TRUTH_EVIDENCE_OUTSIDE_BUNDLE",
                    edge_ref=edge_ref,
                    evidence_ref=evidence_ref,
                )
            binding = _truth_binding(
                edge_ref=edge_ref,
                edge=edge,
                evidence_ref=evidence_ref,
                evidence=evidence,
            )
            if isinstance(binding, Reject):
                return binding
            candidates = receipts_by_binding.get((edge_ref, evidence_ref), [])
            if len(candidates) != 1:
                return _reject(
                    "VERIFIER_RECEIPT_CARDINALITY",
                    edge_ref=edge_ref,
                    evidence_ref=evidence_ref,
                    found=len(candidates),
                )
            candidate = candidates[0]
            admitted = admit_authenticated_verifier_receipt(
                candidate,
                binding=binding,
                trusted_verifier_ids=tuple(
                    signer.key_id for signer in policy.trusted_verifiers
                ),
                accepted_versions=policy.accept_verifier_versions,
                accepted_policy_hashes=policy.accept_receipt_policy_hashes,
                accepted_toolchain_hashes=policy.accept_toolchain_hashes,
            )
            if isinstance(admitted, Reject):
                return admitted
            used_receipt_roots.add(candidate.receipt_root)

    if receipt_object_refs and len(used_receipt_roots) != len(receipt_object_refs):
        return _reject(
            "UNBOUND_VERIFIER_RECEIPT",
            receipt_objects=len(receipt_object_refs),
            admitted_receipts=len(used_receipt_roots),
        )
    if truth_edge_count and not used_receipt_roots:
        return _reject("MISSING_VERIFIER_RECEIPTS")
    return tuple(sorted(used_receipt_roots))
