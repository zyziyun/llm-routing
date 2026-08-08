"""Render the terminal monitoring demo to an SVG card for the README.

Runs demo.py, captures stdout, and draws it as a terminal window (same palette
as the edge-client UI). SVG is crisp at any zoom and version-controllable.

    PYTHONPATH=src python demo/render_svg.py
"""

from __future__ import annotations

import html
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATEWAY = HERE.parent
OUT = GATEWAY / "docs" / "screenshots" / "gateway-demo.svg"

BG = "#0f1115"
FG = "#e6e9ef"
MUTED = "#9aa4b2"
GREEN = "#3ddc97"   # edge
ORANGE = "#f7a23b"  # cheap / frontier
BLUE = "#5b8cff"    # cache / accent

CHAR_W = 8.4
LINE_H = 21
FONT = 14
PAD_X = 22
TITLE_H = 34


def color_for(line: str) -> str:
    s = line.strip()
    if "HIT" in line or s.startswith("cache") or 'tier="cache"' in line:
        return BLUE
    if s.startswith(("edge",)) or 'tier="edge"' in line or "  edge " in line:
        return GREEN
    if 'tier="frontier"' in line or 'tier="cheap"' in line or " frontier " in line or " cheap " in line:
        return ORANGE
    if s.startswith("gw_") or line.startswith("    gw_"):
        return MUTED
    if s.startswith("=") or s.startswith("-"):
        return MUTED
    return FG


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(HERE / "demo.py")],
        cwd=GATEWAY, capture_output=True, text=True,
        env={"PYTHONPATH": "src", "PATH": __import__("os").environ.get("PATH", ""),
             "GW_LOG_LEVEL": "ERROR"},
    )
    lines = [ln.rstrip() for ln in proc.stdout.splitlines() if not ln.lstrip().startswith("{")]

    max_len = max((len(ln) for ln in lines), default=40)
    width = int(CHAR_W * max_len + PAD_X * 2)
    height = int(TITLE_H + 12 + len(lines) * LINE_H + 14)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace">',
        f'<rect width="{width}" height="{height}" rx="10" fill="{BG}"/>',
        f'<rect width="{width}" height="{TITLE_H}" rx="10" fill="#171a21"/>',
        f'<rect y="{TITLE_H-10}" width="{width}" height="10" fill="#171a21"/>',
        f'<circle cx="20" cy="{TITLE_H//2}" r="6" fill="#ff5f56"/>',
        f'<circle cx="40" cy="{TITLE_H//2}" r="6" fill="#ffbd2e"/>',
        f'<circle cx="60" cy="{TITLE_H//2}" r="6" fill="#27c93f"/>',
        f'<text x="{width//2}" y="{TITLE_H//2+4}" fill="{MUTED}" font-size="12" '
        f'text-anchor="middle">make demo</text>',
    ]
    y = TITLE_H + 12 + FONT
    for ln in lines:
        parts.append(
            f'<text x="{PAD_X}" y="{y}" fill="{color_for(ln)}" font-size="{FONT}" '
            f'xml:space="preserve">{html.escape(ln)}</text>'
        )
        y += LINE_H
    parts.append("</svg>")
    OUT.write_text("\n".join(parts))
    print(f"wrote {OUT}  ({width}x{height}, {len(lines)} lines)")


if __name__ == "__main__":
    main()
