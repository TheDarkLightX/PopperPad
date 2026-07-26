"""Pure, deterministic PopperPad semantics.

Modules under :mod:`popperpad.core` may depend only on Python's value-oriented
standard-library facilities and other core modules. They must not perform I/O,
read clocks or environment variables, execute processes, use randomness, or
import shell adapters.
"""

from .result import Accept, CommittedFailure, Decision, Reject
from .values import Amount, DeeplyImmutable, FrozenDict, JsonValue, freeze_json, thaw_json
from .verifier_receipts import (
    ReceiptSignatureAlgorithm,
    TrustedVerifierV1,
    VerifierReceiptV1,
    VerifierResult,
    VerifierStatementV1,
    verifier_key_ref,
    verifier_receipt_object,
    verifier_receipt_root,
    verifier_statement_signing_bytes,
)

__all__ = [
    "Accept",
    "Amount",
    "CommittedFailure",
    "Decision",
    "DeeplyImmutable",
    "FrozenDict",
    "JsonValue",
    "ReceiptSignatureAlgorithm",
    "Reject",
    "TrustedVerifierV1",
    "VerifierReceiptV1",
    "VerifierResult",
    "VerifierStatementV1",
    "freeze_json",
    "thaw_json",
    "verifier_key_ref",
    "verifier_receipt_object",
    "verifier_receipt_root",
    "verifier_statement_signing_bytes",
]
