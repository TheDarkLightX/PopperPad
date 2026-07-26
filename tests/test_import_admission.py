from __future__ import annotations

from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from popperpad.adapters.import_auth import authenticate_bundle_signatures
from popperpad.core.imports import (
    AuthenticatedBundleSignatures,
    BundleSignature,
    ImportTruthMode,
    SignatureAlgorithm,
    TrustPolicy,
    TrustedSigner,
    VerifiedImportProvenance,
    admit_bundle_import,
    bundle_signature_message,
    bundle_signer_ref,
)
from popperpad.core.result import Accept, Reject
from popperpad.core.values import is_deeply_immutable
from popperpad.core.verifier_receipts import (
    AuthenticatedVerifierReceiptV1,
    ReceiptSignatureAlgorithm,
    TruthReceiptBinding,
    TrustedVerifierV1,
    VerifierReceiptV1,
    VerifierResult,
    VerifierStatementV1,
    admit_authenticated_verifier_receipt,
    parse_verifier_receipt_object,
    verifier_receipt_object,
    verifier_key_ref,
    verifier_receipt_root,
    verifier_statement_signing_bytes,
)


def R(character: str) -> str:
    return "sha256:" + character * 64


_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
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

_VERIFIER_KEY_ID = verifier_key_ref(
    algorithm=ReceiptSignatureAlgorithm.ED25519,
    public_key=_PUBLIC,
)
_VERIFIER = TrustedVerifierV1(
    key_id=_VERIFIER_KEY_ID,
    algorithm=ReceiptSignatureAlgorithm.ED25519,
    public_key=_PUBLIC,
)


def _bundle_signature(
    unsigned_root: str,
    *,
    private: Ed25519PrivateKey = _PRIVATE,
) -> BundleSignature:
    return BundleSignature(
        key_id=_KEY_ID,
        algorithm=SignatureAlgorithm.ED25519,
        signature=private.sign(bundle_signature_message(unsigned_root)),
    )


def _policy(**overrides: object) -> TrustPolicy:
    values: dict[str, object] = {
        "expected_bundle_root": R("a"),
        "trusted_signers": (_SIGNER,),
    }
    values.update(overrides)
    return TrustPolicy(**values)  # type: ignore[arg-type]


def _admit(policy: TrustPolicy, *, signature: BundleSignature | None = None):
    signatures = (_bundle_signature(R("b")) if signature is None else signature,)
    authenticated = authenticate_bundle_signatures(
        unsigned_bundle_root=R("b"),
        signatures=signatures,
        policy=policy,
    )
    if isinstance(authenticated, Reject):
        return authenticated
    return admit_bundle_import(
        bundle_root=R("a"),
        unsigned_bundle_root=R("b"),
        content_root=R("c"),
        authenticated_signatures=authenticated,
        previous_bundle_refs=(),
        policy=policy,
        provenance=VerifiedImportProvenance(
            storage_adapters=("ipfs",),
            anchor_adapters=("ethereum",),
            receipt_refs=(R("d"),),
        ),
    )


def test_bundle_admission_verifies_signature_root_threshold_and_provenance() -> None:
    decision = _admit(
        _policy(
            accept_adapters=("ipfs",),
            require_anchors=("ethereum",),
        )
    )
    assert isinstance(decision, Accept)
    assert decision.receipt.signer_key_ids == (_KEY_ID,)
    assert decision.receipt.provenance_receipt_refs == (R("d"),)
    assert decision.next_state.evidence_root == R("a")
    assert is_deeply_immutable(decision.next_state)
    assert is_deeply_immutable(decision.receipt)
    assert not hasattr(decision.next_state, "__dict__")


@pytest.mark.parametrize(
    ("policy", "signature", "expected_code"),
    (
        (_policy(expected_bundle_root=R("f")), None, "BUNDLE_ROOT_MISMATCH"),
        (
            _policy(expected_previous_bundle_refs=(R("e"),)),
            None,
            "REPLAY_PREDECESSOR_MISMATCH",
        ),
        (
            _policy(),
            BundleSignature(
                key_id=_KEY_ID,
                algorithm=SignatureAlgorithm.ED25519,
                signature=b"\x00" * 64,
            ),
            "INVALID_SIGNATURE",
        ),
        (
            _policy(trusted_signers=()),
            None,
            "UNKNOWN_SIGNER",
        ),
        (
            _policy(minimum_signatures=2),
            None,
            "SIGNATURE_THRESHOLD_NOT_MET",
        ),
        (
            _policy(accept_adapters=("local",)),
            None,
            "UNACCEPTED_ADAPTER",
        ),
        (
            _policy(require_anchors=("bitcoin",)),
            None,
            "REQUIRED_ANCHOR_MISSING",
        ),
    ),
)
def test_bundle_admission_fails_closed(
    policy: TrustPolicy,
    signature: BundleSignature | None,
    expected_code: str,
) -> None:
    decision = _admit(policy, signature=signature)
    assert isinstance(decision, Reject)
    assert decision.code == expected_code


def test_unsigned_policy_still_requires_independent_root() -> None:
    decision = admit_bundle_import(
        bundle_root=R("a"),
        unsigned_bundle_root=R("b"),
        content_root=R("c"),
        authenticated_signatures=AuthenticatedBundleSignatures(
            unsigned_bundle_root=R("b"),
            signer_key_ids=(),
        ),
        previous_bundle_refs=(),
        policy=TrustPolicy(
            require_signatures=False,
            expected_bundle_root=None,
        ),
    )
    assert isinstance(decision, Reject)
    assert decision.code == "EXPECTED_BUNDLE_ROOT_REQUIRED"


def _statement(**overrides: object) -> VerifierStatementV1:
    values: dict[str, object] = {
        "claim_ref": R("1"),
        "context_ref": R("2"),
        "recipe_ref": R("3"),
        "evidence_ref": R("4"),
        "edge_ref": R("5"),
        "input_roots": (R("1"),),
        "verifier_id": _VERIFIER_KEY_ID,
        "verifier_version": "z3/4.13.0",
        "result": VerifierResult.SUPPORTS,
        "output_roots": (R("6"),),
        "policy_hash": R("7"),
        "toolchain_hash": R("8"),
    }
    values.update(overrides)
    return VerifierStatementV1(**values)  # type: ignore[arg-type]


def _receipt(statement: VerifierStatementV1) -> VerifierReceiptV1:
    return VerifierReceiptV1(
        statement=statement,
        signer_key_id=_VERIFIER_KEY_ID,
        algorithm=ReceiptSignatureAlgorithm.ED25519,
        signature=_PRIVATE.sign(verifier_statement_signing_bytes(statement)),
    )


def _binding() -> TruthReceiptBinding:
    return TruthReceiptBinding(
        claim_ref=R("1"),
        context_ref=R("2"),
        recipe_ref=R("3"),
        evidence_ref=R("4"),
        edge_ref=R("5"),
        input_roots=(R("1"),),
        result=VerifierResult.SUPPORTS,
        output_roots=(R("6"),),
    )


def test_verifier_receipt_is_canonical_domain_bound_and_deeply_immutable() -> None:
    statement = _statement()
    receipt = _receipt(statement)
    parsed = parse_verifier_receipt_object(verifier_receipt_object(receipt))
    assert parsed == receipt
    assert verifier_receipt_root(receipt) != R("4")
    for value in (statement, receipt, verifier_receipt_object(receipt)):
        assert is_deeply_immutable(value)
        assert not hasattr(value, "__dict__")

    authenticated = AuthenticatedVerifierReceiptV1(
        receipt=receipt,
        receipt_root=verifier_receipt_root(receipt),
    )
    admitted = admit_authenticated_verifier_receipt(
        authenticated,
        binding=_binding(),
        trusted_verifier_ids=(_VERIFIER_KEY_ID,),
        accepted_versions=("z3/4.13.0",),
        accepted_policy_hashes=(R("7"),),
        accepted_toolchain_hashes=(R("8"),),
    )
    assert isinstance(admitted, Accept)
    assert is_deeply_immutable(authenticated)


def test_verifier_receipt_rejects_replay_mismatch_and_tampering() -> None:
    receipt = _receipt(_statement())
    authenticated = AuthenticatedVerifierReceiptV1(
        receipt=receipt,
        receipt_root=verifier_receipt_root(receipt),
    )
    replayed = admit_authenticated_verifier_receipt(
        authenticated,
        binding=replace(_binding(), edge_ref=R("9")),
        trusted_verifier_ids=(_VERIFIER_KEY_ID,),
        accepted_versions=("z3/4.13.0",),
        accepted_policy_hashes=(R("7"),),
        accepted_toolchain_hashes=(R("8"),),
    )
    assert isinstance(replayed, Reject)
    assert replayed.code == "REPLAY_BINDING_MISMATCH"

    untrusted = admit_authenticated_verifier_receipt(
        authenticated,
        binding=_binding(),
        trusted_verifier_ids=(R("0"),),
        accepted_versions=("z3/4.13.0",),
        accepted_policy_hashes=(R("7"),),
        accepted_toolchain_hashes=(R("8"),),
    )
    assert isinstance(untrusted, Reject)
    assert untrusted.code == "UNTRUSTED_VERIFIER"

    raw = verifier_receipt_object(receipt)
    mutable = {key: value for key, value in raw.items()}
    mutable["receipt_root"] = R("0")
    parsed = parse_verifier_receipt_object(mutable)
    assert isinstance(parsed, Reject)
    assert parsed.code == "INVALID_VERIFIER_RECEIPT"

    mutable["algorithm"] = "rsa"
    parsed = parse_verifier_receipt_object(mutable)
    assert isinstance(parsed, Reject)
    assert parsed.code == "INVALID_VERIFIER_RECEIPT"


def test_trusted_receipt_policy_requires_explicit_closed_allowlists() -> None:
    with pytest.raises(ValueError, match="trusted_verifiers"):
        TrustPolicy(
            expected_bundle_root=R("a"),
            trusted_signers=(_SIGNER,),
            truth_mode=ImportTruthMode.TRUSTED_RECEIPT,
        )
    policy = TrustPolicy(
        expected_bundle_root=R("a"),
        trusted_signers=(_SIGNER,),
        trusted_verifiers=(_VERIFIER,),
        accept_verifier_versions=("z3/4.13.0",),
        accept_receipt_policy_hashes=(R("7"),),
        accept_toolchain_hashes=(R("8"),),
        truth_mode=ImportTruthMode.TRUSTED_RECEIPT,
    )
    assert is_deeply_immutable(policy)
    assert not hasattr(policy, "__dict__")


def test_publisher_and_verifier_key_identities_are_domain_separated() -> None:
    assert _KEY_ID != _VERIFIER_KEY_ID
    assert is_deeply_immutable(_SIGNER)
    assert is_deeply_immutable(_VERIFIER)
