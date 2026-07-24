from popperpad.adapters.base import PreparedBundle


def test_prepared_bundle_default_names_the_legacy_v1_canonicalization() -> None:
    prepared = PreparedBundle(
        manifest_ref="sha256:" + "a" * 64,
        bundle_root="sha256:" + "b" * 64,
        object_count=1,
        blob_count=0,
        byte_size=1,
    )
    assert prepared.canonicalization == "popperpad-json-c14n-v1"
    assert "v2" not in prepared.canonicalization
