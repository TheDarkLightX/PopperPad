from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from popperpad.adapters import (
    ImportTruthMode,
    SignatureAlgorithm,
    TrustPolicy,
    TrustedSigner,
    bundle_signer_ref,
)
from popperpad.adapters.bundle import (
    Bundle,
    Manifest,
    build_manifest,
    bundle_root,
    export_bundle,
    unsigned_bundle_root,
)
from popperpad.adapters.flow import import_bundle
from popperpad.canonical import canonical_json_bytes, sha256_bytes
from popperpad.core.imports import bundle_signature_message
from popperpad.core.verifier_receipts import (
    ReceiptSignatureAlgorithm,
    TrustedVerifierV1,
    VerifierReceiptV1,
    VerifierResult,
    VerifierStatementV1,
    verifier_receipt_object,
    verifier_key_ref,
    verifier_statement_signing_bytes,
)
from popperpad.pad import PopperPad
from popperpad.refs import Ref


def R(character: str) -> str:
    return "sha256:" + character * 64


_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(33, 65)))
_PUBLIC = _PRIVATE.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
_KEY_ID = bundle_signer_ref(
    algorithm=SignatureAlgorithm.ED25519,
    public_key=_PUBLIC,
)
_SIGNER = TrustedSigner(
    key_id=_KEY_ID,
    algorithm=SignatureAlgorithm.ED25519,
    public_key=_PUBLIC,
)
_VERIFIER_VERSION = "z3/4.13.0"
_VERIFIER_KEY_ID = verifier_key_ref(
    algorithm=ReceiptSignatureAlgorithm.ED25519,
    public_key=_PUBLIC,
)
_VERIFIER = TrustedVerifierV1(
    key_id=_VERIFIER_KEY_ID,
    algorithm=ReceiptSignatureAlgorithm.ED25519,
    public_key=_PUBLIC,
)
_RECEIPT_POLICY_HASH = R("7")
_TOOLCHAIN_HASH = R("8")
_CREATED_AT = "2026-07-25T00:00:00Z"


def _object(value: dict[str, object]) -> tuple[str, bytes]:
    payload = canonical_json_bytes(value)
    return sha256_bytes(payload), payload


def _truth_objects(
    *,
    receipt_result: VerifierResult = VerifierResult.SUPPORTS,
    forge_receipt: bool = False,
) -> tuple[dict[str, bytes], str, str]:
    recipe_ref, recipe_payload = _object(
        {
            "schema": "popperpad/recipe/v1",
            "recipe_id": "trusted-check",
            "argv": ["true"],
            "verdict_on_pass": "support",
            "expect": {},
        }
    )
    hypothesis_ref, hypothesis_payload = _object(
        {
            "schema": "popperpad/hypothesis/v1",
            "hypothesis_id": "trusted-hypothesis",
            "title": "Trusted import",
            "kind": "formal",
            "statement": {"lang": "text", "body": "The check passes."},
            "tags": [],
            "check_recipe_refs": [recipe_ref],
        }
    )
    evidence_ref, evidence_payload = _object(
        {
            "schema": "popperpad/evidence/v1",
            "evidence_kind": "check",
            "recipe_ref": recipe_ref,
            "subject_refs": [hypothesis_ref],
            "result": {"status": "pass", "exit_code": 0},
            "outputs": [],
            "toolchain": {},
        }
    )
    edge_ref, edge_payload = _object(
        {
            "schema": "popperpad/edge/v1",
            "edge_type": "supports",
            "from_ref": evidence_ref,
            "to_ref": hypothesis_ref,
            "evidence_refs": [evidence_ref],
        }
    )
    statement = VerifierStatementV1(
        claim_ref=hypothesis_ref,
        context_ref=None,
        recipe_ref=recipe_ref,
        evidence_ref=evidence_ref,
        edge_ref=edge_ref,
        input_roots=(hypothesis_ref,),
        verifier_id=_VERIFIER_KEY_ID,
        verifier_version=_VERIFIER_VERSION,
        result=receipt_result,
        output_roots=(),
        policy_hash=_RECEIPT_POLICY_HASH,
        toolchain_hash=_TOOLCHAIN_HASH,
    )
    signature = _PRIVATE.sign(verifier_statement_signing_bytes(statement))
    if forge_receipt:
        signature = b"\x00" * 64
    receipt = VerifierReceiptV1(
        statement=statement,
        signer_key_id=_VERIFIER_KEY_ID,
        algorithm=ReceiptSignatureAlgorithm.ED25519,
        signature=signature,
    )
    receipt_ref, receipt_payload = _object(dict(verifier_receipt_object(receipt)))
    return (
        {
            recipe_ref: recipe_payload,
            hypothesis_ref: hypothesis_payload,
            evidence_ref: evidence_payload,
            edge_ref: edge_payload,
            receipt_ref: receipt_payload,
        },
        hypothesis_ref,
        edge_ref,
    )


def _export_signed(
    tmp_path: Path,
    *,
    receipt_result: VerifierResult = VerifierResult.SUPPORTS,
    forge_receipt: bool = False,
) -> tuple[Path, Manifest, str, str]:
    objects, hypothesis_ref, edge_ref = _truth_objects(
        receipt_result=receipt_result,
        forge_receipt=forge_receipt,
    )
    refs = tuple(Ref(ref) for ref in sorted(objects))
    unsigned = Bundle(
        bundle_id="authority",
        object_refs=refs,
        blob_refs=(),
        entry_refs=(Ref(hypothesis_ref),),
    )
    unsigned_manifest = build_manifest(unsigned, created_at=_CREATED_AT)
    signature = _PRIVATE.sign(
        bundle_signature_message(unsigned_bundle_root(unsigned_manifest))
    )
    signed = replace(
        unsigned,
        signatures=(
            {
                "algorithm": "ed25519",
                "key_id": _KEY_ID,
                "signature_hex": signature.hex(),
            },
        ),
    )
    out = tmp_path / "bundle"
    manifest = export_bundle(
        signed,
        out,
        objects=objects,
        blobs={},
        created_at=_CREATED_AT,
    )
    return out, manifest, hypothesis_ref, edge_ref


def _trusted_policy(manifest: Manifest) -> TrustPolicy:
    return TrustPolicy(
        expected_bundle_root=bundle_root(manifest),
        trusted_signers=(_SIGNER,),
        trusted_verifiers=(_VERIFIER,),
        accept_verifier_versions=(_VERIFIER_VERSION,),
        accept_receipt_policy_hashes=(_RECEIPT_POLICY_HASH,),
        accept_toolchain_hashes=(_TOOLCHAIN_HASH,),
        truth_mode=ImportTruthMode.TRUSTED_RECEIPT,
    )


def test_quarantined_truth_stays_inert_until_fresh_local_replay(
    tmp_path: Path,
) -> None:
    bundle_dir, manifest, hypothesis_ref, _edge_ref = _export_signed(tmp_path)
    target_root = tmp_path / "quarantined"
    target = PopperPad(root=target_root)
    target.init()
    report = import_bundle(
        bundle_dir,
        target,
        TrustPolicy(
            trusted_signers=(_SIGNER,),
            expected_bundle_root=bundle_root(manifest),
        ),
    )
    assert report.status == "imported"
    assert target.status(hypothesis_ref, context_ref=None).state == "unknown"

    restarted = PopperPad(root=target_root)
    restarted.init()
    assert restarted.status(hypothesis_ref, context_ref=None).state == "unknown"

    replay = restarted.run_hypothesis(hypothesis_ref, context_ref=None, mode="prove")
    assert replay.verdict == "PASS"
    assert restarted.status(hypothesis_ref, context_ref=None).state == "supported"


def test_trusted_receipt_activates_exact_edge_before_and_after_restart(
    tmp_path: Path,
) -> None:
    bundle_dir, manifest, hypothesis_ref, edge_ref = _export_signed(tmp_path)
    target_root = tmp_path / "trusted"
    target = PopperPad(root=target_root)
    target.init()
    report = import_bundle(bundle_dir, target, _trusted_policy(manifest))
    assert report.status == "imported"
    assert target.status(hypothesis_ref, context_ref=None).state == "supported"
    assert target.status(hypothesis_ref, context_ref=None).supports == (edge_ref,)

    restarted = PopperPad(root=target_root)
    restarted.init()
    assert restarted.status(hypothesis_ref, context_ref=None).state == "supported"


def test_forged_or_replayed_verifier_receipt_commits_nothing(tmp_path: Path) -> None:
    for name, kwargs, expected in (
        ("forged", {"forge_receipt": True}, "INVALID_VERIFIER_SIGNATURE"),
        (
            "replayed",
            {"receipt_result": VerifierResult.REFUTES},
            "REPLAY_BINDING_MISMATCH",
        ),
    ):
        bundle_dir, manifest, _hypothesis_ref, _edge_ref = _export_signed(
            tmp_path / name,
            **kwargs,
        )
        target = PopperPad(root=tmp_path / f"{name}-target")
        target.init()
        report = import_bundle(bundle_dir, target, _trusted_policy(manifest))
        assert report.status == "rejected"
        assert expected in next(
            check.detail
            for check in report.checks
            if check.name == "verifier_receipts"
        )
        assert target.log.stats() == {"event_count": 0, "head": ""}


def test_import_publication_failure_has_no_partial_authority(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle_dir, manifest, _hypothesis_ref, _edge_ref = _export_signed(tmp_path)
    target = PopperPad(root=tmp_path / "failed-target")
    target.init()

    def fail_append(_record: object, *, expected_head: str) -> object:
        raise OSError(f"injected append failure at {expected_head!r}")

    monkeypatch.setattr(target.log, "append_prepared", fail_append)
    report = import_bundle(bundle_dir, target, _trusted_policy(manifest))
    assert report.status == "rejected"
    assert target.log.stats() == {"event_count": 0, "head": ""}
    assert list(target.log.iter_records()) == []
