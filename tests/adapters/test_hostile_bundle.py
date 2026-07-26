from __future__ import annotations

import json
from pathlib import Path

import pytest

import popperpad.adapters.bundle as bundle_module
from popperpad.adapters.bundle import Bundle, export_bundle, load_bundle_dir
from popperpad.canonical import canonical_json_bytes, sha256_bytes
from popperpad.refs import Ref, ValidationError


def _export_domain(tmp_path: Path) -> tuple[Path, str]:
    value = {
        "schema": "popperpad/domain/v1",
        "domain_id": "hostile",
        "name": "Hostile boundary",
        "tags": [],
    }
    payload = canonical_json_bytes(value)
    ref = sha256_bytes(payload)
    out = tmp_path / "bundle"
    export_bundle(
        Bundle(
            bundle_id="hostile",
            object_refs=(Ref(ref),),
            blob_refs=(),
            entry_refs=(Ref(ref),),
        ),
        out,
        objects={ref: payload},
        blobs={},
        created_at="2026-07-25T00:00:00Z",
    )
    return out, ref


def _rewrite_manifest(path: Path, mutate) -> None:
    value = json.loads(path.read_bytes())
    mutate(value)
    path.write_bytes(canonical_json_bytes(value))


def _fake_signature(character: str) -> dict[str, str]:
    return {
        "algorithm": "ed25519",
        "key_id": "sha256:" + character * 64,
        "signature_hex": "00" * 64,
    }


def test_manifest_rejects_duplicate_keys_and_noncanonical_bytes(tmp_path: Path) -> None:
    bundle_dir, _ref = _export_domain(tmp_path)
    manifest_path = bundle_dir / "manifest.json"
    raw = manifest_path.read_bytes()
    duplicate = raw.replace(
        b'{"anchor_hints":',
        b'{"anchor_hints":[],"anchor_hints":',
        1,
    )
    manifest_path.write_bytes(duplicate)
    with pytest.raises(ValidationError, match="duplicate manifest key"):
        load_bundle_dir(bundle_dir)

    manifest_path.write_bytes(raw.replace(b'{"anchor_hints":', b'{ "anchor_hints":', 1))
    with pytest.raises(ValidationError, match="canonical bytes"):
        load_bundle_dir(bundle_dir)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.__setitem__("unexpected", True), "unknown or missing"),
        (
            lambda value: value.__setitem__(
                "object_refs",
                [value["object_refs"][0], value["object_refs"][0]],
            ),
            "sorted and unique",
        ),
        (
            lambda value: value.__setitem__("object_refs", ["sha256:../../escape"]),
            "invalid ref",
        ),
        (
            lambda value: value.__setitem__(
                "signatures",
                [_fake_signature("2"), _fake_signature("1")],
            ),
            "sorted and unique",
        ),
        (
            lambda value: value.__setitem__(
                "signatures",
                [
                    {
                        "algorithm": "rsa",
                        "key_id": "sha256:" + "1" * 64,
                        "signature_hex": "00" * 64,
                    }
                ],
            ),
            "unsupported signature algorithm",
        ),
    ),
)
def test_manifest_rejects_unknown_fields_refs_and_algorithms_before_payload_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation,
    message: str,
) -> None:
    bundle_dir, _ref = _export_domain(tmp_path)
    _rewrite_manifest(bundle_dir / "manifest.json", mutation)
    reads: list[Path] = []
    original = bundle_module._read_regular_bundle_file

    def tracking_read(root: Path, path: Path, *, max_bytes: int) -> bytes:
        reads.append(path.relative_to(root))
        return original(root, path, max_bytes=max_bytes)

    monkeypatch.setattr(bundle_module, "_read_regular_bundle_file", tracking_read)
    with pytest.raises((TypeError, ValueError), match=message):
        load_bundle_dir(bundle_dir)
    assert reads == [Path("manifest.json")]


def test_payload_symlink_is_rejected_even_when_target_bytes_hash_correctly(
    tmp_path: Path,
) -> None:
    bundle_dir, ref = _export_domain(tmp_path)
    prefix = ref[7:9]
    payload_path = (
        bundle_dir
        / "objects"
        / "sha256"
        / prefix
        / f"sha256-{ref[7:]}.json"
    )
    outside = tmp_path / "outside.json"
    outside.write_bytes(payload_path.read_bytes())
    payload_path.unlink()
    payload_path.symlink_to(outside)

    with pytest.raises(ValidationError, match="symlink"):
        load_bundle_dir(bundle_dir)


def test_total_payload_byte_budget_is_enforced_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir, _ref = _export_domain(tmp_path)
    monkeypatch.setattr(
        bundle_module,
        "MAX_TOTAL_PAYLOAD_BYTES",
        1,
    )
    with pytest.raises(ValidationError, match="byte limit"):
        load_bundle_dir(bundle_dir)
