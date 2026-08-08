"""Render the demos to SVG cards for the README (terminal-window style, same
palette as the edge-client UI). SVG is crisp at any zoom and diff-able.

Produces two cards:
  - gateway-demo.svg       from demo.py        (in-process routing + metrics)
  - gateway-live-demo.svg  from live_demo.sh   (real uvicorn over HTTP)

    PYTHONPATH=src python demo/render_svg.py
"""

from __future__ import annotations

import html
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATEWAY = HERE.parent
SHOTS = GATEWAY / "docs" / "screenshots"

BG, FG, MUTED = "#0f1115", "#e6e9ef", "#9aa4b2"
GREEN, ORANGE, BLUE = "#3ddc97", "#f7a23b", "#5b8cff"
CHAR_W, LINE_H, FONT, PAD_X, TITLE_H, MAX_COLS = 8.4, 21, 14, 22, 34, 96


def color_for(line: str) -> str:
    s = line.strip()
    if s.startswith(("=", "-")):
        return MUTED
    if s.startswith("data:"):
        return BLUE
    if "-> 200" in line:
        return GREEN
    if any(c in line for c in ("-> 401", "-> 402", "-> 429")):
        return ORANGE
    if "HIT" in line or "tier=cache" in line or 'tier="cache"' in line or "cache=True" in line:
        return BLUE
    if "tier=edge" in line or 'tier="edge"' in line or "  edge " in line or s.startswith("edge"):
        return GREEN
    if any(t in line for t in ('tier="frontier"', 'tier="cheap"', "tier=frontier",
                               "tier=cheap", " frontier ", " cheap ")):
        return ORANGE
    if s.startswith("gw_") or line.startswith("  gw_"):
        return MUTED
    return FG


def build_svg(lines: list[str], title: str) -> str:
    lines = [(ln if len(ln) <= MAX_COLS else ln[: MAX_COLS - 1] + "…") for ln in lines]
    max_len = max((len(ln) for ln in lines), default=40)
    width = int(CHAR_W * max_len + PAD_X * 2)
    height = int(TITLE_H + 12 + len(lines) * LINE_H + 14)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace">',
        f'<rect width="{width}" height="{height}" rx="10" fill="{BG}"/>',
        f'<rect width="{width}" height="{TITLE_H}" rx="10" fill="#171a21"/>',
        f'<rect y="{TITLE_H-10}" width="{width}" height="10" fill="#171a21"/>',
        f'<circle cx="20" cy="{TITLE_H//2}" r="6" fill="#ff5f56"/>',
        f'<circle cx="40" cy="{TITLE_H//2}" r="6" fill="#ffbd2e"/>',
        f'<circle cx="60" cy="{TITLE_H//2}" r="6" fill="#27c93f"/>',
        f'<text x="{width//2}" y="{TITLE_H//2+4}" fill="{MUTED}" font-size="12" '
        f'text-anchor="middle">{html.escape(title)}</text>',
    ]
    y = TITLE_H + 12 + FONT
    for ln in lines:
        out.append(
            f'<text x="{PAD_X}" y="{y}" fill="{color_for(ln)}" font-size="{FONT}" '
            f'xml:space="preserve">{html.escape(ln)}</text>'
        )
        y += LINE_H
    out.append("</svg>")
    return "\n".join(out)


def run(cmd: list[str]) -> list[str]:
    env = {**os.environ, "PYTHONPATH": "src", "GW_LOG_LEVEL": "ERROR"}
    p = subprocess.run(cmd, cwd=GATEWAY, capture_output=True, text=True, env=env)
    return [ln.rstrip() for ln in p.stdout.splitlines() if not ln.lstrip().startswith("{")]


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    (SHOTS / "gateway-demo.svg").write_text(
        build_svg(run([sys.executable, str(HERE / "demo.py")]), "make demo"))
    (SHOTS / "gateway-live-demo.svg").write_text(
        build_svg(run(["bash", str(HERE / "live_demo.sh")]), "bash demo/live_demo.sh"))
    print("wrote gateway-demo.svg and gateway-live-demo.svg")


if __name__ == "__main__":
    main()
