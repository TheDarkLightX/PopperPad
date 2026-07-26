from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from .codec import canonical_hash, canonical_json_bytes, domain_frame
from .result import Accept, Reject
from .values import ClosedStrEnum, DeeplyImmutable, FrozenDict, JsonValue, freeze_json
from .verifier_receipts import TrustedVerifierV1


_BUNDLE_SIGNATURE_DOMAIN = "bundle-import-signature/v1"
_BUNDLE_SIGNER_KEY_DOMAIN = "bundle-import-signer-key/v1"
_BUNDLE_IMPORT_POLICY_DOMAIN = "bundle-import-policy/v1"
_SIGNATURE_STATEMENT_SCHEMA = "popperpad/bundle-signature-statement/v1"


def _valid_ref(value: object) -> bool:
    if type(value) is not str or not value.startswith("sha256:"):
        return False
    suffix = value[7:]
    return len(suffix) == 64 and suffix == suffix.lower() and all(
        character in "0123456789abcdef" for character in suffix
    )


def _require_ref(field_name: str, value: object) -> None:
    if not _valid_ref(value):
        raise ValueError(f"{field_name} must be a lowercase sha256 ref")


def _require_sorted_unique_strings(
    field_name: str,
    values: object,
) -> None:
    if type(values) is not tuple or not all(
        type(value) is str and bool(value) for value in values
    ):
        raise TypeError(f"{field_name} must be a tuple of non-empty strings")
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{field_name} must be sorted and unique")


def _details(**values: JsonValue) -> FrozenDict[JsonValue]:
    frozen = freeze_json(values)
    assert isinstance(frozen, FrozenDict)
    return frozen


class SignatureAlgorithm(ClosedStrEnum):
    _symbols = (("ED25519", "ed25519"),)


class ImportTruthMode(ClosedStrEnum):
    _symbols = (
        ("QUARANTINED", "quarantined"),
        ("TRUSTED_RECEIPT", "trusted_receipt"),
    )


class ImportAuthorityScope(ClosedStrEnum):
    _symbols = (
        ("QUARANTINED", "import_quarantined"),
        ("TRUSTED_RECEIPT", "import_trusted_receipt"),
    )


def bundle_signer_ref(
    *,
    algorithm: SignatureAlgorithm,
    public_key: bytes,
) -> str:
    if type(algorithm) is not SignatureAlgorithm:
        raise TypeError("algorithm must be a SignatureAlgorithm")
    if algorithm is not SignatureAlgorithm.ED25519:
        raise ValueError("unsupported bundle signer algorithm")
    if type(public_key) is not bytes or len(public_key) != 32:
        raise ValueError("Ed25519 public key must be exactly 32 bytes")
    return canonical_hash(
        _BUNDLE_SIGNER_KEY_DOMAIN,
        {
            "algorithm": algorithm.value,
            "public_key_hex": public_key.hex(),
        },
    )


def bundle_signature_message(unsigned_bundle_root: str) -> bytes:
    _require_ref("unsigned_bundle_root", unsigned_bundle_root)
    statement = canonical_json_bytes(
        {
            "schema": _SIGNATURE_STATEMENT_SCHEMA,
            "unsigned_bundle_root": unsigned_bundle_root,
        }
    )
    return domain_frame(_BUNDLE_SIGNATURE_DOMAIN, statement)


@dataclass(frozen=True, slots=True)
class TrustedSigner(DeeplyImmutable):
    key_id: str
    algorithm: SignatureAlgorithm
    public_key: bytes

    def __post_init__(self) -> None:
        if type(self.algorithm) is not SignatureAlgorithm:
            raise TypeError("algorithm must be a SignatureAlgorithm")
        if type(self.public_key) is not bytes:
            raise TypeError("public_key must be exact bytes")
        expected = bundle_signer_ref(
            algorithm=self.algorithm,
            public_key=self.public_key,
        )
        if self.key_id != expected:
            raise ValueError("key_id does not identify the supplied public key")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class BundleSignature(DeeplyImmutable):
    key_id: str
    algorithm: SignatureAlgorithm
    signature: bytes

    def __post_init__(self) -> None:
        _require_ref("key_id", self.key_id)
        if type(self.algorithm) is not SignatureAlgorithm:
            raise TypeError("algorithm must be a SignatureAlgorithm")
        if (
            self.algorithm is SignatureAlgorithm.ED25519
            and (type(self.signature) is not bytes or len(self.signature) != 64)
        ):
            raise ValueError("Ed25519 signature must be exactly 64 bytes")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class AuthenticatedBundleSignatures(DeeplyImmutable):
    """Imperative-shell result for one exact unsigned manifest root."""

    unsigned_bundle_root: str
    signer_key_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_ref("unsigned_bundle_root", self.unsigned_bundle_root)
        if type(self.signer_key_ids) is not tuple or not all(
            _valid_ref(value) for value in self.signer_key_ids
        ):
            raise TypeError("signer_key_ids must be a tuple of sha256 refs")
        if self.signer_key_ids != tuple(sorted(set(self.signer_key_ids))):
            raise ValueError("signer_key_ids must be sorted and unique")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class VerifiedImportProvenance(DeeplyImmutable):
    """Explicit shell-supplied results from successful adapter verification."""

    storage_adapters: tuple[str, ...] = ()
    anchor_adapters: tuple[str, ...] = ()
    receipt_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_sorted_unique_strings("storage_adapters", self.storage_adapters)
        _require_sorted_unique_strings("anchor_adapters", self.anchor_adapters)
        if type(self.receipt_refs) is not tuple or not all(
            _valid_ref(value) for value in self.receipt_refs
        ):
            raise TypeError("receipt_refs must be a tuple of sha256 refs")
        if self.receipt_refs != tuple(sorted(set(self.receipt_refs))):
            raise ValueError("receipt_refs must be sorted and unique")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class TrustPolicy(DeeplyImmutable):
    """Closed, immutable local authority policy for one bundle import."""

    require_signatures: bool = True
    require_bundle_root_match: bool = True
    expected_bundle_root: str | None = None
    expected_previous_bundle_refs: tuple[str, ...] | None = None
    trusted_signers: tuple[TrustedSigner, ...] = ()
    minimum_signatures: int = 1
    accept_adapters: tuple[str, ...] = ()
    require_anchors: tuple[str, ...] = ()
    trusted_verifiers: tuple[TrustedVerifierV1, ...] = ()
    accept_verifier_versions: tuple[str, ...] = ()
    accept_receipt_policy_hashes: tuple[str, ...] = ()
    accept_toolchain_hashes: tuple[str, ...] = ()
    truth_mode: ImportTruthMode = ImportTruthMode.QUARANTINED

    def __post_init__(self) -> None:
        if type(self.require_signatures) is not bool:
            raise TypeError("require_signatures must be a boolean")
        if type(self.require_bundle_root_match) is not bool:
            raise TypeError("require_bundle_root_match must be a boolean")
        if self.expected_bundle_root is not None:
            _require_ref("expected_bundle_root", self.expected_bundle_root)
        if self.expected_previous_bundle_refs is not None:
            values = self.expected_previous_bundle_refs
            if type(values) is not tuple or not all(
                _valid_ref(value) for value in values
            ):
                raise TypeError("expected_previous_bundle_refs must contain sha256 refs")
            if values != tuple(sorted(set(values))):
                raise ValueError("expected_previous_bundle_refs must be sorted and unique")
        if type(self.trusted_signers) is not tuple or not all(
            type(value) is TrustedSigner for value in self.trusted_signers
        ):
            raise TypeError("trusted_signers must contain exact TrustedSigner values")
        signer_ids = tuple(value.key_id for value in self.trusted_signers)
        if signer_ids != tuple(sorted(set(signer_ids))):
            raise ValueError("trusted_signers must be sorted and unique by key_id")
        if type(self.minimum_signatures) is not int or self.minimum_signatures < 1:
            raise ValueError("minimum_signatures must be a positive integer")
        _require_sorted_unique_strings("accept_adapters", self.accept_adapters)
        _require_sorted_unique_strings("require_anchors", self.require_anchors)
        if type(self.trusted_verifiers) is not tuple or not all(
            type(value) is TrustedVerifierV1 for value in self.trusted_verifiers
        ):
            raise TypeError(
                "trusted_verifiers must contain exact TrustedVerifierV1 values"
            )
        verifier_ids = tuple(value.key_id for value in self.trusted_verifiers)
        if verifier_ids != tuple(sorted(set(verifier_ids))):
            raise ValueError("trusted_verifiers must be sorted and unique by key_id")
        _require_sorted_unique_strings(
            "accept_verifier_versions",
            self.accept_verifier_versions,
        )
        for field_name in ("accept_receipt_policy_hashes", "accept_toolchain_hashes"):
            values = getattr(self, field_name)
            if type(values) is not tuple or not all(_valid_ref(value) for value in values):
                raise TypeError(f"{field_name} must be a tuple of sha256 refs")
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{field_name} must be sorted and unique")
        if type(self.truth_mode) is not ImportTruthMode:
            raise TypeError("truth_mode must be an ImportTruthMode")
        if (
            self.truth_mode is ImportTruthMode.TRUSTED_RECEIPT
            and not self.require_signatures
        ):
            raise ValueError("trusted_receipt truth mode requires signatures")
        if self.truth_mode is ImportTruthMode.TRUSTED_RECEIPT:
            if not self.trusted_verifiers:
                raise ValueError("trusted_receipt truth mode requires trusted_verifiers")
            if not self.accept_verifier_versions:
                raise ValueError(
                    "trusted_receipt truth mode requires accepted verifier versions"
                )
            if not self.accept_receipt_policy_hashes:
                raise ValueError(
                    "trusted_receipt truth mode requires accepted receipt policy hashes"
                )
            if not self.accept_toolchain_hashes:
                raise ValueError(
                    "trusted_receipt truth mode requires accepted toolchain hashes"
                )
        DeeplyImmutable.__post_init__(self)

    def hash(self) -> str:
        return canonical_hash(
            _BUNDLE_IMPORT_POLICY_DOMAIN,
            {
                "require_signatures": self.require_signatures,
                "require_bundle_root_match": self.require_bundle_root_match,
                "expected_bundle_root": self.expected_bundle_root,
                "expected_previous_bundle_refs": self.expected_previous_bundle_refs,
                "trusted_signer_ids": tuple(
                    signer.key_id for signer in self.trusted_signers
                ),
                "minimum_signatures": self.minimum_signatures,
                "accept_adapters": self.accept_adapters,
                "require_anchors": self.require_anchors,
                "truth_mode": self.truth_mode.value,
                "trusted_verifier_ids": tuple(
                    signer.key_id for signer in self.trusted_verifiers
                ),
                "accept_verifier_versions": self.accept_verifier_versions,
                "accept_receipt_policy_hashes": self.accept_receipt_policy_hashes,
                "accept_toolchain_hashes": self.accept_toolchain_hashes,
            },
        )


@dataclass(frozen=True, slots=True)
class ImportPlan(DeeplyImmutable):
    bundle_root: str
    evidence_root: str
    policy_hash: str
    policy_version: str
    authority_scope: ImportAuthorityScope

    def __post_init__(self) -> None:
        _require_ref("bundle_root", self.bundle_root)
        _require_ref("evidence_root", self.evidence_root)
        _require_ref("policy_hash", self.policy_hash)
        if type(self.policy_version) is not str or not self.policy_version:
            raise TypeError("policy_version must be a non-empty string")
        if type(self.authority_scope) is not ImportAuthorityScope:
            raise TypeError("authority_scope must be an ImportAuthorityScope")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class ImportAdmissionReceipt(DeeplyImmutable):
    bundle_root: str
    unsigned_bundle_root: str
    policy_hash: str
    signer_key_ids: tuple[str, ...]
    provenance_receipt_refs: tuple[str, ...]
    truth_mode: ImportTruthMode

    def __post_init__(self) -> None:
        _require_ref("bundle_root", self.bundle_root)
        _require_ref("unsigned_bundle_root", self.unsigned_bundle_root)
        _require_ref("policy_hash", self.policy_hash)
        if type(self.signer_key_ids) is not tuple or not all(
            _valid_ref(value) for value in self.signer_key_ids
        ):
            raise TypeError("signer_key_ids must be a tuple of sha256 refs")
        if self.signer_key_ids != tuple(sorted(set(self.signer_key_ids))):
            raise ValueError("signer_key_ids must be sorted and unique")
        if type(self.provenance_receipt_refs) is not tuple or not all(
            _valid_ref(value) for value in self.provenance_receipt_refs
        ):
            raise TypeError("provenance_receipt_refs must be a tuple of sha256 refs")
        if self.provenance_receipt_refs != tuple(
            sorted(set(self.provenance_receipt_refs))
        ):
            raise ValueError("provenance_receipt_refs must be sorted and unique")
        if type(self.truth_mode) is not ImportTruthMode:
            raise TypeError("truth_mode must be an ImportTruthMode")
        DeeplyImmutable.__post_init__(self)


ImportAdmissionDecision: TypeAlias = (
    Accept[ImportPlan, object, ImportAdmissionReceipt] | Reject
)


def admit_bundle_import(
    *,
    bundle_root: str,
    unsigned_bundle_root: str,
    content_root: str,
    authenticated_signatures: AuthenticatedBundleSignatures,
    previous_bundle_refs: tuple[str, ...],
    policy: TrustPolicy,
    provenance: VerifiedImportProvenance = VerifiedImportProvenance(),
) -> ImportAdmissionDecision:
    """Purely admit one canonical, independently identified bundle."""

    if not _valid_ref(bundle_root):
        return Reject("INVALID_BUNDLE_ROOT", _details(bundle_root=str(bundle_root)))
    if not _valid_ref(unsigned_bundle_root):
        return Reject(
            "INVALID_UNSIGNED_BUNDLE_ROOT",
            _details(unsigned_bundle_root=str(unsigned_bundle_root)),
        )
    if not _valid_ref(content_root):
        return Reject("INVALID_CONTENT_ROOT", _details(content_root=str(content_root)))
    if type(authenticated_signatures) is not AuthenticatedBundleSignatures:
        return Reject(
            "UNAUTHENTICATED_SIGNATURE_SET",
            _details(reason="wrong value type"),
        )
    if type(previous_bundle_refs) is not tuple or not all(
        _valid_ref(value) for value in previous_bundle_refs
    ):
        return Reject(
            "INVALID_PREVIOUS_BUNDLE_REFS",
            _details(reason="must contain sha256 refs"),
        )
    if previous_bundle_refs != tuple(sorted(set(previous_bundle_refs))):
        return Reject("INVALID_PREVIOUS_BUNDLE_REFS", _details(reason="not sorted unique"))
    if type(policy) is not TrustPolicy:
        return Reject("INVALID_TRUST_POLICY", _details(reason="wrong value type"))
    if type(provenance) is not VerifiedImportProvenance:
        return Reject("INVALID_PROVENANCE", _details(reason="wrong value type"))

    if policy.require_bundle_root_match:
        if policy.expected_bundle_root is None:
            return Reject(
                "EXPECTED_BUNDLE_ROOT_REQUIRED",
                _details(reason="policy requires an independently obtained root"),
            )
        if policy.expected_bundle_root != bundle_root:
            return Reject(
                "BUNDLE_ROOT_MISMATCH",
                _details(
                    expected=policy.expected_bundle_root,
                    actual=bundle_root,
                ),
            )

    if authenticated_signatures.unsigned_bundle_root != unsigned_bundle_root:
        return Reject(
            "SIGNATURE_ROOT_MISMATCH",
            _details(
                expected=unsigned_bundle_root,
                actual=authenticated_signatures.unsigned_bundle_root,
            ),
        )
    if (
        policy.expected_previous_bundle_refs is not None
        and policy.expected_previous_bundle_refs != previous_bundle_refs
    ):
        return Reject(
            "REPLAY_PREDECESSOR_MISMATCH",
            _details(
                expected=policy.expected_previous_bundle_refs,
                actual=previous_bundle_refs,
            ),
        )
    trusted_ids = tuple(signer.key_id for signer in policy.trusted_signers)
    untrusted_ids = tuple(
        key_id
        for key_id in authenticated_signatures.signer_key_ids
        if key_id not in trusted_ids
    )
    if untrusted_ids:
        return Reject("UNKNOWN_SIGNER", _details(key_ids=untrusted_ids))
    admitted_signers = authenticated_signatures.signer_key_ids

    if (
        policy.require_signatures
        and len(admitted_signers) < policy.minimum_signatures
    ):
        return Reject(
            "SIGNATURE_THRESHOLD_NOT_MET",
            _details(
                required=policy.minimum_signatures,
                admitted=len(admitted_signers),
            ),
        )

    if policy.accept_adapters:
        if not provenance.storage_adapters:
            return Reject(
                "ACCEPTED_ADAPTER_REQUIRED",
                _details(accepted=policy.accept_adapters),
            )
        unaccepted = tuple(
            value
            for value in provenance.storage_adapters
            if value not in policy.accept_adapters
        )
        if unaccepted:
            return Reject(
                "UNACCEPTED_ADAPTER",
                _details(adapters=unaccepted),
            )

    missing_anchors = tuple(
        value
        for value in policy.require_anchors
        if value not in provenance.anchor_adapters
    )
    if missing_anchors:
        return Reject(
            "REQUIRED_ANCHOR_MISSING",
            _details(anchors=missing_anchors),
        )

    policy_hash = policy.hash()
    if policy.truth_mode is ImportTruthMode.TRUSTED_RECEIPT:
        authority_scope = ImportAuthorityScope.TRUSTED_RECEIPT
        policy_version = "popperpad-import-policy/v2/trusted-receipt"
    else:
        authority_scope = ImportAuthorityScope.QUARANTINED
        policy_version = "popperpad-import-policy/v2/quarantined"
    policy_version = f"{policy_version}/{policy_hash}"
    plan = ImportPlan(
        bundle_root=bundle_root,
        evidence_root=bundle_root,
        policy_hash=policy_hash,
        policy_version=policy_version,
        authority_scope=authority_scope,
    )
    receipt = ImportAdmissionReceipt(
        bundle_root=bundle_root,
        unsigned_bundle_root=unsigned_bundle_root,
        policy_hash=policy_hash,
        signer_key_ids=tuple(sorted(admitted_signers)),
        provenance_receipt_refs=provenance.receipt_refs,
        truth_mode=policy.truth_mode,
    )
    return Accept(next_state=plan, effects=(), receipt=receipt)
