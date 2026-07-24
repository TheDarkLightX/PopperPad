#![forbid(unsafe_code)]

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::error::Error;
use std::fmt::{Display, Formatter};

const DOMAIN_PREFIX: &[u8] = b"PopperPad\0";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CoreError {
    FloatingPointNotAllowed,
    InvalidDomain,
    InvalidPreStateRoot,
    InvalidObjectSchema,
    DuplicateWrite(String),
    ArithmeticOverflow,
    Serialization(String),
}

impl Display for CoreError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::FloatingPointNotAllowed => formatter.write_str("floating-point JSON is not allowed"),
            Self::InvalidDomain => formatter.write_str("hash domain must be non-empty, NUL-free, and at most 65535 bytes"),
            Self::InvalidPreStateRoot => formatter.write_str("pre-state root must be empty or sha256:<64hex>"),
            Self::InvalidObjectSchema => formatter.write_str("committed objects require a non-empty string schema"),
            Self::DuplicateWrite(reference) => write!(formatter, "duplicate write: {reference}"),
            Self::ArithmeticOverflow => formatter.write_str("exact amount arithmetic overflowed"),
            Self::Serialization(message) => write!(formatter, "serialization failure: {message}"),
        }
    }
}

impl Error for CoreError {}

pub fn canonical_json_bytes(value: &Value) -> Result<Vec<u8>, CoreError> {
    let mut output = String::new();
    write_canonical_json(value, &mut output)?;
    output.push('\n');
    Ok(output.into_bytes())
}

fn write_canonical_json(value: &Value, output: &mut String) -> Result<(), CoreError> {
    match value {
        Value::Null => output.push_str("null"),
        Value::Bool(value) => output.push_str(if *value { "true" } else { "false" }),
        Value::Number(number) => {
            let encoded = number.to_string();
            if encoded.contains('.') || encoded.contains('e') || encoded.contains('E') {
                return Err(CoreError::FloatingPointNotAllowed);
            }
            output.push_str(&encoded);
        }
        Value::String(value) => {
            output.push_str(
                &serde_json::to_string(value)
                    .map_err(|error| CoreError::Serialization(error.to_string()))?,
            );
        }
        Value::Array(values) => {
            output.push('[');
            for (index, child) in values.iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                write_canonical_json(child, output)?;
            }
            output.push(']');
        }
        Value::Object(values) => {
            output.push('{');
            let mut keys: Vec<&str> = values.keys().map(String::as_str).collect();
            keys.sort_unstable();
            for (index, key) in keys.iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                output.push_str(
                    &serde_json::to_string(key)
                        .map_err(|error| CoreError::Serialization(error.to_string()))?,
                );
                output.push(':');
                write_canonical_json(&values[*key], output)?;
            }
            output.push('}');
        }
    }
    Ok(())
}

#[must_use]
pub fn sha256_bytes(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    format!("sha256:{}", hex::encode(digest))
}

pub fn domain_sha256(domain: &str, bytes: &[u8]) -> Result<String, CoreError> {
    if domain.is_empty() || domain.contains('\0') || domain.len() > usize::from(u16::MAX) {
        return Err(CoreError::InvalidDomain);
    }
    let domain_len = u16::try_from(domain.len()).map_err(|_| CoreError::InvalidDomain)?;
    let mut framed = Vec::with_capacity(DOMAIN_PREFIX.len() + 2 + domain.len() + bytes.len());
    framed.extend_from_slice(DOMAIN_PREFIX);
    framed.extend_from_slice(&domain_len.to_be_bytes());
    framed.extend_from_slice(domain.as_bytes());
    framed.extend_from_slice(bytes);
    Ok(sha256_bytes(&framed))
}

pub fn canonical_hash(domain: &str, value: &Value) -> Result<String, CoreError> {
    domain_sha256(domain, &canonical_json_bytes(value)?)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct Amount(u64);

impl Amount {
    #[must_use]
    pub const fn new(atoms: u64) -> Self {
        Self(atoms)
    }

    #[must_use]
    pub const fn atoms(self) -> u64 {
        self.0
    }

    pub fn checked_add(self, other: Self) -> Result<Self, CoreError> {
        self.0
            .checked_add(other.0)
            .map(Self)
            .ok_or(CoreError::ArithmeticOverflow)
    }

    pub fn checked_sub(self, other: Self) -> Result<Self, CoreError> {
        self.0
            .checked_sub(other.0)
            .map(Self)
            .ok_or(CoreError::ArithmeticOverflow)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Decision<State, Effect, Receipt> {
    Reject {
        code: String,
        details: Value,
    },
    Accept {
        next_state: State,
        effects: Vec<Effect>,
        receipt: Receipt,
    },
    CommittedFailure {
        code: String,
        next_state: State,
        effects: Vec<Effect>,
        receipt: Receipt,
        details: Value,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct BlobInput {
    pub payload_utf8: String,
    pub media_type: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct OutboxInput {
    pub kind: String,
    pub payload: Value,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct CommitInput {
    #[serde(default)]
    pub expected_head: String,
    pub created_at: String,
    #[serde(default)]
    pub objects: Vec<Value>,
    #[serde(default)]
    pub blobs: Vec<BlobInput>,
    #[serde(default)]
    pub outbox: Vec<OutboxInput>,
    #[serde(default)]
    pub evidence_root: String,
    #[serde(default = "default_policy_version")]
    pub policy_version: String,
    #[serde(default = "default_core_version")]
    pub core_version: String,
}

fn default_policy_version() -> String {
    "popperpad-policy/v1".to_owned()
}

fn default_core_version() -> String {
    "popperpad-core/v1".to_owned()
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CommitSummary {
    pub object_refs: Vec<String>,
    pub blob_refs: Vec<String>,
    pub effect_ids: Vec<String>,
    pub command_hash: String,
    pub replay_id: String,
    pub effect_plan_hash: String,
    pub commit_root: String,
    pub record_hash: String,
    pub record_canonical_utf8: String,
}

fn valid_ref_or_empty(value: &str) -> bool {
    if value.is_empty() {
        return true;
    }
    let Some(hex) = value.strip_prefix("sha256:") else {
        return false;
    };
    hex.len() == 64 && hex.bytes().all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

pub fn plan_commit(input: &CommitInput) -> Result<CommitSummary, CoreError> {
    if !valid_ref_or_empty(&input.expected_head) {
        return Err(CoreError::InvalidPreStateRoot);
    }

    let mut seen_refs = HashSet::new();
    let mut object_rows = Vec::with_capacity(input.objects.len());
    let mut object_refs = Vec::with_capacity(input.objects.len());
    for object in &input.objects {
        let schema = object
            .as_object()
            .and_then(|mapping| mapping.get("schema"))
            .and_then(Value::as_str)
            .filter(|schema| !schema.is_empty())
            .ok_or(CoreError::InvalidObjectSchema)?;
        let payload = canonical_json_bytes(object)?;
        let reference = sha256_bytes(&payload);
        if !seen_refs.insert(reference.clone()) {
            return Err(CoreError::DuplicateWrite(reference));
        }
        object_rows.push(json!({"ref": reference, "schema": schema, "bytes": payload.len()}));
        object_refs.push(reference);
    }

    let mut blob_rows = Vec::with_capacity(input.blobs.len());
    let mut blob_refs = Vec::with_capacity(input.blobs.len());
    for blob in &input.blobs {
        let payload = blob.payload_utf8.as_bytes();
        let reference = sha256_bytes(payload);
        if !seen_refs.insert(reference.clone()) {
            return Err(CoreError::DuplicateWrite(reference));
        }
        blob_rows.push(json!({
            "ref": reference,
            "media_type": blob.media_type,
            "bytes": payload.len(),
        }));
        blob_refs.push(reference);
    }

    let command_value = json!({
        "expected_head": input.expected_head,
        "objects": object_rows,
        "blobs": blob_rows,
        "policy_version": input.policy_version,
        "core_version": input.core_version,
    });
    let command_hash = canonical_hash("commit-command/v1", &command_value)?;
    let replay_id = canonical_hash(
        "replay-id/v1",
        &json!({"pre_state_root": input.expected_head, "command_hash": command_hash}),
    )?;

    let mut effect_rows = Vec::with_capacity(input.outbox.len());
    let mut effect_ids = Vec::with_capacity(input.outbox.len());
    for (index, effect) in input.outbox.iter().enumerate() {
        let effect_id = canonical_hash(
            "outbox-effect-id/v1",
            &json!({
                "replay_id": replay_id,
                "index": index,
                "kind": effect.kind,
                "payload": effect.payload,
            }),
        )?;
        effect_rows.push(json!({
            "effect_id": effect_id,
            "kind": effect.kind,
            "payload": effect.payload,
        }));
        effect_ids.push(effect_id);
    }

    let effect_plan_hash = canonical_hash("effect-plan/v1", &Value::Array(effect_rows.clone()))?;
    let commit_value = json!({
        "expected_head": input.expected_head,
        "created_at": input.created_at,
        "command_hash": command_hash,
        "evidence_root": input.evidence_root,
        "objects": object_rows,
        "blobs": blob_rows,
        "outbox": effect_rows,
        "policy_version": input.policy_version,
        "core_version": input.core_version,
    });
    let commit_root = canonical_hash("commit-bundle/v1", &commit_value)?;
    let receipt = json!({
        "version": "popperpad/receipt/v1",
        "pre_state_root": input.expected_head,
        "command_hash": command_hash,
        "evidence_root": input.evidence_root,
        "policy_version": input.policy_version,
        "core_version": input.core_version,
        "replay_id": replay_id,
        "next_state_root": commit_root,
        "effect_plan_hash": effect_plan_hash,
    });
    let record_core = json!({
        "schema": "popperpad/log_record/v2",
        "op": "commit_bundle",
        "created_at": input.created_at,
        "prev_record_hash": input.expected_head,
        "commit_root": commit_root,
        "objects": object_rows,
        "blobs": blob_rows,
        "outbox": effect_rows,
        "receipt": receipt,
    });
    let record_hash = canonical_hash("log-record/v2", &record_core)?;
    let mut record = record_core;
    record
        .as_object_mut()
        .expect("record_core is constructed as an object")
        .insert("record_hash".to_owned(), Value::String(record_hash.clone()));
    let record_canonical_utf8 = String::from_utf8(canonical_json_bytes(&record)?)
        .map_err(|error| CoreError::Serialization(error.to_string()))?;

    Ok(CommitSummary {
        object_refs,
        blob_refs,
        effect_ids,
        command_hash,
        replay_id,
        effect_plan_hash,
        commit_root,
        record_hash,
        record_canonical_utf8,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Debug, Deserialize)]
    struct VectorFile {
        schema: String,
        canonical_cases: Vec<CanonicalCase>,
        domain_hash_cases: Vec<DomainHashCase>,
        commit_cases: Vec<CommitCase>,
    }

    #[derive(Debug, Deserialize)]
    struct CanonicalCase {
        name: String,
        value: Value,
        canonical_utf8: String,
        raw_sha256: String,
    }

    #[derive(Debug, Deserialize)]
    struct DomainHashCase {
        name: String,
        domain: String,
        value: Value,
        hash: String,
    }

    #[derive(Debug, Deserialize)]
    struct CommitCase {
        name: String,
        input: CommitInput,
        expected: CommitSummary,
    }

    fn vectors() -> VectorFile {
        serde_json::from_str(include_str!("../../../vectors/fcis-v1.json"))
            .expect("shared FCIS vectors must parse")
    }

    #[test]
    fn canonical_vectors_match_python() {
        let vectors = vectors();
        assert_eq!(vectors.schema, "popperpad/fcis-vectors/v1");
        for case in vectors.canonical_cases {
            let bytes = canonical_json_bytes(&case.value).unwrap_or_else(|error| panic!("{}: {error}", case.name));
            assert_eq!(String::from_utf8(bytes.clone()).expect("canonical JSON is UTF-8"), case.canonical_utf8, "{}", case.name);
            assert_eq!(sha256_bytes(&bytes), case.raw_sha256, "{}", case.name);
        }
    }

    #[test]
    fn domain_hash_vectors_match_python() {
        for case in vectors().domain_hash_cases {
            assert_eq!(canonical_hash(&case.domain, &case.value).unwrap(), case.hash, "{}", case.name);
        }
    }

    #[test]
    fn commit_vectors_match_python() {
        for case in vectors().commit_cases {
            assert_eq!(plan_commit(&case.input).unwrap(), case.expected, "{}", case.name);
        }
    }

    #[test]
    fn floating_point_is_rejected() {
        let value: Value = serde_json::from_str("{\"risk\":0.5}").unwrap();
        assert_eq!(canonical_json_bytes(&value), Err(CoreError::FloatingPointNotAllowed));
    }

    #[test]
    fn exact_amount_arithmetic_is_checked() {
        assert_eq!(Amount::new(7).checked_add(Amount::new(5)).unwrap().atoms(), 12);
        assert_eq!(Amount::new(7).checked_sub(Amount::new(5)).unwrap().atoms(), 2);
        assert_eq!(Amount::new(5).checked_sub(Amount::new(7)), Err(CoreError::ArithmeticOverflow));
    }
}
