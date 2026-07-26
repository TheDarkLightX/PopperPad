from __future__ import annotations

from hypothesis import given, strategies as st

from popperpad.adapters.bundle import Bundle, build_manifest, bundle_root
from popperpad.canonical import stable_sha256
from popperpad.refs import Ref


def _ref_strategy():
    return st.binary(min_size=32, max_size=32).map(lambda raw: Ref("sha256:" + raw.hex()))


def _missing_ref(refs: tuple[Ref, ...]) -> Ref:
    existing = frozenset(refs)
    for value in range(len(refs) + 1):
        candidate = Ref("sha256:" + f"{value:064x}")
        if candidate not in existing:
            return candidate
    raise AssertionError("bounded missing-reference search was exhausted")


@st.composite
def _sorted_refs(draw, min_size=0, max_size=5):
    refs = draw(st.lists(_ref_strategy(), min_size=min_size, max_size=max_size, unique=True))
    return tuple(sorted(refs))


@given(
    bundle_id=st.text(min_size=1, max_size=20),
    object_refs=_sorted_refs(),
    blob_refs=_sorted_refs(),
    entry_refs=_sorted_refs(),
    previous_bundle_refs=_sorted_refs(),
)
def test_root_hash_is_pure_function_of_content(bundle_id, object_refs, blob_refs, entry_refs, previous_bundle_refs):
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
    assert manifest.root_hash == stable_sha256(content)


@given(
    bundle_id_a=st.text(min_size=1, max_size=10),
    bundle_id_b=st.text(min_size=1, max_size=10),
    object_refs=_sorted_refs(min_size=1, max_size=3),
    blob_refs=_sorted_refs(),
    entry_refs=_sorted_refs(min_size=1),
    previous_bundle_refs=_sorted_refs(),
)
def test_root_hash_independent_of_bundle_id_and_producer(
    bundle_id_a, bundle_id_b, object_refs, blob_refs, entry_refs, previous_bundle_refs
):
    bundle_a = Bundle(bundle_id=bundle_id_a, object_refs=object_refs, blob_refs=blob_refs, entry_refs=entry_refs, previous_bundle_refs=previous_bundle_refs)
    bundle_b = Bundle(bundle_id=bundle_id_b, object_refs=object_refs, blob_refs=blob_refs, entry_refs=entry_refs, previous_bundle_refs=previous_bundle_refs)
    m_a = build_manifest(bundle_a, created_at="2026-01-01T00:00:00Z", producer={"name": "A"})
    m_b = build_manifest(bundle_b, created_at="2026-02-02T00:00:00Z", producer={"name": "B"})
    assert m_a.root_hash == m_b.root_hash


@given(
    bundle_id=st.text(min_size=1, max_size=20),
    object_refs=_sorted_refs(min_size=1, max_size=4),
    blob_refs=_sorted_refs(),
    entry_refs=_sorted_refs(min_size=1),
    previous_bundle_refs=_sorted_refs(),
)
def test_bundle_root_is_deterministic(bundle_id, object_refs, blob_refs, entry_refs, previous_bundle_refs):
    bundle = Bundle(bundle_id=bundle_id, object_refs=object_refs, blob_refs=blob_refs, entry_refs=entry_refs, previous_bundle_refs=previous_bundle_refs)
    manifest = build_manifest(bundle, created_at="2026-01-01T00:00:00Z")
    assert bundle_root(manifest) == bundle_root(manifest)


@given(
    bundle_id=st.text(min_size=1, max_size=20),
    object_refs=_sorted_refs(min_size=1, max_size=4),
    blob_refs=_sorted_refs(min_size=1, max_size=3),
    entry_refs=_sorted_refs(min_size=1),
    previous_bundle_refs=_sorted_refs(),
)
def test_bundle_root_changes_when_content_changes(bundle_id, object_refs, blob_refs, entry_refs, previous_bundle_refs):
    bundle = Bundle(bundle_id=bundle_id, object_refs=object_refs, blob_refs=blob_refs, entry_refs=entry_refs, previous_bundle_refs=previous_bundle_refs)
    manifest = build_manifest(bundle, created_at="2026-01-01T00:00:00Z")
    extra = _missing_ref(object_refs)
    all_refs = sorted(list(object_refs) + [extra])
    bundle2 = Bundle(bundle_id=bundle_id, object_refs=tuple(all_refs), blob_refs=blob_refs, entry_refs=entry_refs, previous_bundle_refs=previous_bundle_refs)
    manifest2 = build_manifest(bundle2, created_at="2026-01-01T00:00:00Z")
    assert bundle_root(manifest) != bundle_root(manifest2)
