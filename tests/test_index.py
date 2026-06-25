from __future__ import annotations

from pathlib import Path

import pytest

from popperpad.index import PadIndex
from popperpad.pad import PopperPad
from popperpad.schemas import SCHEMA_DOMAIN_V1, SCHEMA_EDGE_V1, SCHEMA_HYPOTHESIS_V1, SCHEMA_RECIPE_V1


def _pad_with_edges(tmp_path: Path) -> tuple[PopperPad, str, str, str]:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    domain = {"schema": SCHEMA_DOMAIN_V1, "domain_id": "A", "name": "A", "tags": []}
    domain_ref = pad.put_object(domain).obj_ref
    recipe = {"schema": SCHEMA_RECIPE_V1, "recipe_id": "r1", "argv": ["true"], "verdict_on_pass": "support"}
    recipe_ref = pad.put_object(recipe).obj_ref
    hyp = {"schema": SCHEMA_HYPOTHESIS_V1, "hypothesis_id": "h1", "title": "Test", "statement": {"lang": "en", "body": "test"}, "check_recipe_refs": [recipe_ref]}
    hyp_ref = pad.put_object(hyp).obj_ref
    ev_ref = "sha256:" + "e" * 64
    edge = {"schema": SCHEMA_EDGE_V1, "edge_type": "supports", "from_ref": ev_ref, "to_ref": hyp_ref, "evidence_refs": []}
    edge_ref = pad.put_object(edge).obj_ref
    return pad, hyp_ref, edge_ref, domain_ref


def test_index_rebuild_matches_incremental(tmp_path: Path) -> None:
    pad, hyp_ref, edge_ref, domain_ref = _pad_with_edges(tmp_path)
    idx = PadIndex()
    idx.rebuild_from_log(pad.log.iter_records())
    assert hyp_ref in idx.refs_by_schema(SCHEMA_HYPOTHESIS_V1)
    assert edge_ref in idx.refs_by_schema(SCHEMA_EDGE_V1)
    assert domain_ref in idx.refs_by_schema(SCHEMA_DOMAIN_V1)


def test_index_edges_by_target_is_o_k_not_o_n(tmp_path: Path) -> None:
    pad, hyp_ref, edge_ref, _ = _pad_with_edges(tmp_path)
    idx = PadIndex()
    idx.rebuild_from_log(pad.log.iter_records())
    edges = idx.edges_by_target(hyp_ref, object_lookup=pad.get_object)
    assert edge_ref in edges


def test_index_incremental_update_matches_rebuild(tmp_path: Path) -> None:
    pad, hyp_ref, edge_ref, domain_ref = _pad_with_edges(tmp_path)
    idx_incremental = PadIndex()
    for record in pad.log.iter_records():
        idx_incremental.on_record(record)
    idx_rebuild = PadIndex()
    idx_rebuild.rebuild_from_log(pad.log.iter_records())
    assert idx_incremental.refs_by_schema(SCHEMA_EDGE_V1) == idx_rebuild.refs_by_schema(SCHEMA_EDGE_V1)
    assert idx_incremental.edges_by_target(hyp_ref, object_lookup=pad.get_object) == idx_rebuild.edges_by_target(hyp_ref, object_lookup=pad.get_object)


def test_index_semantic_adjacency_for_bfs(tmp_path: Path) -> None:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    a = "sha256:" + "a" * 64
    b = "sha256:" + "b" * 64
    edge = {"schema": SCHEMA_EDGE_V1, "edge_type": "semantic", "from_ref": a, "to_ref": b, "tag": "≅", "obligations": [], "evidence_refs": []}
    edge_ref = pad.put_object(edge).obj_ref
    idx = PadIndex()
    idx.rebuild_from_log(pad.log.iter_records())
    adj = idx.semantic_adjacency(object_lookup=pad.get_object)
    assert (edge_ref, b) in adj.get(a, [])
    assert (edge_ref, a) in adj.get(b, [])  # symmetric for ≅


def test_index_ignores_non_object_records(tmp_path: Path) -> None:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    pad.put_blob(b"hello")
    idx = PadIndex()
    idx.rebuild_from_log(pad.log.iter_records())
    assert idx.refs_by_schema(SCHEMA_EDGE_V1) == set()
