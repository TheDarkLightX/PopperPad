from __future__ import annotations

from hypothesis import assume, given, strategies as st

from popperpad.adapters.bundle import (
    Bundle,
    build_manifest,
    bundle_root,
    unsigned_bundle_root,
)
from popperpad.canonical import canonical_hash
from popperpad.refs import Ref


def _ref_strategy():
    return st.binary(min_size=32, max_size=32).map(
        lambda raw: Ref("sha256:" + raw.hex())
    )


def _missing_ref(refs: tuple[Ref, ...]) -> Ref:
    existing = frozenset(refs)
    for value in range(len(refs) + 1):
        candidate = Ref("sha256:" + f"{value:064x}")
        if candidate not in existing:
            return candidate
    raise AssertionError("bounded missing-reference search was exhausted")


@st.composite
def _sorted_refs(draw, min_size=0, max_size=5):
    refs = draw(
        st.lists(
            _ref_strategy(),
            min_size=min_size,
            max_size=max_size,
            unique=True,
        )
    )
    return tuple(sorted(refs))


@st.composite
def _valid_bundle_refs(
    draw,
    *,
    min_objects=0,
    max_objects=5,
    min_blobs=0,
    max_blobs=5,
    require_entry=False,
):
    object_refs = draw(_sorted_refs(min_size=min_objects, max_size=max_objects))
    blob_refs = draw(_sorted_refs(min_size=min_blobs, max_size=max_blobs))
    assume(set(object_refs).isdisjoint(blob_refs))
    if object_refs:
        entry_refs = tuple(
            sorted(
                draw(
                    st.lists(
                        st.sampled_from(object_refs),
                        min_size=1 if require_entry else 0,
                        max_size=len(object_refs),
                        unique=True,
                    )
                )
            )
        )
    else:
        entry_refs = ()
    previous_bundle_refs = draw(_sorted_refs())
    return object_refs, blob_refs, entry_refs, previous_bundle_refs


@given(
    bundle_id=st.text(min_size=1, max_size=20),
    refs=_valid_bundle_refs(),
)
def test_root_hash_is_pure_function_of_content(bundle_id, refs):
    object_refs, blob_refs, entry_refs, previous_bundle_refs = refs
    bundle = Bundle(
        bundle_id=bundle_id,
        object_refs=object_refs,
        blob_refs=blob_refs,
        entry_refs=entry_refs,
        previous_bundle_refs=previous_bundle_refs,
    )
    manifest = build_manifest(bundle, created_at="2026-01-01T00:00:00Z")
    content = {
        "object_refs": [str(r) for r in object_refs],
        "blob_refs": [str(r) for r in blob_refs],
        "entry_refs": [str(r) for r in entry_refs],
        "previous_bundle_refs": [str(r) for r in previous_bundle_refs],
    }
    assert manifest.root_hash == canonical_hash("bundle-content/v1", content)


@given(
    bundle_id_a=st.text(min_size=1, max_size=10),
    bundle_id_b=st.text(min_size=1, max_size=10),
    refs=_valid_bundle_refs(
        min_objects=1,
        max_objects=3,
        require_entry=True,
    ),
)
def test_root_hash_independent_of_bundle_id_and_producer(
    bundle_id_a,
    bundle_id_b,
    refs,
):
    object_refs, blob_refs, entry_refs, previous_bundle_refs = refs
    bundle_a = Bundle(
        bundle_id=bundle_id_a,
        object_refs=object_refs,
        blob_refs=blob_refs,
        entry_refs=entry_refs,
        previous_bundle_refs=previous_bundle_refs,
    )
    bundle_b = Bundle(
        bundle_id=bundle_id_b,
        object_refs=object_refs,
        blob_refs=blob_refs,
        entry_refs=entry_refs,
        previous_bundle_refs=previous_bundle_refs,
    )
    m_a = build_manifest(
        bundle_a,
        created_at="2026-01-01T00:00:00Z",
        producer={"name": "A"},
    )
    m_b = build_manifest(
        bundle_b,
        created_at="2026-02-02T00:00:00Z",
        producer={"name": "B"},
    )
    assert m_a.root_hash == m_b.root_hash


@given(
    bundle_id=st.text(min_size=1, max_size=20),
    refs=_valid_bundle_refs(
        min_objects=1,
        max_objects=4,
        require_entry=True,
    ),
)
def test_bundle_root_is_deterministic(bundle_id, refs):
    object_refs, blob_refs, entry_refs, previous_bundle_refs = refs
    bundle = Bundle(
        bundle_id=bundle_id,
        object_refs=object_refs,
        blob_refs=blob_refs,
        entry_refs=entry_refs,
        previous_bundle_refs=previous_bundle_refs,
    )
    manifest = build_manifest(bundle, created_at="2026-01-01T00:00:00Z")
    assert bundle_root(manifest) == bundle_root(manifest)
    assert (
        len(
            {
                manifest.root_hash,
                unsigned_bundle_root(manifest),
                bundle_root(manifest),
            }
        )
        == 3
    )


@given(
    bundle_id=st.text(min_size=1, max_size=20),
    refs=_valid_bundle_refs(
        min_objects=1,
        max_objects=4,
        min_blobs=1,
        max_blobs=3,
        require_entry=True,
    ),
)
def test_bundle_root_changes_when_content_changes(bundle_id, refs):
    object_refs, blob_refs, entry_refs, previous_bundle_refs = refs
    bundle = Bundle(
        bundle_id=bundle_id,
        object_refs=object_refs,
        blob_refs=blob_refs,
        entry_refs=entry_refs,
        previous_bundle_refs=previous_bundle_refs,
    )
    manifest = build_manifest(bundle, created_at="2026-01-01T00:00:00Z")
    extra = _missing_ref(tuple(sorted((*object_refs, *blob_refs))))
    all_refs = tuple(sorted((*object_refs, extra)))
    bundle2 = Bundle(
        bundle_id=bundle_id,
        object_refs=all_refs,
        blob_refs=blob_refs,
        entry_refs=entry_refs,
        previous_bundle_refs=previous_bundle_refs,
    )
    manifest2 = build_manifest(bundle2, created_at="2026-01-01T00:00:00Z")
    assert bundle_root(manifest) != bundle_root(manifest2)
