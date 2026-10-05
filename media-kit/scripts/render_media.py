#!/usr/bin/env python3
"""Render authentic PopperPad CLI transcripts into PNG and MP4 assets."""

from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPTS = ROOT / "transcripts"
IMAGES = ROOT / "images"
VIDEOS = ROOT / "videos"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
FFMPEG = shutil.which("ffmpeg")
SCENES = (
    "ledger",
    "support",
    "refute",
    "dispute",
    "transfer",
    "integrity",
)


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def page(scene: str, visible_lines: int | None = None) -> str:
    all_lines = strip_ansi((TRANSCRIPTS / f"{scene}.txt").read_text()).splitlines()
    lines = all_lines if visible_lines is None else all_lines[:visible_lines]
    terminal = html.escape("\n".join(lines))
    font_rule = (
        'font: 500 15.5px/1.38 "SFMono-Regular", Menlo, monospace;'
        if scene == "integrity"
        else 'font: 500 17px/1.42 "SFMono-Regular", Menlo, monospace;'
    )
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>PopperPad CLI — {html.escape(scene)}</title>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; width: 100%; height: 100%; overflow: hidden; }}
  body {{
    color: #e8eceb;
    background:
      radial-gradient(circle at 78% 8%, #292532 0%, transparent 35%),
      radial-gradient(circle at 8% 100%, #182221 0%, transparent 44%),
      #090b0f;
  }}
  .noise {{
    position: fixed; inset: 0; opacity: .045; pointer-events: none;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.92' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.58'/%3E%3C/svg%3E");
  }}
  .frame {{
    width: 1920px; height: 1080px; padding: 48px 58px;
  }}
  .terminal {{
    width: 1804px; height: 984px; overflow: hidden;
    border: 1px solid rgba(255,255,255,.15); border-radius: 14px;
    background: rgba(5,7,9,.96);
    box-shadow: 0 34px 110px rgba(0,0,0,.58), inset 0 1px rgba(255,255,255,.05);
  }}
  .bar {{
    height: 56px; padding: 0 20px; display: flex; align-items: center;
    border-bottom: 1px solid rgba(255,255,255,.11);
    background: #191b20;
  }}
  .dots {{ display: flex; gap: 10px; }}
  .dot {{ width: 13px; height: 13px; border-radius: 50%; }}
  .dot:nth-child(1) {{ background: #ff6b72; }}
  .dot:nth-child(2) {{ background: #ffca5c; }}
  .dot:nth-child(3) {{ background: #6dffb4; }}
  .bar-title {{
    margin-left: auto; margin-right: auto; transform: translateX(-33px);
    color: #a4a7ad; font: 500 16px "SFMono-Regular", Menlo, monospace;
  }}
  pre {{
    margin: 0; padding: 25px 34px 32px; color: #e8eceb;
    {font_rule}
    white-space: pre-wrap;
  }}
</style>
</head>
<body>
<div class="noise"></div>
<main class="frame">
  <section class="terminal">
    <div class="bar">
      <div class="dots"><i class="dot"></i><i class="dot"></i><i class="dot"></i></div>
      <div class="bar-title">popperpad — zsh — 132×38</div>
    </div>
    <pre>{terminal}</pre>
  </section>
</main>
</body>
</html>"""


def chrome_screenshot(source: Path, target: Path) -> None:
    command = [
        str(CHROME),
        "--headless=new",
        "--hide-scrollbars",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--allow-file-access-from-files",
        "--window-size=1920,1080",
        "--force-device-scale-factor=1",
        f"--screenshot={target}",
        source.as_uri(),
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0 or not target.exists():
        raise SystemExit(result.stdout.decode(errors="replace"))


def ffmpeg(command: list[str]) -> None:
    result = subprocess.run(
        [FFMPEG or "ffmpeg", *command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.decode(errors="replace"))


def render_scene(scene: str, temp: Path) -> tuple[Path, Path]:
    IMAGES.mkdir(parents=True, exist_ok=True)
    VIDEOS.mkdir(parents=True, exist_ok=True)
    frames = temp / scene
    frames.mkdir()
    final_html = temp / f"{scene}-final.html"
    final_html.write_text(page(scene))
    image = IMAGES / f"{scene}-1920x1080.png"
    chrome_screenshot(final_html, image)

    lines = strip_ansi((TRANSCRIPTS / f"{scene}.txt").read_text()).splitlines()
    sample_points = list(range(1, len(lines) + 1, 2))
    if sample_points[-1] != len(lines):
        sample_points.append(len(lines))
    manifest_lines: list[str] = []
    for index, visible in enumerate(sample_points):
        source = frames / f"{index:04}.html"
        frame = frames / f"{index:04}.png"
        source.write_text(page(scene, visible))
        chrome_screenshot(source, frame)
        safe = str(frame).replace("'", "'\\''")
        manifest_lines.append(f"file '{safe}'")
        manifest_lines.append("duration 0.30")
    last = str(frames / f"{len(sample_points)-1:04}.png").replace("'", "'\\''")
    manifest_lines.extend(
        [
            f"file '{last}'",
            "duration 2.2",
            f"file '{last}'",
        ]
    )
    manifest = frames / "frames.txt"
    manifest.write_text("\n".join(manifest_lines) + "\n")
    video = VIDEOS / f"{scene}-1920x1080.mp4"
    ffmpeg(
        [
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest),
            "-vf",
            "fps=30,format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(video),
        ]
    )
    return image, video


def render_reel(videos: list[Path], temp: Path) -> Path:
    manifest = temp / "reel.txt"
    entries = []
    for video in videos:
        safe = str(video).replace("'", "'\\''")
        entries.append(f"file '{safe}'")
    manifest.write_text("\n".join(entries) + "\n")
    reel = VIDEOS / "popperpad-cli-workflow-1920x1080.mp4"
    ffmpeg(
        [
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(reel),
        ]
    )
    return reel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenes", nargs="*", choices=[*SCENES])
    parser.add_argument("--reel-only", action="store_true")
    args = parser.parse_args()
    selected = args.scenes or list(SCENES)
    if not CHROME.exists():
        raise SystemExit(f"Chrome not found: {CHROME}")
    if not FFMPEG:
        raise SystemExit("ffmpeg not found")
    with tempfile.TemporaryDirectory(prefix="popperpad-media-") as directory:
        temp = Path(directory)
        if args.reel_only:
            existing = [VIDEOS / f"{scene}-1920x1080.mp4" for scene in SCENES]
            missing = [path for path in existing if not path.exists()]
            if missing:
                raise SystemExit(f"missing scene clips: {missing}")
            reel = render_reel(existing, temp)
            print(reel.relative_to(ROOT))
            return
        outputs = [render_scene(scene, temp) for scene in selected]
        if selected == list(SCENES):
            reel = render_reel([video for _, video in outputs], temp)
            print(reel.relative_to(ROOT))
    for image, video in outputs:
        print(image.relative_to(ROOT))
        print(video.relative_to(ROOT))


if __name__ == "__main__":
    main()
