from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from popperpad.cli import main


@pytest.mark.parametrize(
    "arguments",
    [
        lambda root: ["--pad", str(root), "init"],
        lambda root: ["init", "--pad", str(root)],
    ],
    ids=["global-option", "documented-subcommand-option"],
)
def test_init_accepts_pad_before_or_after_subcommand(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    arguments: Callable[[Path], list[str]],
) -> None:
    root = tmp_path / "pad"

    assert main(arguments(root)) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"ok": True, "pad": str(root.resolve())}
    assert root.is_dir()
    assert (root / "log.jsonl").is_file()
    assert (root / "log.jsonl.lock").is_file()
