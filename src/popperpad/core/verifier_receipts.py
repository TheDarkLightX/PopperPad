from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, TypeAlias

from .codec import canonical_hash, canonical_json_bytes, domain_frame
from .result import Accept, Reject
from .values import ClosedStrEnum, DeeplyImmutable, FrozenDict, JsonValue, freeze_json, thaw_json


_STATEMENT_SCHEMA = "popperpad/verifier-statement/v1"
_RECEIPT_SCHEMA = "popperpad/verifier-receipt/v1"
_VERIFIER_KEY_DOMAIN = "verifier-signer-key/v1"
_STATEMENT_DOMAIN = "verifier-statement/v1"
_RECEIPT_DOMAIN = "verifier-receipt/v1"
_STATEMENT_FIELDS = frozenset(
    {
        "schema",
        "claim_ref",
        "context_ref",
        "recipe_ref",
        "evidence_ref",
        "edge_ref",
        "input_roots",
        "verifier_id",
        "verifier_version",
        "result",
        "output_roots",
        "policy_hash",
        "toolchain_hash",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "receipt_root",
        "algorithm",
        "signer_key_id",
        "signature_hex",
        "statement",
    }
)


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


def _require_ref_tuple(field_name: str, values: object) -> None:
    if type(values) is not tuple or not all(_valid_ref(value) for value in values):
        raise TypeError(f"{field_name} must be a tuple of sha256 refs")
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{field_name} must be sorted and unique")


def _details(**values: JsonValue) -> FrozenDict[JsonValue]:
    result = freeze_json(values)
    assert isinstance(result, FrozenDict)
    return result


class VerifierResult(ClosedStrEnum):
    _symbols = (
        ("SUPPORTS", "supports"),
        ("REFUTES", "refutes"),
    )


class ReceiptSignatureAlgorithm(ClosedStrEnum):
    _symbols = (("ED25519", "ed25519"),)


def verifier_key_ref(
    *,
    algorithm: ReceiptSignatureAlgorithm,
    public_key: bytes,
) -> str:
    if type(algorithm) is not ReceiptSignatureAlgorithm:
        raise TypeError("algorithm must be a ReceiptSignatureAlgorithm")
    if algorithm is not ReceiptSignatureAlgorithm.ED25519:
        raise ValueError("unsupported verifier signature algorithm")
    if type(public_key) is not bytes or len(public_key) != 32:
        raise ValueError("Ed25519 public key must be exactly 32 bytes")
    return canonical_hash(
        _VERIFIER_KEY_DOMAIN,
        {
            "algorithm": algorithm.value,
            "public_key_hex": public_key.hex(),
        },
    )


@dataclass(frozen=True, slots=True)
class TrustedVerifierV1(DeeplyImmutable):
    key_id: str
    algorithm: ReceiptSignatureAlgorithm
    public_key: bytes

    def __post_init__(self) -> None:
        if type(self.algorithm) is not ReceiptSignatureAlgorithm:
            raise TypeError("algorithm must be a ReceiptSignatureAlgorithm")
        if type(self.public_key) is not bytes:
            raise TypeError("public_key must be exact bytes")
        expected = verifier_key_ref(
            algorithm=self.algorithm,
            public_key=self.public_key,
        )
        if self.key_id != expected:
            raise ValueError("key_id does not identify the supplied verifier key")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class VerifierStatementV1(DeeplyImmutable):
    claim_ref: str
    context_ref: str | None
    recipe_ref: str
    evidence_ref: str
    edge_ref: str
    input_roots: tuple[str, ...]
    verifier_id: str
    verifier_version: str
    result: VerifierResult
    output_roots: tuple[str, ...]
    policy_hash: str
    toolchain_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "claim_ref",
            "recipe_ref",
            "evidence_ref",
            "edge_ref",
            "verifier_id",
            "policy_hash",
            "toolchain_hash",
        ):
            _require_ref(field_name, getattr(self, field_name))
        if self.context_ref is not None:
            _require_ref("context_ref", self.context_ref)
        _require_ref_tuple("input_roots", self.input_roots)
        _require_ref_tuple("output_roots", self.output_roots)
        if type(self.verifier_version) is not str or not self.verifier_version:
            raise TypeError("verifier_version must be a non-empty string")
        if type(self.result) is not VerifierResult:
            raise TypeError("result must be a VerifierResult")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class VerifierReceiptV1(DeeplyImmutable):
    statement: VerifierStatementV1
    signer_key_id: str
    algorithm: ReceiptSignatureAlgorithm
    signature: bytes

    def __post_init__(self) -> None:
        if type(self.statement) is not VerifierStatementV1:
            raise TypeError("statement must be an exact VerifierStatementV1")
        _require_ref("signer_key_id", self.signer_key_id)
        if self.signer_key_id != self.statement.verifier_id:
            raise ValueError("signer_key_id must equal statement verifier_id")
        if type(self.algorithm) is not ReceiptSignatureAlgorithm:
            raise TypeError("algorithm must be a ReceiptSignatureAlgorithm")
        if (
            self.algorithm is ReceiptSignatureAlgorithm.ED25519
            and (type(self.signature) is not bytes or len(self.signature) != 64)
        ):
            raise ValueError("Ed25519 signature must be exactly 64 bytes")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class AuthenticatedVerifierReceiptV1(DeeplyImmutable):
    """Shell-produced result of authenticating one exact receipt."""

    receipt: VerifierReceiptV1
    receipt_root: str

    def __post_init__(self) -> None:
        if type(self.receipt) is not VerifierReceiptV1:
            raise TypeError("receipt must be an exact VerifierReceiptV1")
        _require_ref("receipt_root", self.receipt_root)
        if self.receipt_root != verifier_receipt_root(self.receipt):
            raise ValueError("receipt_root does not identify receipt")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class TruthReceiptBinding(DeeplyImmutable):
    claim_ref: str
    context_ref: str | None
    recipe_ref: str
    evidence_ref: str
    edge_ref: str
    input_roots: tuple[str, ...]
    result: VerifierResult
    output_roots: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("claim_ref", "recipe_ref", "evidence_ref", "edge_ref"):
            _require_ref(field_name, getattr(self, field_name))
        if self.context_ref is not None:
            _require_ref("context_ref", self.context_ref)
        _require_ref_tuple("input_roots", self.input_roots)
        _require_ref_tuple("output_roots", self.output_roots)
        if type(self.result) is not VerifierResult:
            raise TypeError("result must be a VerifierResult")
        DeeplyImmutable.__post_init__(self)


def verifier_statement_json(statement: VerifierStatementV1) -> FrozenDict[JsonValue]:
    if type(statement) is not VerifierStatementV1:
        raise TypeError("statement must be an exact VerifierStatementV1")
    value = freeze_json(
        {
            "schema": _STATEMENT_SCHEMA,
            "claim_ref": statement.claim_ref,
            "context_ref": statement.context_ref,
            "recipe_ref": statement.recipe_ref,
            "evidence_ref": statement.evidence_ref,
            "edge_ref": statement.edge_ref,
            "input_roots": statement.input_roots,
            "verifier_id": statement.verifier_id,
            "verifier_version": statement.verifier_version,
            "result": statement.result.value,
            "output_roots": statement.output_roots,
            "policy_hash": statement.policy_hash,
            "toolchain_hash": statement.toolchain_hash,
        }
    )
    assert isinstance(value, FrozenDict)
    return value


def verifier_statement_signing_bytes(statement: VerifierStatementV1) -> bytes:
    return domain_frame(
        _STATEMENT_DOMAIN,
        canonical_json_bytes(verifier_statement_json(statement)),
    )


def _receipt_body(receipt: VerifierReceiptV1) -> FrozenDict[JsonValue]:
    value = freeze_json(
        {
            "schema": _RECEIPT_SCHEMA,
            "algorithm": receipt.algorithm.value,
            "signer_key_id": receipt.signer_key_id,
            "signature_hex": receipt.signature.hex(),
            "statement": verifier_statement_json(receipt.statement),
        }
    )
    assert isinstance(value, FrozenDict)
    return value


def verifier_receipt_root(receipt: VerifierReceiptV1) -> str:
    if type(receipt) is not VerifierReceiptV1:
        raise TypeError("receipt must be an exact VerifierReceiptV1")
    return canonical_hash(_RECEIPT_DOMAIN, _receipt_body(receipt))


def verifier_receipt_object(receipt: VerifierReceiptV1) -> FrozenDict[JsonValue]:
    body = thaw_json(_receipt_body(receipt))
    body["receipt_root"] = verifier_receipt_root(receipt)
    value = freeze_json(body)
    assert isinstance(value, FrozenDict)
    return value


def parse_verifier_receipt_object(
    raw: Mapping[str, Any],
) -> VerifierReceiptV1 | Reject:
    """Pure exact decoder for a canonical verifier-receipt object."""

    try:
        if type(raw) not in (dict, FrozenDict):
            raise TypeError("receipt must be an owned object")
        if set(raw) != _RECEIPT_FIELDS:
            raise ValueError("receipt has unknown or missing fields")
        statement_raw = raw["statement"]
        if type(statement_raw) not in (dict, FrozenDict):
            raise TypeError("receipt statement must be an owned object")
        if set(statement_raw) != _STATEMENT_FIELDS:
            raise ValueError("receipt statement has unknown or missing fields")
        if statement_raw["schema"] != _STATEMENT_SCHEMA:
            raise ValueError("unsupported verifier statement schema")
        if raw["schema"] != _RECEIPT_SCHEMA:
            raise ValueError("unsupported verifier receipt schema")
        if raw["algorithm"] != ReceiptSignatureAlgorithm.ED25519.value:
            raise ValueError("unsupported verifier receipt algorithm")
        signature_hex = raw["signature_hex"]
        if (
            type(signature_hex) is not str
            or len(signature_hex) != 128
            or signature_hex != signature_hex.lower()
        ):
            raise ValueError("signature_hex must be lowercase 64-byte hex")
        signature = bytes.fromhex(signature_hex)
        statement = VerifierStatementV1(
            claim_ref=statement_raw["claim_ref"],
            context_ref=statement_raw["context_ref"],
            recipe_ref=statement_raw["recipe_ref"],
            evidence_ref=statement_raw["evidence_ref"],
            edge_ref=statement_raw["edge_ref"],
            input_roots=tuple(statement_raw["input_roots"]),
            verifier_id=statement_raw["verifier_id"],
            verifier_version=statement_raw["verifier_version"],
            result=VerifierResult(statement_raw["result"]),
            output_roots=tuple(statement_raw["output_roots"]),
            policy_hash=statement_raw["policy_hash"],
            toolchain_hash=statement_raw["toolchain_hash"],
        )
        receipt = VerifierReceiptV1(
            statement=statement,
            signer_key_id=raw["signer_key_id"],
            algorithm=ReceiptSignatureAlgorithm(raw["algorithm"]),
            signature=signature,
        )
        if raw["receipt_root"] != verifier_receipt_root(receipt):
            raise ValueError("receipt_root mismatch")
        return receipt
    except (KeyError, TypeError, ValueError) as exc:
        return Reject("INVALID_VERIFIER_RECEIPT", _details(reason=str(exc)))


VerifierReceiptDecision: TypeAlias = (
    Accept[VerifierStatementV1, object, AuthenticatedVerifierReceiptV1] | Reject
)


def admit_authenticated_verifier_receipt(
    authenticated: AuthenticatedVerifierReceiptV1,
    *,
    binding: TruthReceiptBinding,
    trusted_verifier_ids: tuple[str, ...],
    accepted_versions: tuple[str, ...],
    accepted_policy_hashes: tuple[str, ...],
    accepted_toolchain_hashes: tuple[str, ...],
) -> VerifierReceiptDecision:
    """Purely bind one shell-authenticated receipt to one truth edge."""

    if type(authenticated) is not AuthenticatedVerifierReceiptV1:
        return Reject("UNAUTHENTICATED_VERIFIER_RECEIPT", _details())
    if type(binding) is not TruthReceiptBinding:
        return Reject("INVALID_TRUTH_BINDING", _details())
    receipt = authenticated.receipt
    statement = receipt.statement
    if statement.verifier_id not in trusted_verifier_ids:
        return Reject(
            "UNTRUSTED_VERIFIER",
            _details(verifier_id=statement.verifier_id),
        )
    if statement.verifier_version not in accepted_versions:
        return Reject(
            "UNACCEPTED_VERIFIER_VERSION",
            _details(verifier_version=statement.verifier_version),
        )
    if statement.policy_hash not in accepted_policy_hashes:
        return Reject(
            "RECEIPT_POLICY_MISMATCH",
            _details(policy_hash=statement.policy_hash),
        )
    if statement.toolchain_hash not in accepted_toolchain_hashes:
        return Reject(
            "TOOLCHAIN_MISMATCH",
            _details(toolchain_hash=statement.toolchain_hash),
        )
    expected = (
        binding.claim_ref,
        binding.context_ref,
        binding.recipe_ref,
        binding.evidence_ref,
        binding.edge_ref,
        binding.input_roots,
        binding.result,
        binding.output_roots,
    )
    actual = (
        statement.claim_ref,
        statement.context_ref,
        statement.recipe_ref,
        statement.evidence_ref,
        statement.edge_ref,
        statement.input_roots,
        statement.result,
        statement.output_roots,
    )
    if actual != expected:
        return Reject(
            "REPLAY_BINDING_MISMATCH",
            _details(receipt_root=authenticated.receipt_root),
        )
    return Accept(
        next_state=statement,
        effects=(),
        receipt=authenticated,
    )
