from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from .cas import ContentAddressedStore
from .refs import CheckStatus, ValidationError, require


def _safe_relpath(path: str) -> str:
    path = str(path).strip()
    require(path and not path.startswith("/"), "file path must be relative")
    norm = path.replace("\\", "/")
    require(".." not in norm.split("/"), "file path must not contain '..'")
    return norm


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _materialize_bytes(*, cas: ContentAddressedStore, spec: Mapping[str, Any], bindings: Mapping[str, str]) -> bytes:
    if "ref" in spec:
        return cas.get_bytes(str(spec.get("ref")))
    if "text" in spec:
        return str(spec.get("text")).encode("utf-8")
    if "binding" in spec:
        key = str(spec.get("binding"))
        ref = bindings.get(key, "")
        if not ref:
            raise ValidationError(f"missing binding: {key}")
        return cas.get_bytes(ref)
    raise ValidationError("file spec must contain one of: ref, text, binding")


@dataclass(frozen=True)
class RunRecipeResult:
    status: str  # PASS|FAIL|SKIP|TIMEOUT|ERROR
    reason: str
    exit_code: int | None
    stdout_ref: str
    stderr_ref: str
    outputs: list[dict[str, Any]]
    toolchain: dict[str, Any]
    duration_ms: int
    argv: list[str]
    stdout_truncated: bool
    stderr_truncated: bool


@dataclass
class RecipeSpec:
    argv: list[str]
    timeout_ms: int
    max_output_bytes: int
    max_capture_bytes: int
    expected_exit: int
    expect: Mapping[str, Any]
    capture_paths: list[str]
    artifacts: Mapping[str, Mapping[str, Any]]
    stdin_spec: Any
    env_extra: Mapping[str, Any]
    files: Mapping[str, Mapping[str, Any]]
    requires: list[str]
    requires_paths: list[str]
    toolchain: dict[str, Any] = field(default_factory=lambda: {"executables": {}})

    @classmethod
    def from_recipe(cls, recipe: Mapping[str, Any]) -> "RecipeSpec":
        expect = recipe.get("expect", {}) or {}
        return cls(
            argv=list(recipe.get("argv") or []),
            timeout_ms=int(recipe.get("timeout_ms", 30000)),
            max_output_bytes=int(recipe.get("max_output_bytes", 65536)),
            max_capture_bytes=int(recipe.get("max_capture_bytes", 1024 * 1024)),
            expected_exit=int(expect.get("exit_code", 0)),
            expect=expect,
            capture_paths=list(recipe.get("capture_paths", []) or []),
            artifacts=dict(recipe.get("artifacts", {}) or {}),
            stdin_spec=recipe.get("stdin"),
            env_extra=dict(recipe.get("env", {}) or {}),
            files=dict(recipe.get("files", {}) or {}),
            requires=list(recipe.get("requires", []) or []),
            requires_paths=list(recipe.get("requires_paths", []) or []),
        )


def _non_pass_result(
    status: CheckStatus,
    reason: str,
    *,
    toolchain: dict[str, Any],
    duration_ms: int = 0,
    argv: list[str] | None = None,
) -> RunRecipeResult:
    return RunRecipeResult(
        status=status.value,
        reason=reason,
        exit_code=None,
        stdout_ref="",
        stderr_ref="",
        outputs=[],
        toolchain=toolchain,
        duration_ms=duration_ms,
        argv=list(argv or []),
        stdout_truncated=False,
        stderr_truncated=False,
    )


def _check_requires(spec: RecipeSpec) -> RunRecipeResult | None:
    for exe in spec.requires:
        if shutil.which(str(exe)) is None:
            return _non_pass_result(
                CheckStatus.SKIP,
                f"missing required executable: {exe}",
                toolchain=spec.toolchain,
            )
    return None


def _check_requires_paths(spec: RecipeSpec, repo_root: Path | None) -> RunRecipeResult | None:
    base = Path(repo_root) if repo_root is not None else None
    for path in spec.requires_paths:
        candidate = Path(str(path))
        if not candidate.is_absolute() and base is not None:
            candidate = base / candidate
        if not candidate.exists():
            return _non_pass_result(
                CheckStatus.SKIP,
                f"missing required path: {path}",
                toolchain=spec.toolchain,
            )
    return None


def _materialize_files(
    *, cas: ContentAddressedStore, files: Mapping[str, Mapping[str, Any]], bindings: Mapping[str, str], work: Path
) -> None:
    for name, spec in files.items():
        safe = _safe_relpath(str(name))
        if not isinstance(spec, Mapping):
            raise ValidationError("recipe.files values must be objects")
        data = _materialize_bytes(cas=cas, spec=dict(spec), bindings=bindings)
        target = work / safe
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _materialize_stdin(
    *, cas: ContentAddressedStore, stdin_spec: Any, bindings: Mapping[str, str]
) -> bytes | None:
    if stdin_spec is None:
        return None
    if not isinstance(stdin_spec, Mapping):
        raise ValidationError("recipe.stdin must be an object")
    return _materialize_bytes(cas=cas, spec=dict(stdin_spec), bindings=bindings)


def _build_env(env_extra: Mapping[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    for key, value in env_extra.items():
        if value is None:
            env.pop(str(key), None)
        else:
            env[str(key)] = str(value)
    return env


def _resolve_toolchain(argv: list[str], requires: list[str], work: Path) -> dict[str, Any]:
    toolchain: dict[str, Any] = {"executables": {}}
    exe_names = list(dict.fromkeys([str(argv[0])] + [str(x) for x in requires]))
    for exe in exe_names:
        exe_path = _resolve_exe_path(exe, work)
        if not exe_path:
            continue
        toolchain["executables"][exe] = _toolchain_entry(exe_path)
    return toolchain


def _resolve_exe_path(exe: str, work: Path) -> str | None:
    candidate = Path(exe)
    if candidate.is_absolute():
        return str(candidate)
    if "/" in exe or "\\" in exe:
        resolved = (work / exe).resolve()
        return str(resolved) if resolved.exists() else None
    found = shutil.which(exe)
    return str(Path(found).resolve()) if found else None


def _toolchain_entry(exe_path: str) -> dict[str, Any]:
    try:
        return {"path": exe_path, "sha256": _sha256_file(Path(exe_path))}
    except Exception as e:
        return {"path": exe_path, "error": f"{type(e).__name__}: {e}"}


def _run_subprocess(
    *, argv: list[str], cwd: str, env: dict[str, str], stdin_bytes: bytes | None, timeout_ms: int
) -> tuple[subprocess.CompletedProcess[bytes] | None, RunRecipeResult | None, float]:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            input=stdin_bytes,
            timeout=timeout_ms / 1000.0,
            check=False,
        )
        return proc, None, start
    except FileNotFoundError as e:
        return None, _non_pass_result(
            CheckStatus.SKIP,
            f"executable not found: {e.filename}",
            toolchain={"executables": {}},
            argv=argv,
        ), start
    except subprocess.TimeoutExpired:
        return None, _non_pass_result(
            CheckStatus.TIMEOUT,
            f"timeout after {timeout_ms}ms",
            toolchain={"executables": {}},
            duration_ms=int((time.monotonic() - start) * 1000.0),
            argv=argv,
        ), start
    except Exception as e:
        return None, _non_pass_result(
            CheckStatus.ERROR,
            f"{type(e).__name__}: {e}",
            toolchain={"executables": {}},
            duration_ms=int((time.monotonic() - start) * 1000.0),
            argv=argv,
        ), start


def _evaluate_expectations(
    *, expect: Mapping[str, Any], expected_exit: int, exit_code: int, stdout_text: str, stderr_text: str, work: Path
) -> tuple[bool, str]:
    if exit_code != expected_exit:
        return False, f"exit_code {exit_code} != {expected_exit}"
    checks = (
        _check_contains(stdout_text, expect, "stdout_contains", True),
        _check_contains(stderr_text, expect, "stderr_contains", True),
        _check_contains(stdout_text, expect, "stdout_not_contains", False),
        _check_contains(stderr_text, expect, "stderr_not_contains", False),
        _check_regex(stdout_text, expect, "stdout_regex"),
        _check_regex(stderr_text, expect, "stderr_regex"),
        _check_files_exist(expect, "files_exist", work, True),
        _check_files_exist(expect, "files_not_exist", work, False),
    )
    for ok, reason in checks:
        if not ok:
            return False, reason
    return True, "pass"


def _check_contains(text: str, expect: Mapping[str, Any], key: str, should_contain: bool) -> tuple[bool, str]:
    if key not in expect:
        return True, ""
    needle = str(expect.get(key))
    contained = needle in text
    ok = contained if should_contain else not contained
    return ok, "" if ok else f"{key} mismatch"


def _check_regex(text: str, expect: Mapping[str, Any], key: str) -> tuple[bool, str]:
    if key not in expect:
        return True, ""
    pattern = str(expect.get(key))
    ok = re.search(pattern, text) is not None
    return ok, "" if ok else f"{key} mismatch"


def _check_files_exist(expect: Mapping[str, Any], key: str, work: Path, should_exist: bool) -> tuple[bool, str]:
    if key not in expect:
        return True, ""
    paths = expect.get(key, []) or []
    if not isinstance(paths, list):
        paths = []
    for path in paths:
        safe = _safe_relpath(str(path))
        exists = (work / safe).exists()
        if exists != should_exist:
            return False, f"{key} mismatch: {path}"
    return True, ""


def _capture_outputs(
    *, capture_paths: list[str], artifacts: Mapping[str, Mapping[str, Any]], work: Path, cas: ContentAddressedStore, max_capture_bytes: int
) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for rel in capture_paths:
        outputs.extend(_capture_path(rel, work, cas, max_capture_bytes))
    for aid in sorted(artifacts.keys(), key=str):
        outputs.extend(_capture_artifact(aid, artifacts.get(aid), work, cas, max_capture_bytes))
    return outputs


def _capture_path(rel: str, work: Path, cas: ContentAddressedStore, max_bytes: int) -> list[dict[str, Any]]:
    safe = _safe_relpath(str(rel))
    file = work / safe
    if not file.exists() or not file.is_file():
        return []
    data = file.read_bytes()
    ref = cas.put_bytes(data[:max_bytes]).ref
    return [{"name": safe, "ref": ref, "bytes": len(data), "truncated": len(data) > max_bytes, "path": safe}]


def _capture_artifact(
    aid: str, spec: Any, work: Path, cas: ContentAddressedStore, default_max: int
) -> list[dict[str, Any]]:
    if not isinstance(spec, Mapping):
        return []
    rel = spec.get("path")
    if not isinstance(rel, str) or not rel.strip():
        return []
    safe = _safe_relpath(rel)
    file = work / safe
    if not file.exists() or not file.is_file():
        return []
    max_bytes = int(spec.get("max_bytes", default_max))
    data = file.read_bytes()
    ref = cas.put_bytes(data[:max_bytes]).ref
    return [{
        "name": str(aid),
        "ref": ref,
        "bytes": len(data),
        "truncated": len(data) > max_bytes,
        "path": safe,
        "media_type": str(spec.get("media_type", "application/octet-stream")),
    }]


def run_recipe(
    *,
    cas: ContentAddressedStore,
    recipe: Mapping[str, Any],
    bindings: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> RunRecipeResult:
    """Execute a ``popperpad/recipe/v1`` in an isolated temp directory.

    ``bindings`` lets recipes refer to dynamic CAS refs via file specs:
    ``{"binding": "name"}`` uses ``bindings["name"]`` as a CAS ref.
    """
    bindings = dict(bindings or {})
    spec = RecipeSpec.from_recipe(recipe)

    skip = _check_requires(spec)
    if skip is not None:
        return skip
    skip = _check_requires_paths(spec, repo_root)
    if skip is not None:
        return skip

    with tempfile.TemporaryDirectory(prefix="popperpad_recipe_") as td:
        work = Path(td)
        _materialize_files(cas=cas, files=spec.files, bindings=bindings, work=work)
        stdin_bytes = _materialize_stdin(cas=cas, stdin_spec=spec.stdin_spec, bindings=bindings)
        env = _build_env(spec.env_extra)
        argv = [sys.executable if a == "${PYTHON}" else a for a in spec.argv]
        toolchain = _resolve_toolchain(argv, spec.requires, work)

        proc, error, start = _run_subprocess(
            argv=argv, cwd=str(work), env=env, stdin_bytes=stdin_bytes, timeout_ms=spec.timeout_ms
        )
        if error is not None:
            return replace(error, toolchain=toolchain)
        duration_ms = int((time.monotonic() - start) * 1000.0)

        stdout_full = proc.stdout or b""
        stderr_full = proc.stderr or b""
        stdout_truncated = len(stdout_full) > spec.max_output_bytes
        stderr_truncated = len(stderr_full) > spec.max_output_bytes
        stdout = stdout_full[: spec.max_output_bytes]
        stderr = stderr_full[: spec.max_output_bytes]
        stdout_ref = cas.put_bytes(stdout).ref if stdout else ""
        stderr_ref = cas.put_bytes(stderr).ref if stderr else ""
        stdout_text = stdout.decode("utf-8", errors="ignore")
        stderr_text = stderr.decode("utf-8", errors="ignore")

        outputs = _capture_outputs(
            capture_paths=spec.capture_paths,
            artifacts=spec.artifacts,
            work=work,
            cas=cas,
            max_capture_bytes=spec.max_capture_bytes,
        )

        ok, reason = _evaluate_expectations(
            expect=spec.expect,
            expected_exit=spec.expected_exit,
            exit_code=int(proc.returncode),
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            work=work,
        )
        if ok:
            return RunRecipeResult(
                status=CheckStatus.PASS.value,
                reason="pass",
                exit_code=int(proc.returncode),
                stdout_ref=stdout_ref,
                stderr_ref=stderr_ref,
                outputs=outputs,
                toolchain=toolchain,
                duration_ms=duration_ms,
                argv=list(argv),
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
            )
        return RunRecipeResult(
            status=CheckStatus.FAIL.value,
            reason=reason,
            exit_code=int(proc.returncode),
            stdout_ref=stdout_ref,
            stderr_ref=stderr_ref,
            outputs=outputs,
            toolchain=toolchain,
            duration_ms=duration_ms,
            argv=list(argv),
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
