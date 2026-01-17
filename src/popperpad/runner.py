from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .cas import ContentAddressedStore


def _require(cond: bool, msg: str) -> None:
    if cond:
        return
    raise ValueError(msg)


def _safe_relpath(p: str) -> str:
    p = str(p).strip()
    _require(p and not p.startswith("/"), "file path must be relative")
    norm = p.replace("\\", "/")
    _require(".." not in norm.split("/"), "file path must not contain '..'")
    return norm


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _materialize_bytes(*, cas: ContentAddressedStore, spec: Mapping[str, Any], bindings: Mapping[str, str]) -> bytes:
    if "ref" in spec:
        ref = str(spec.get("ref"))
        return cas.get_bytes(ref)
    if "text" in spec:
        return str(spec.get("text")).encode("utf-8")
    if "binding" in spec:
        key = str(spec.get("binding"))
        ref = bindings.get(key, "")
        if not ref:
            raise ValueError(f"missing binding: {key}")
        return cas.get_bytes(ref)
    raise ValueError("file spec must contain one of: ref, text, binding")


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


def run_recipe(
    *,
    cas: ContentAddressedStore,
    recipe: Mapping[str, Any],
    bindings: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> RunRecipeResult:
    """
    Execute a `popperpad/recipe/v1` in an isolated temp directory.

    `bindings` allows recipes to refer to dynamic CAS refs via files specs:
      { "binding": "name" } -> uses bindings["name"] as a CAS ref.
    """
    bindings = dict(bindings or {})
    toolchain: dict[str, Any] = {"executables": {}}
    requires = recipe.get("requires", []) or []
    for exe in requires:
        if shutil.which(str(exe)) is None:
            return RunRecipeResult(
                status="SKIP",
                reason=f"missing required executable: {exe}",
                exit_code=None,
                stdout_ref="",
                stderr_ref="",
                outputs=[],
                toolchain=toolchain,
                duration_ms=0,
                argv=[],
                stdout_truncated=False,
                stderr_truncated=False,
            )

    requires_paths = recipe.get("requires_paths", []) or []
    rr = Path(repo_root) if repo_root is not None else None
    for p in requires_paths:
        pp = Path(str(p))
        if not pp.is_absolute() and rr is not None:
            pp = rr / pp
        if not pp.exists():
            return RunRecipeResult(
                status="SKIP",
                reason=f"missing required path: {p}",
                exit_code=None,
                stdout_ref="",
                stderr_ref="",
                outputs=[],
                toolchain=toolchain,
                duration_ms=0,
                argv=[],
                stdout_truncated=False,
                stderr_truncated=False,
            )

    argv = list(recipe.get("argv") or [])
    timeout_ms = int(recipe.get("timeout_ms", 30000))
    max_output_bytes = int(recipe.get("max_output_bytes", 65536))
    max_capture_bytes = int(recipe.get("max_capture_bytes", 1024 * 1024))
    expect = recipe.get("expect", {}) or {}
    expected_exit = int(expect.get("exit_code", 0))
    capture_paths = list(recipe.get("capture_paths", []) or [])
    artifacts = dict(recipe.get("artifacts", {}) or {})
    stdin_spec = recipe.get("stdin", None)

    env_extra = recipe.get("env", {}) or {}
    files = recipe.get("files", {}) or {}

    with tempfile.TemporaryDirectory(prefix="popperpad_recipe_") as td:
        work = Path(td)

        for name, spec in files.items():
            safe = _safe_relpath(str(name))
            if not isinstance(spec, Mapping):
                raise ValueError("recipe.files values must be objects")
            data = _materialize_bytes(cas=cas, spec=dict(spec), bindings=bindings)

            fp = work / safe
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_bytes(data)

        stdin_bytes: bytes | None = None
        if stdin_spec is not None:
            if not isinstance(stdin_spec, Mapping):
                raise ValueError("recipe.stdin must be an object")
            stdin_bytes = _materialize_bytes(cas=cas, spec=dict(stdin_spec), bindings=bindings)

        env = dict(os.environ)
        env["PYTHONHASHSEED"] = "0"
        for k, v in env_extra.items():
            if v is None:
                env.pop(str(k), None)
            else:
                env[str(k)] = str(v)

        argv = [sys.executable if a == "${PYTHON}" else a for a in argv]

        exe_names = list(dict.fromkeys([str(argv[0])] + [str(x) for x in requires]))
        for exe in exe_names:
            exe_path: str | None = None
            p = Path(exe)
            if p.is_absolute():
                exe_path = str(p)
            elif "/" in exe or "\\" in exe:
                cand = (work / exe).resolve()
                if cand.exists():
                    exe_path = str(cand)
            else:
                resolved = shutil.which(exe)
                if resolved:
                    exe_path = str(Path(resolved).resolve())
            if exe_path:
                try:
                    toolchain["executables"][exe] = {"path": exe_path, "sha256": _sha256_file(Path(exe_path))}
                except Exception as e:
                    toolchain["executables"][exe] = {"path": exe_path, "error": f"{type(e).__name__}: {e}"}

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                cwd=str(work),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                input=stdin_bytes,
                timeout=timeout_ms / 1000.0,
                check=False,
            )
        except FileNotFoundError as e:
            return RunRecipeResult(
                status="SKIP",
                reason=f"executable not found: {e.filename}",
                exit_code=None,
                stdout_ref="",
                stderr_ref="",
                outputs=[],
                toolchain=toolchain,
                duration_ms=0,
                argv=list(argv),
                stdout_truncated=False,
                stderr_truncated=False,
            )
        except subprocess.TimeoutExpired:
            return RunRecipeResult(
                status="TIMEOUT",
                reason=f"timeout after {timeout_ms}ms",
                exit_code=None,
                stdout_ref="",
                stderr_ref="",
                outputs=[],
                toolchain=toolchain,
                duration_ms=int((time.monotonic() - t0) * 1000.0),
                argv=list(argv),
                stdout_truncated=False,
                stderr_truncated=False,
            )
        except Exception as e:
            return RunRecipeResult(
                status="ERROR",
                reason=f"{type(e).__name__}: {e}",
                exit_code=None,
                stdout_ref="",
                stderr_ref="",
                outputs=[],
                toolchain=toolchain,
                duration_ms=int((time.monotonic() - t0) * 1000.0),
                argv=list(argv),
                stdout_truncated=False,
                stderr_truncated=False,
            )

        dt_ms = int((time.monotonic() - t0) * 1000.0)
        stdout_full = proc.stdout or b""
        stderr_full = proc.stderr or b""
        stdout_trunc = len(stdout_full) > int(max_output_bytes)
        stderr_trunc = len(stderr_full) > int(max_output_bytes)

        stdout = stdout_full[:max_output_bytes]
        stderr = stderr_full[:max_output_bytes]
        stdout_ref = cas.put_bytes(stdout).ref if stdout else ""
        stderr_ref = cas.put_bytes(stderr).ref if stderr else ""

        stdout_text = stdout.decode("utf-8", errors="ignore")
        stderr_text = stderr.decode("utf-8", errors="ignore")

        ok = int(proc.returncode) == expected_exit
        if ok and "stdout_contains" in expect:
            needle = str(expect.get("stdout_contains"))
            ok = needle in stdout_text
        if ok and "stderr_contains" in expect:
            needle = str(expect.get("stderr_contains"))
            ok = needle in stderr_text
        if ok and "stdout_not_contains" in expect:
            needle = str(expect.get("stdout_not_contains"))
            ok = needle not in stdout_text
        if ok and "stderr_not_contains" in expect:
            needle = str(expect.get("stderr_not_contains"))
            ok = needle not in stderr_text
        if ok and "stdout_regex" in expect:
            pat = str(expect.get("stdout_regex"))
            ok = re.search(pat, stdout_text) is not None
        if ok and "stderr_regex" in expect:
            pat = str(expect.get("stderr_regex"))
            ok = re.search(pat, stderr_text) is not None
        if ok and "files_exist" in expect:
            want = expect.get("files_exist", []) or []
            if not isinstance(want, list):
                want = []
            for p in want:
                safe = _safe_relpath(str(p))
                if not (work / safe).exists():
                    ok = False
                    break
        if ok and "files_not_exist" in expect:
            want = expect.get("files_not_exist", []) or []
            if not isinstance(want, list):
                want = []
            for p in want:
                safe = _safe_relpath(str(p))
                if (work / safe).exists():
                    ok = False
                    break

        outputs: list[dict[str, Any]] = []
        for rel in capture_paths:
            safe = _safe_relpath(str(rel))
            fp = work / safe
            if not fp.exists() or not fp.is_file():
                continue
            data = fp.read_bytes()
            ref = cas.put_bytes(data[:max_capture_bytes]).ref
            outputs.append({"name": safe, "ref": ref, "bytes": len(data), "truncated": len(data) > max_capture_bytes, "path": safe})

        for aid in sorted(artifacts.keys(), key=str):
            spec = artifacts.get(aid)
            if not isinstance(spec, Mapping):
                continue
            rel = spec.get("path")
            if not isinstance(rel, str) or not rel.strip():
                continue
            safe = _safe_relpath(rel)
            fp = work / safe
            if not fp.exists() or not fp.is_file():
                continue
            max_b = int(spec.get("max_bytes", max_capture_bytes))
            data = fp.read_bytes()
            ref = cas.put_bytes(data[:max_b]).ref
            outputs.append(
                {
                    "name": str(aid),
                    "ref": ref,
                    "bytes": len(data),
                    "truncated": len(data) > max_b,
                    "path": safe,
                    "media_type": str(spec.get("media_type", "application/octet-stream")),
                }
            )

        if ok:
            return RunRecipeResult(
                status="PASS",
                reason="pass",
                exit_code=int(proc.returncode),
                stdout_ref=stdout_ref,
                stderr_ref=stderr_ref,
                outputs=outputs,
                toolchain=toolchain,
                duration_ms=dt_ms,
                argv=list(argv),
                stdout_truncated=stdout_trunc,
                stderr_truncated=stderr_trunc,
            )

        reason = "check failed"
        if int(proc.returncode) != expected_exit:
            reason = f"exit_code {proc.returncode} != {expected_exit}"

        return RunRecipeResult(
            status="FAIL",
            reason=reason,
            exit_code=int(proc.returncode),
            stdout_ref=stdout_ref,
            stderr_ref=stderr_ref,
            outputs=outputs,
            toolchain=toolchain,
            duration_ms=dt_ms,
            argv=list(argv),
            stdout_truncated=stdout_trunc,
            stderr_truncated=stderr_trunc,
        )
