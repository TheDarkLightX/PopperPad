from __future__ import annotations

from typing import Any, Callable, Mapping

from .refs import ValidationError, is_ref, require, require_list, require_ref, require_str
from .schemas import (
    SCHEMA_ARTIFACT_V1,
    SCHEMA_CHECKPOINT_V1,
    SCHEMA_CONTEXT_V1,
    SCHEMA_DOMAIN_V1,
    SCHEMA_EDGE_V1,
    SCHEMA_EVIDENCE_V1,
    SCHEMA_GAMIFICATION_QUEST_V1,
    SCHEMA_GAMIFICATION_SCORE_EVENT_V1,
    SCHEMA_HYPOTHESIS_V1,
    SCHEMA_MARKET_RESOURCE_BUDGET_V1,
    SCHEMA_MARKET_WORK_ORDER_V1,
    SCHEMA_RECIPE_V1,
    SCHEMA_TRUTH_CERTIFICATE_V1,
)

import re

_TAG_RE = re.compile(r"^[A-Za-z0-9_\-./:]{1,64}$")
_EDGE_TYPES = {"supports", "refutes", "supersedes", "depends_on", "topic", "semantic"}
_SEMANTIC_TAGS = {"≅", "↦", "⊑", "⊒", "~"}
_RECIPE_VERDICTS = {"support", "refute", "neutral"}
_MARKET_TASK_TYPES = {
    "proof",
    "counterexample",
    "reproduction",
    "boundary",
    "formalization",
    "recipe_maintenance",
    "artifact_availability",
    "curation",
    "forecast",
    "verifier_improvement",
}
_PAYOUT_CONDITIONS = {
    "verifier_passes",
    "valid_counterexample",
    "independent_reproduction",
    "boundary_certificate",
    "maintenance_accepted",
    "artifact_retrieval_passes",
    "curation_used",
}
_MARKET_ACCESS_PATHS = {"pay", "earn", "grant", "local"}
_RESOURCE_LIMIT_KEYS = {"compute", "storage", "api", "verifier", "retrieval"}
_SCORE_EVENT_KINDS = {
    "proof_accepted",
    "counterexample_verified",
    "reproduction_completed",
    "boundary_found",
    "recipe_maintained",
    "artifact_preserved",
    "curation_used",
    "quest_completed",
}
_POINT_KINDS = {"xp", "reputation", "season_score", "badge", "streak"}
_QUEST_TYPES = {
    "proof",
    "counterexample",
    "reproduction",
    "boundary",
    "maintenance",
    "storage",
    "curation",
    "season",
}
_TRUTH_CERTIFICATE_KINDS = {
    "proof",
    "refutation",
    "reproduction",
    "boundary",
    "formalization",
    "verifier_improvement",
}
_TRUTH_CERTIFICATE_STATUSES = {
    "supported",
    "refuted",
    "reproduced",
    "narrowed",
    "formalized",
    "maintained",
}


def require_mapping(value: Any, message: str) -> None:
    require(isinstance(value, Mapping), message)


def _require_ref_list(items: Any, message: str) -> None:
    require_list(items, message)
    for item in items:
        require_ref(item, message)


def _require_str_list(items: Any, message: str) -> None:
    require_list(items, message)
    for item in items:
        require_str(item, message)


def _require_tags(tags: Any, message: str) -> None:
    require_list(tags, message)
    for tag in tags:
        require_str(tag, message)
        require(bool(_TAG_RE.match(tag)), message)


def _optional_ref(obj: Mapping[str, Any], key: str, message: str) -> None:
    if obj.get(key) is not None:
        require_ref(obj.get(key), message)


def _require_positive_int(value: Any, message: str) -> None:
    require(isinstance(value, int) and not isinstance(value, bool) and value > 0, message)


def _require_nonneg_int(value: Any, message: str) -> None:
    require(isinstance(value, int) and not isinstance(value, bool) and value >= 0, message)


def _require_nonneg_number(value: Any, message: str) -> None:
    require(isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0, message)


def _require_file_spec(spec: Any, message: str) -> None:
    require_mapping(spec, message)
    if "ref" in spec:
        require_ref(spec.get("ref"), "file spec ref must be sha256:<64hex>")
        return
    if "text" in spec:
        require_str(spec.get("text"), "file spec text must be a string")
        return
    if "binding" in spec:
        require_str(spec.get("binding"), "file spec binding must be a string")
        return
    raise ValidationError("file spec must contain one of: ref, text, binding")


def _validate_domain(obj: Mapping[str, Any]) -> None:
    require_str(obj.get("domain_id"), "domain.domain_id must be a string")
    require_str(obj.get("name"), "domain.name must be a string")
    _require_tags(obj.get("tags", []), "domain.tags contains an invalid tag")


def _validate_context(obj: Mapping[str, Any]) -> None:
    require_str(obj.get("context_key"), "context.context_key must be a string")
    _optional_ref(obj, "domain_ref", "context.domain_ref must be sha256:<64hex>")
    toolchain = obj.get("toolchain", {})
    if toolchain:
        require_mapping(toolchain, "context.toolchain must be an object")
        require_str(toolchain.get("name"), "context.toolchain.name must be a string")
        require_ref(toolchain.get("digest"), "context.toolchain.digest must be sha256:<64hex>")
    harness = obj.get("harness", {})
    if harness:
        require_mapping(harness, "context.harness must be an object")
        require_str(harness.get("id"), "context.harness.id must be a string")
        require_ref(harness.get("digest"), "context.harness.digest must be sha256:<64hex>")


def _validate_recipe(obj: Mapping[str, Any]) -> None:
    require_str(obj.get("recipe_id", ""), "recipe.recipe_id must be a string")
    argv = obj.get("argv")
    require_list(argv, "recipe.argv must be a list")
    require(len(argv) > 0, "recipe.argv must be non-empty")
    _require_str_list(argv, "recipe.argv items must be strings")

    verdict = obj.get("verdict_on_pass", "support")
    require_str(verdict, "recipe.verdict_on_pass must be a string")
    require(verdict in _RECIPE_VERDICTS, f"recipe.verdict_on_pass must be one of {sorted(_RECIPE_VERDICTS)}")

    _require_str_list(obj.get("requires", []), "recipe.requires items must be strings")
    _require_str_list(obj.get("requires_paths", []), "recipe.requires_paths items must be strings")

    require_mapping(obj.get("env", {}), "recipe.env must be an object")

    files = obj.get("files", {})
    require_mapping(files, "recipe.files must be an object")
    for name, spec in files.items():
        require_str(name, "recipe.files keys must be strings")
        _require_file_spec(spec, "recipe.files values must be file specs")

    stdin = obj.get("stdin")
    if stdin is not None:
        _require_file_spec(stdin, "recipe.stdin must be a file spec")

    if "timeout_ms" in obj:
        _require_positive_int(obj.get("timeout_ms"), "recipe.timeout_ms must be a positive int")
    if "max_output_bytes" in obj:
        _require_positive_int(obj.get("max_output_bytes"), "recipe.max_output_bytes must be a positive int")
    if "max_capture_bytes" in obj:
        _require_positive_int(obj.get("max_capture_bytes"), "recipe.max_capture_bytes must be a positive int")

    _validate_expect(obj.get("expect", {}))
    _require_str_list(obj.get("capture_paths", []), "recipe.capture_paths items must be strings")
    _validate_artifacts(obj.get("artifacts", {}))


def _validate_expect(expect: Any) -> None:
    require_mapping(expect, "recipe.expect must be an object")
    string_fields = (
        ("stdout_contains", "recipe.expect.stdout_contains must be a string"),
        ("stderr_contains", "recipe.expect.stderr_contains must be a string"),
        ("stdout_not_contains", "recipe.expect.stdout_not_contains must be a string"),
        ("stderr_not_contains", "recipe.expect.stderr_not_contains must be a string"),
        ("stdout_regex", "recipe.expect.stdout_regex must be a string"),
        ("stderr_regex", "recipe.expect.stderr_regex must be a string"),
    )
    for key, message in string_fields:
        if key in expect:
            require_str(expect.get(key), message)
    if "exit_code" in expect:
        require(isinstance(expect.get("exit_code"), int), "recipe.expect.exit_code must be an int")
    for key in ("files_exist", "files_not_exist"):
        if key in expect:
            _require_str_list(expect.get(key), f"recipe.expect.{key} items must be strings")


def _validate_artifacts(artifacts: Any) -> None:
    require_mapping(artifacts, "recipe.artifacts must be an object")
    for aid, spec in artifacts.items():
        require_str(aid, "recipe.artifacts keys must be strings")
        require_mapping(spec, "recipe.artifacts values must be objects")
        require_str(spec.get("path"), "recipe.artifacts[*].path must be a string")
        if "max_bytes" in spec:
            _require_positive_int(spec.get("max_bytes"), "recipe.artifacts[*].max_bytes must be a positive int")
        if "media_type" in spec:
            require_str(spec.get("media_type"), "recipe.artifacts[*].media_type must be a string")


def _validate_hypothesis(obj: Mapping[str, Any]) -> None:
    require_str(obj.get("hypothesis_id"), "hypothesis.hypothesis_id must be a string")
    require_str(obj.get("title"), "hypothesis.title must be a string")
    require_str(obj.get("kind", "other"), "hypothesis.kind must be a string")
    statement = obj.get("statement")
    require_mapping(statement, "hypothesis.statement must be an object")
    require_str(statement.get("lang"), "hypothesis.statement.lang must be a string")
    require_str(statement.get("body"), "hypothesis.statement.body must be a string")
    _require_tags(obj.get("tags", []), "hypothesis.tags contains an invalid tag")
    _optional_ref(obj, "domain_ref", "hypothesis.domain_ref must be sha256:<64hex>")
    _optional_ref(obj, "context_ref", "hypothesis.context_ref must be sha256:<64hex>")
    checks = obj.get("check_recipe_refs", [])
    require_list(checks, "hypothesis.check_recipe_refs must be a list")
    require(len(checks) > 0, "hypothesis must include at least one check recipe (falsifiability gate)")
    _require_ref_list(checks, "hypothesis.check_recipe_refs must contain sha256:<64hex>")


def _validate_evidence(obj: Mapping[str, Any]) -> None:
    require_str(obj.get("evidence_kind"), "evidence.evidence_kind must be a string")
    require_ref(obj.get("recipe_ref"), "evidence.recipe_ref must be sha256:<64hex>")
    _optional_ref(obj, "context_ref", "evidence.context_ref must be sha256:<64hex>")
    _require_ref_list(obj.get("subject_refs", []), "evidence.subject_refs must contain sha256:<64hex>")

    result = obj.get("result", {})
    require_mapping(result, "evidence.result must be an object")
    require_str(result.get("status"), "evidence.result.status must be a string")
    if result.get("exit_code") is not None:
        require(isinstance(result.get("exit_code"), int), "evidence.result.exit_code must be an int or null")

    if obj.get("stdout_ref"):
        require_ref(obj.get("stdout_ref"), "evidence.stdout_ref must be sha256:<64hex>")
    if obj.get("stderr_ref"):
        require_ref(obj.get("stderr_ref"), "evidence.stderr_ref must be sha256:<64hex>")

    outputs = obj.get("outputs", [])
    require_list(outputs, "evidence.outputs must be a list")
    for out in outputs:
        require_mapping(out, "evidence.outputs items must be objects")
        require_str(out.get("name"), "evidence.outputs[*].name must be a string")
        require_ref(out.get("ref"), "evidence.outputs[*].ref must be sha256:<64hex>")

    if "argv" in obj:
        _require_str_list(obj.get("argv"), "evidence.argv items must be strings")
    if "duration_ms" in obj:
        _require_nonneg_int(obj.get("duration_ms"), "evidence.duration_ms must be an int >= 0")
    for key in ("stdout_truncated", "stderr_truncated"):
        if key in obj:
            require(isinstance(obj.get(key), bool), f"evidence.{key} must be a bool")
    _validate_toolchain(obj.get("toolchain", {}))


def _validate_toolchain(toolchain: Any) -> None:
    if not toolchain:
        return
    require_mapping(toolchain, "evidence.toolchain must be an object")
    executables = toolchain.get("executables", {})
    require_mapping(executables, "evidence.toolchain.executables must be an object")
    for value in executables.values():
        require_mapping(value, "evidence.toolchain.executables values must be objects")
        require_str(value.get("path"), "evidence.toolchain.executables[*].path must be a string")
        digest = value.get("sha256", "")
        if digest:
            require_ref(digest, "evidence.toolchain.executables[*].sha256 must be sha256:<64hex>")


def _validate_artifact(obj: Mapping[str, Any]) -> None:
    require_str(obj.get("name"), "artifact.name must be a string")
    require_str(obj.get("kind"), "artifact.kind must be a string")
    require_str(obj.get("media_type"), "artifact.media_type must be a string")
    require_ref(obj.get("blob_ref"), "artifact.blob_ref must be sha256:<64hex>")


def _validate_edge(obj: Mapping[str, Any]) -> None:
    edge_type = obj.get("edge_type")
    require_str(edge_type, "edge.edge_type must be a string")
    require(edge_type in _EDGE_TYPES, f"edge.edge_type must be one of {sorted(_EDGE_TYPES)}")
    require_ref(obj.get("from_ref"), "edge.from_ref must be sha256:<64hex>")
    require_ref(obj.get("to_ref"), "edge.to_ref must be sha256:<64hex>")
    _optional_ref(obj, "context_ref", "edge.context_ref must be sha256:<64hex>")
    if edge_type == "semantic":
        _validate_semantic_edge(obj)
    _require_ref_list(obj.get("evidence_refs", []), "edge.evidence_refs must contain sha256:<64hex>")


def _validate_semantic_edge(obj: Mapping[str, Any]) -> None:
    tag = obj.get("tag")
    require_str(tag, "edge.tag must be a string for semantic edges")
    require(tag in _SEMANTIC_TAGS, f"edge.tag must be one of {sorted(_SEMANTIC_TAGS)}")
    obligations = obj.get("obligations", [])
    require_list(obligations, "edge.obligations must be a list")
    for obligation in obligations:
        require_mapping(obligation, "edge.obligations items must be objects")
        require_str(obligation.get("obligation_id"), "obligation.obligation_id must be a string")
        require_ref(obligation.get("recipe_ref"), "obligation.recipe_ref must be sha256:<64hex>")


def _validate_checkpoint(obj: Mapping[str, Any]) -> None:
    require_str(obj.get("created_at"), "checkpoint.created_at must be a string")
    require_str(obj.get("log_head"), "checkpoint.log_head must be a string")
    if obj.get("log_head"):
        require_ref(obj.get("log_head"), "checkpoint.log_head must be sha256:<64hex>")
    require(isinstance(obj.get("event_count"), int), "checkpoint.event_count must be an int")


def _validate_truth_certificate(obj: Mapping[str, Any]) -> None:
    require_str(obj.get("certificate_id"), "truth certificate certificate_id must be a string")
    certificate_kind = obj.get("certificate_kind")
    require_str(certificate_kind, "truth certificate certificate_kind must be a string")
    require(
        certificate_kind in _TRUTH_CERTIFICATE_KINDS,
        f"truth certificate certificate_kind must be one of {sorted(_TRUTH_CERTIFICATE_KINDS)}",
    )
    require_ref(obj.get("claim_ref"), "truth certificate claim_ref must be sha256:<64hex>")
    _optional_ref(obj, "context_ref", "truth certificate context_ref must be sha256:<64hex>")
    require_ref(obj.get("verifier_ref"), "truth certificate verifier_ref must be sha256:<64hex>")
    _optional_ref(obj, "recipe_ref", "truth certificate recipe_ref must be sha256:<64hex>")
    _require_ref_list(
        obj.get("evidence_refs", []),
        "truth certificate evidence_refs must contain sha256:<64hex>",
    )
    require(
        len(obj.get("evidence_refs", [])) > 0,
        "truth certificate evidence_refs must be non-empty",
    )
    _require_ref_list(
        obj.get("artifact_refs", []),
        "truth certificate artifact_refs must contain sha256:<64hex>",
    )
    verifier_result = obj.get("verifier_result")
    require_mapping(verifier_result, "truth certificate verifier_result must be an object")
    require(
        verifier_result.get("accepted") is True,
        "truth certificate verifier_result.accepted must be true",
    )
    status = verifier_result.get("status")
    require_str(status, "truth certificate verifier_result.status must be a string")
    require(
        status in _TRUTH_CERTIFICATE_STATUSES,
        f"truth certificate verifier_result.status must be one of {sorted(_TRUTH_CERTIFICATE_STATUSES)}",
    )
    _require_str_list(obj.get("signatures", []), "truth certificate signatures items must be strings")
    require(
        obj.get("truth_boundary") == "verifier_checked_certificate",
        "truth certificate truth_boundary must be verifier_checked_certificate",
    )


def _validate_market_work_order(obj: Mapping[str, Any]) -> None:
    task_type = obj.get("task_type")
    require_str(task_type, "market work order task_type must be a string")
    require(
        task_type in _MARKET_TASK_TYPES,
        f"market work order task_type must be one of {sorted(_MARKET_TASK_TYPES)}",
    )
    require_ref(obj.get("claim_ref"), "market work order claim_ref must be sha256:<64hex>")
    _optional_ref(obj, "context_ref", "market work order context_ref must be sha256:<64hex>")
    _require_ref_list(
        obj.get("accepted_recipe_refs", []),
        "market work order accepted_recipe_refs must contain sha256:<64hex>",
    )
    _require_ref_list(
        obj.get("accepted_verifier_refs", []),
        "market work order accepted_verifier_refs must contain sha256:<64hex>",
    )
    require_str(obj.get("max_payout"), "market work order max_payout must be a string")
    require_str(obj.get("min_bond"), "market work order min_bond must be a string")
    require_str(obj.get("deadline"), "market work order deadline must be a string")
    if "payout_condition" in obj:
        payout_condition = obj.get("payout_condition")
        require_str(payout_condition, "market work order payout_condition must be a string")
        require(
            payout_condition in _PAYOUT_CONDITIONS,
            f"market work order payout_condition must be one of {sorted(_PAYOUT_CONDITIONS)}",
        )
    _require_nonneg_int(
        obj.get("challenge_window_seconds"),
        "market work order challenge_window_seconds must be an int >= 0",
    )
    scoring = obj.get("scoring", {})
    require_mapping(scoring, "market work order scoring must be an object")
    for key, value in scoring.items():
        require_str(key, "market work order scoring keys must be strings")
        _require_nonneg_number(value, "market work order scoring values must be numbers >= 0")


def _validate_market_resource_budget(obj: Mapping[str, Any]) -> None:
    require_str(obj.get("budget_id"), "market resource budget budget_id must be a string")
    _optional_ref(obj, "work_order_ref", "market resource budget work_order_ref must be sha256:<64hex>")
    require_str(obj.get("payer_ref"), "market resource budget payer_ref must be a string")
    assets = obj.get("settlement_assets", [])
    _require_str_list(assets, "market resource budget settlement_assets items must be strings")
    require(len(assets) > 0, "market resource budget settlement_assets must be non-empty")

    limits = obj.get("limits")
    require_mapping(limits, "market resource budget limits must be an object")
    require(len(limits) > 0, "market resource budget limits must be non-empty")
    for key, value in limits.items():
        require_str(key, "market resource budget limits keys must be strings")
        require(key in _RESOURCE_LIMIT_KEYS, f"market resource budget limits keys must be one of {sorted(_RESOURCE_LIMIT_KEYS)}")
        require_str(value, "market resource budget limits values must be strings")

    access_paths = obj.get("access_paths", [])
    require_list(access_paths, "market resource budget access_paths must be a list")
    require(len(access_paths) > 0, "market resource budget access_paths must be non-empty")
    for path in access_paths:
        require_str(path, "market resource budget access_paths items must be strings")
        require(
            path in _MARKET_ACCESS_PATHS,
            f"market resource budget access_paths must be one of {sorted(_MARKET_ACCESS_PATHS)}",
        )

    model_policy = obj.get("model_policy", {})
    require_mapping(model_policy, "market resource budget model_policy must be an object")
    if "cheap_model_first" in model_policy:
        require(
            isinstance(model_policy.get("cheap_model_first"), bool),
            "market resource budget model_policy.cheap_model_first must be a bool",
        )
    if "max_paid_escalations" in model_policy:
        _require_nonneg_int(
            model_policy.get("max_paid_escalations"),
            "market resource budget model_policy.max_paid_escalations must be an int >= 0",
        )
    require(
        obj.get("truth_boundary") == "resource_funding_only",
        "market resource budget truth_boundary must be resource_funding_only",
    )


def _validate_score_event(obj: Mapping[str, Any]) -> None:
    require_str(obj.get("event_id"), "score event event_id must be a string")
    require_str(obj.get("agent_ref"), "score event agent_ref must be a string")
    event_kind = obj.get("event_kind")
    require_str(event_kind, "score event event_kind must be a string")
    require(event_kind in _SCORE_EVENT_KINDS, f"score event event_kind must be one of {sorted(_SCORE_EVENT_KINDS)}")
    point_kind = obj.get("point_kind")
    require_str(point_kind, "score event point_kind must be a string")
    require(point_kind in _POINT_KINDS, f"score event point_kind must be one of {sorted(_POINT_KINDS)}")
    require(
        isinstance(obj.get("point_delta"), int) and not isinstance(obj.get("point_delta"), bool),
        "score event point_delta must be an int",
    )
    require_ref(obj.get("subject_ref"), "score event subject_ref must be sha256:<64hex>")
    _optional_ref(obj, "domain_ref", "score event domain_ref must be sha256:<64hex>")
    evidence_refs = obj.get("evidence_refs", [])
    _require_ref_list(evidence_refs, "score event evidence_refs must contain sha256:<64hex>")
    require(len(evidence_refs) > 0, "score event evidence_refs must be non-empty")
    token_reward = obj.get("token_reward")
    if token_reward is not None:
        require_str(token_reward, "score event token_reward must be a string")
    _validate_anti_abuse(obj.get("anti_abuse", {}))
    require(obj.get("truth_boundary") == "gamification_only", "score event truth_boundary must be gamification_only")


def _validate_anti_abuse(anti_abuse: Any) -> None:
    require_mapping(anti_abuse, "score event anti_abuse must be an object")
    if "verifier_required" in anti_abuse:
        require(
            isinstance(anti_abuse.get("verifier_required"), bool),
            "score event anti_abuse.verifier_required must be a bool",
        )
    if "sybil_risk" in anti_abuse:
        _require_nonneg_number(
            anti_abuse.get("sybil_risk"),
            "score event anti_abuse.sybil_risk must be a number >= 0",
        )


def _validate_quest(obj: Mapping[str, Any]) -> None:
    require_str(obj.get("quest_id"), "quest quest_id must be a string")
    require_str(obj.get("title"), "quest title must be a string")
    quest_type = obj.get("quest_type")
    require_str(quest_type, "quest quest_type must be a string")
    require(quest_type in _QUEST_TYPES, f"quest quest_type must be one of {sorted(_QUEST_TYPES)}")
    _optional_ref(obj, "domain_ref", "quest domain_ref must be sha256:<64hex>")
    objective = obj.get("objective")
    require_mapping(objective, "quest objective must be an object")
    require_str(objective.get("summary"), "quest objective.summary must be a string")
    if objective.get("target_ref") is not None:
        require_ref(objective.get("target_ref"), "quest objective.target_ref must be sha256:<64hex>")
    accepted_event_kinds = obj.get("accepted_event_kinds", [])
    require_list(accepted_event_kinds, "quest accepted_event_kinds must be a list")
    require(len(accepted_event_kinds) > 0, "quest accepted_event_kinds must be non-empty")
    for event_kind in accepted_event_kinds:
        require_str(event_kind, "quest accepted_event_kinds items must be strings")
        require(
            event_kind in _SCORE_EVENT_KINDS,
            f"quest accepted_event_kinds must be one of {sorted(_SCORE_EVENT_KINDS)}",
        )
    _validate_quest_rewards(obj.get("rewards", {}))
    _validate_quest_completion(obj.get("completion", {}))
    _validate_quest_anti_abuse(obj.get("anti_abuse", {}))
    require(obj.get("truth_boundary") == "gamification_only", "quest truth_boundary must be gamification_only")


def _validate_quest_rewards(rewards: Any) -> None:
    require_mapping(rewards, "quest rewards must be an object")
    points = rewards.get("points", {})
    require_mapping(points, "quest rewards.points must be an object")
    require(len(points) > 0, "quest rewards.points must be non-empty")
    for point_kind, point_value in points.items():
        require_str(point_kind, "quest rewards.points keys must be strings")
        require(point_kind in _POINT_KINDS, f"quest rewards.points keys must be one of {sorted(_POINT_KINDS)}")
        require(
            isinstance(point_value, int) and not isinstance(point_value, bool) and point_value >= 0,
            "quest rewards.points values must be ints >= 0",
        )
    if rewards.get("token_budget_ref") is not None:
        require_ref(rewards.get("token_budget_ref"), "quest rewards.token_budget_ref must be sha256:<64hex>")


def _validate_quest_completion(completion: Any) -> None:
    require_mapping(completion, "quest completion must be an object")
    required_evidence_count = completion.get("required_evidence_count", 1)
    require(
        isinstance(required_evidence_count, int)
        and not isinstance(required_evidence_count, bool)
        and required_evidence_count > 0,
        "quest completion.required_evidence_count must be an int > 0",
    )
    if completion.get("deadline") is not None:
        require_str(completion.get("deadline"), "quest completion.deadline must be a string")


def _validate_quest_anti_abuse(anti_abuse: Any) -> None:
    require_mapping(anti_abuse, "quest anti_abuse must be an object")
    if "max_rewards_per_agent" in anti_abuse:
        max_rewards = anti_abuse.get("max_rewards_per_agent")
        require(
            isinstance(max_rewards, int) and not isinstance(max_rewards, bool) and max_rewards > 0,
            "quest anti_abuse.max_rewards_per_agent must be an int > 0",
        )
    if "requires_independent_reproduction" in anti_abuse:
        require(
            isinstance(anti_abuse.get("requires_independent_reproduction"), bool),
            "quest anti_abuse.requires_independent_reproduction must be a bool",
        )


VALIDATORS: dict[str, Callable[[Mapping[str, Any]], None]] = {
    SCHEMA_DOMAIN_V1: _validate_domain,
    SCHEMA_CONTEXT_V1: _validate_context,
    SCHEMA_RECIPE_V1: _validate_recipe,
    SCHEMA_HYPOTHESIS_V1: _validate_hypothesis,
    SCHEMA_EVIDENCE_V1: _validate_evidence,
    SCHEMA_ARTIFACT_V1: _validate_artifact,
    SCHEMA_EDGE_V1: _validate_edge,
    SCHEMA_CHECKPOINT_V1: _validate_checkpoint,
    SCHEMA_TRUTH_CERTIFICATE_V1: _validate_truth_certificate,
    SCHEMA_MARKET_WORK_ORDER_V1: _validate_market_work_order,
    SCHEMA_MARKET_RESOURCE_BUDGET_V1: _validate_market_resource_budget,
    SCHEMA_GAMIFICATION_SCORE_EVENT_V1: _validate_score_event,
    SCHEMA_GAMIFICATION_QUEST_V1: _validate_quest,
}


def validate_object(obj: Any) -> None:
    require_mapping(obj, "object must be a JSON object")
    schema = obj.get("schema")
    require_str(schema, "object.schema must be a string")
    validator = VALIDATORS.get(str(schema))
    if validator is None:
        raise ValidationError(f"unknown schema: {schema}")
    validator(obj)
