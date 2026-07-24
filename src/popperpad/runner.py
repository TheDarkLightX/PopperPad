from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .cas import ContentAddressedStore
from .core.recipe import ArtifactPlan, InputSpec, ProcessObservation, RecipePlan, evaluate_observation, plan_recipe
from .core.result import Reject
from .core.values import FrozenDict, JsonValue, freeze_json
from .refs import CheckStatus, ValidationError


@dataclass(frozen=True, slots=True)
class RunRecipeResult:
    status: str  # PASS|FAIL|SKIP|TIMEOUT|ERROR
    reason: str
    exit_code: int | None
    stdout_ref: str
    stderr_ref: str
    outputs: tuple[FrozenDict[JsonValue], ...]
    toolchain: FrozenDict[JsonValue]
    duration_ms: int
    argv: tuple[str, ...]
    stdout_truncated: bool
    stderr_truncated: bool


def _frozen_json_map(value: Mapping[str, Any]) -> FrozenDict[JsonValue]:
    frozen = freeze_json(value)
    if not isinstance(frozen, FrozenDict):
        raise TypeError("expected object-shaped JSON value")
    return frozen


def _empty_toolchain() -> FrozenDict[JsonValue]:
    return _frozen_json_map({"executables": {}})


def _non_pass_result(
    status: CheckStatus,
    reason: str,
    *,
    toolchain: FrozenDict[JsonValue] | None = None,
    duration_ms: int = 0,
    argv: tuple[str, ...] = (),
) -> RunRecipeResult:
    return RunRecipeResult(
        status=status.value,
        reason=reason,
        exit_code=None,
        stdout_ref="",
        stderr_ref="",
        outputs=(),
        toolchain=toolchain or _empty_toolchain(),
        duration_ms=duration_ms,
        argv=argv,
        stdout_truncated=False,
        stderr_truncated=False,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _materialize_input(
    *, cas: ContentAddressedStore, spec: InputSpec, bindings: Mapping[str, str]
) -> bytes:
    if spec.kind == "ref":
        return cas.get_bytes(spec.value)
    if spec.kind == "text":
        return spec.value.encode("utf-8")
    if spec.kind == "binding":
        ref = bindings.get(spec.value, "")
        if not ref:
            raise ValidationError(f"missing binding: {spec.value}")
        return cas.get_bytes(ref)
    raise ValidationError(f"unsupported input spec kind: {spec.kind}")


def _materialize_files(
    *, cas: ContentAddressedStore, plan: RecipePlan, bindings: Mapping[str, str], work: Path
) -> None:
    for name, spec in plan.files.items_tuple():
        data = _materialize_input(cas=cas, spec=spec, bindings=bindings)
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _materialize_stdin(
    *, cas: ContentAddressedStore, plan: RecipePlan, bindings: Mapping[str, str]
) -> bytes | None:
    if plan.stdin is None:
        return None
    return _materialize_input(cas=cas, spec=plan.stdin, bindings=bindings)


def _build_env(plan: RecipePlan, work: Path) -> dict[str, str]:
    """Construct a minimal explicit environment instead of inheriting secrets."""

    env: dict[str, str] = {
        "HOME": str(work),
        "TMPDIR": str(work),
        "PYTHONHASHSEED": "0",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    for key in ("PATH", "SYSTEMROOT", "WINDIR"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    for key, value in plan.env.items_tuple():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def _check_requires(plan: RecipePlan) -> RunRecipeResult | None:
    for executable in plan.requires:
        if shutil.which(executable) is None:
            return _non_pass_result(CheckStatus.SKIP, f"missing required executable: {executable}")
    return None


def _check_requires_paths(plan: RecipePlan, repo_root: Path | None) -> RunRecipeResult | None:
    base = Path(repo_root) if repo_root is not None else None
    for raw_path in plan.requires_paths:
        candidate = Path(raw_path)
        if not candidate.is_absolute() and base is not None:
            candidate = base / candidate
        if not candidate.exists():
            return _non_pass_result(CheckStatus.SKIP, f"missing required path: {raw_path}")
    return None


def _resolve_exe_path(executable: str, work: Path) -> str | None:
    candidate = Path(executable)
    if candidate.is_absolute():
        return str(candidate) if candidate.exists() else None
    if "/" in executable or "\\" in executable:
        resolved = (work / executable).resolve()
        return str(resolved) if resolved.exists() else None
    found = shutil.which(executable)
    return str(Path(found).resolve()) if found else None


def _toolchain_entry(executable_path: str) -> dict[str, JsonValue]:
    try:
        return {"path": executable_path, "sha256": _sha256_file(Path(executable_path))}
    except Exception as exc:
        return {"path": executable_path, "error": f"{type(exc).__name__}: {exc}"}


def _resolve_toolchain(argv: tuple[str, ...], requires: tuple[str, ...], work: Path) -> FrozenDict[JsonValue]:
    executable_names = tuple(dict.fromkeys((argv[0], *requires)))
    entries: dict[str, JsonValue] = {}
    for executable in executable_names:
        path = _resolve_exe_path(executable, work)
        if path:
            entries[executable] = _frozen_json_map(_toolchain_entry(path))
    return _frozen_json_map({"executables": entries})


def _kill_process_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        return
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _run_process(
    *,
    argv: tuple[str, ...],
    cwd: Path,
    env: dict[str, str],
    stdin_bytes: bytes | None,
    timeout_ms: int,
    toolchain: FrozenDict[JsonValue],
) -> tuple[int, bytes, bytes, int] | RunRecipeResult:
    start = time.monotonic()
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
    except FileNotFoundError as exc:
        return _non_pass_result(
            CheckStatus.SKIP,
            f"executable not found: {exc.filename}",
            toolchain=toolchain,
            argv=argv,
        )
    except Exception as exc:
        return _non_pass_result(
            CheckStatus.ERROR,
            f"{type(exc).__name__}: {exc}",
            toolchain=toolchain,
            duration_ms=int((time.monotonic() - start) * 1000),
            argv=argv,
        )

    try:
        stdout, stderr = process.communicate(input=stdin_bytes, timeout=timeout_ms / 1000.0)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        stdout, stderr = process.communicate()
        return _non_pass_result(
            CheckStatus.TIMEOUT,
            f"timeout after {timeout_ms}ms",
            toolchain=toolchain,
            duration_ms=int((time.monotonic() - start) * 1000),
            argv=argv,
        )
    except Exception as exc:
        _kill_process_tree(process)
        process.communicate()
        return _non_pass_result(
            CheckStatus.ERROR,
            f"{type(exc).__name__}: {exc}",
            toolchain=toolchain,
            duration_ms=int((time.monotonic() - start) * 1000),
            argv=argv,
        )

    return int(process.returncode), stdout or b"", stderr or b"", int((time.monotonic() - start) * 1000)


def _is_inside_worktree(path: Path, work: Path) -> bool:
    try:
        path.resolve().relative_to(work.resolve())
        return True
    except (OSError, ValueError):
        return False


def _capture_file(
    *,
    name: str,
    relative_path: str,
    media_type: str,
    max_bytes: int,
    work: Path,
    cas: ContentAddressedStore,
) -> FrozenDict[JsonValue] | None:
    path = work / relative_path
    if not path.exists() or not path.is_file() or not _is_inside_worktree(path, work):
        return None
    size = path.stat().st_size
    with path.open("rb") as handle:
        data = handle.read(max_bytes)
    ref = cas.put_bytes(data).ref
    return _frozen_json_map(
        {
            "name": name,
            "ref": ref,
            "bytes": size,
            "truncated": size > max_bytes,
            "path": relative_path,
            "media_type": media_type,
        }
    )


def _capture_outputs(plan: RecipePlan, work: Path, cas: ContentAddressedStore) -> tuple[FrozenDict[JsonValue], ...]:
    outputs: list[FrozenDict[JsonValue]] = []
    for relative_path in plan.capture_paths:
        captured = _capture_file(
            name=relative_path,
            relative_path=relative_path,
            media_type="application/octet-stream",
            max_bytes=plan.max_capture_bytes,
            work=work,
            cas=cas,
        )
        if captured is not None:
            outputs.append(captured)
    for artifact_id, artifact in plan.artifacts.items_tuple():
        assert isinstance(artifact, ArtifactPlan)
        captured = _capture_file(
            name=artifact_id,
            relative_path=artifact.path,
            media_type=artifact.media_type,
            max_bytes=artifact.max_bytes or plan.max_capture_bytes,
            work=work,
            cas=cas,
        )
        if captured is not None:
            outputs.append(captured)
    return tuple(outputs)


def _existing_expected_paths(plan: RecipePlan, work: Path) -> frozenset[str]:
    candidates = (*plan.expectations.files_exist, *plan.expectations.files_not_exist)
    return frozenset(path for path in candidates if (work / path).exists())


def run_recipe(
    *,
    cas: ContentAddressedStore,
    recipe: Mapping[str, Any],
    bindings: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> RunRecipeResult:
    """Interpret one immutable recipe plan in the imperative process shell."""

    planned = plan_recipe(recipe)
    if isinstance(planned, Reject):
        field = planned.details.get("field", "recipe")
        reason = planned.details.get("reason", planned.code)
        return _non_pass_result(CheckStatus.ERROR, f"{field}: {reason}")
    plan = planned
    bindings = dict(bindings or {})

    skipped = _check_requires(plan)
    if skipped is not None:
        return skipped
    skipped = _check_requires_paths(plan, repo_root)
    if skipped is not None:
        return skipped

    with tempfile.TemporaryDirectory(prefix="popperpad_recipe_") as temporary_directory:
        work = Path(temporary_directory)
        try:
            _materialize_files(cas=cas, plan=plan, bindings=bindings, work=work)
            stdin_bytes = _materialize_stdin(cas=cas, plan=plan, bindings=bindings)
        except Exception as exc:
            return _non_pass_result(CheckStatus.ERROR, f"input materialization failed: {type(exc).__name__}: {exc}")

        argv = tuple(sys.executable if arg == "${PYTHON}" else arg for arg in plan.argv)
        toolchain = _resolve_toolchain(argv, plan.requires, work)
        execution = _run_process(
            argv=argv,
            cwd=work,
            env=_build_env(plan, work),
            stdin_bytes=stdin_bytes,
            timeout_ms=plan.timeout_ms,
            toolchain=toolchain,
        )
        if isinstance(execution, RunRecipeResult):
            return execution

        exit_code, stdout_full, stderr_full, duration_ms = execution
        stdout_truncated = len(stdout_full) > plan.max_output_bytes
        stderr_truncated = len(stderr_full) > plan.max_output_bytes
        stdout = stdout_full[: plan.max_output_bytes]
        stderr = stderr_full[: plan.max_output_bytes]
        stdout_ref = cas.put_bytes(stdout).ref if stdout else ""
        stderr_ref = cas.put_bytes(stderr).ref if stderr else ""

        observation = ProcessObservation(
            exit_code=exit_code,
            stdout_text=stdout.decode("utf-8", errors="ignore"),
            stderr_text=stderr.decode("utf-8", errors="ignore"),
            existing_paths=_existing_expected_paths(plan, work),
        )
        evaluation = evaluate_observation(plan, observation)
        outputs = _capture_outputs(plan, work, cas)
        return RunRecipeResult(
            status=evaluation.status,
            reason=evaluation.reason,
            exit_code=exit_code,
            stdout_ref=stdout_ref,
            stderr_ref=stderr_ref,
            outputs=outputs,
            toolchain=toolchain,
            duration_ms=duration_ms,
            argv=argv,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
