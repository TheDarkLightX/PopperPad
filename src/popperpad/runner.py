from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
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


@dataclass(frozen=True)
class RunRecipeResult:
    status: str  # PASS|FAIL|SKIP|TIMEOUT|ERROR
    reason: str
    exit_code: int | None
    stdout_ref: str
    stderr_ref: str
    outputs: list[dict[str, Any]]


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
            )

    argv = list(recipe.get("argv") or [])
    timeout_ms = int(recipe.get("timeout_ms", 30000))
    max_output_bytes = int(recipe.get("max_output_bytes", 65536))
    expect = recipe.get("expect", {}) or {}
    expected_exit = int(expect.get("exit_code", 0))
    capture_paths = list(recipe.get("capture_paths", []) or [])

    env_extra = recipe.get("env", {}) or {}
    files = recipe.get("files", {}) or {}

    with tempfile.TemporaryDirectory(prefix="popperpad_recipe_") as td:
        work = Path(td)

        for name, spec in files.items():
            safe = _safe_relpath(str(name))
            if not isinstance(spec, Mapping):
                raise ValueError("recipe.files values must be objects")
            if "ref" in spec:
                ref = str(spec.get("ref"))
                data = cas.get_bytes(ref)
            elif "text" in spec:
                data = str(spec.get("text")).encode("utf-8")
            elif "binding" in spec:
                key = str(spec.get("binding"))
                ref = bindings.get(key, "")
                if not ref:
                    raise ValueError(f"missing binding for file: {name} (binding={key})")
                data = cas.get_bytes(ref)
            else:
                raise ValueError("file spec must contain one of: ref, text, binding")

            fp = work / safe
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_bytes(data)

        env = dict(os.environ)
        env["PYTHONHASHSEED"] = "0"
        for k, v in env_extra.items():
            if v is None:
                env.pop(str(k), None)
            else:
                env[str(k)] = str(v)

        argv = [sys.executable if a == "${PYTHON}" else a for a in argv]

        try:
            proc = subprocess.run(
                argv,
                cwd=str(work),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
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
            )
        except subprocess.TimeoutExpired:
            return RunRecipeResult(
                status="TIMEOUT",
                reason=f"timeout after {timeout_ms}ms",
                exit_code=None,
                stdout_ref="",
                stderr_ref="",
                outputs=[],
            )
        except Exception as e:
            return RunRecipeResult(
                status="ERROR",
                reason=f"{type(e).__name__}: {e}",
                exit_code=None,
                stdout_ref="",
                stderr_ref="",
                outputs=[],
            )

        stdout = (proc.stdout or b"")[:max_output_bytes]
        stderr = (proc.stderr or b"")[:max_output_bytes]
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

        outputs: list[dict[str, Any]] = []
        for rel in capture_paths:
            safe = _safe_relpath(str(rel))
            fp = work / safe
            if not fp.exists() or not fp.is_file():
                continue
            data = fp.read_bytes()
            ref = cas.put_bytes(data).ref
            outputs.append({"name": safe, "ref": ref, "bytes": len(data)})

        if ok:
            return RunRecipeResult(
                status="PASS",
                reason="pass",
                exit_code=int(proc.returncode),
                stdout_ref=stdout_ref,
                stderr_ref=stderr_ref,
                outputs=outputs,
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
        )
