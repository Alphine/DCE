"""Build frontend/assets/world-map.svg from the upstream world-map-data SVG.

Upstream: https://github.com/stephanwagner/world-map-data (MIT, Stephan Wagner), maps/world.svg.
The raw file is about 13.6 MB and is NOT committed. It is read from --source (default:
scripts/.cache/world.svg, which is git-ignored) and downloaded there if missing.

Simplification:
  * path data is parsed to absolute coordinates, quantised to 0.1 SVG units, and re-encoded as
    relative integer deltas (no accumulated rounding error);
  * Douglas-Peucker point reduction per ring (--tolerance, SVG units);
  * subpaths (islands, lakes) whose area is below --min-area square units are dropped, except the
    largest subpath of every country, so no country disappears;
  * only country paths (those with data-id) are kept; the border-line paths are dropped because
    country outlines are drawn with a stroke;
  * presentation attributes (fill, stroke, ...) are dropped; styling is done in CSS.

Standard library only. Usage (from the repo root):
    python scripts/build_world_map.py [--source PATH] [--output PATH] [--min-area 0.1] [--tolerance 0.15]
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO_ROOT / "scripts" / ".cache" / "world.svg"
DEFAULT_OUTPUT = REPO_ROOT / "frontend" / "assets" / "world-map.svg"
SOURCE_URL = "https://raw.githubusercontent.com/stephanwagner/world-map-data/main/maps/world.svg"
LICENSE_URL = "https://raw.githubusercontent.com/stephanwagner/world-map-data/main/LICENSE"
VIEW_W, VIEW_H = 2400, 1200
SCALE = 10  # 0.1 SVG unit grid

PATH_RE = re.compile(r"<path\b([^>]*?)/?>", re.S)
ATTR_RE = re.compile(r'\s([A-Za-z_:][-A-Za-z0-9_:.]*)="([^"]*)"')
TOKEN_RE = re.compile(r"[MmLlHhVvZzCcSsQqTtAa]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def ensure_source(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {SOURCE_URL} to {path} ...", file=sys.stderr)
    urllib.request.urlretrieve(SOURCE_URL, path)  # noqa: S310 - fixed upstream URL


def fetch_license() -> str:
    try:
        with urllib.request.urlopen(LICENSE_URL, timeout=20) as resp:  # noqa: S310 - fixed upstream URL
            text = resp.read().decode("utf-8").strip()
    except OSError:
        text = "MIT License. Full text: https://github.com/stephanwagner/world-map-data/blob/main/LICENSE"
    # An XML comment must not contain "--".
    return text.replace("--", "- -")


def parse_path(d: str) -> list[list[tuple[int, int]]]:
    """Return subpaths as lists of integer points on the 0.1-unit grid (absolute)."""
    tokens = TOKEN_RE.findall(d)
    subpaths: list[list[tuple[int, int]]] = []
    cur: list[tuple[int, int]] = []
    x = y = 0.0
    sx = sy = 0.0
    cmd = ""
    i = 0

    def take() -> float:
        nonlocal i
        value = float(tokens[i])
        i += 1
        return value

    while i < len(tokens):
        tok = tokens[i]
        if tok[0].isalpha():
            cmd = tok
            i += 1
            if cmd in "Zz":
                if cur:
                    subpaths.append(cur)
                    cur = []
                x, y = sx, sy
                continue
        if cmd in ("M", "m"):
            nx, ny = take(), take()
            if cmd == "m":
                nx, ny = nx + x, ny + y
            if cur:
                subpaths.append(cur)
            x, y, sx, sy = nx, ny, nx, ny
            cur = [(round(x * SCALE), round(y * SCALE))]
            cmd = "L" if cmd == "M" else "l"
        elif cmd in ("L", "l"):
            nx, ny = take(), take()
            if cmd == "l":
                nx, ny = nx + x, ny + y
            x, y = nx, ny
            cur.append((round(x * SCALE), round(y * SCALE)))
        elif cmd in ("H", "h"):
            nx = take()
            x = nx if cmd == "H" else x + nx
            cur.append((round(x * SCALE), round(y * SCALE)))
        elif cmd in ("V", "v"):
            ny = take()
            y = ny if cmd == "V" else y + ny
            cur.append((round(x * SCALE), round(y * SCALE)))
        else:
            raise ValueError(f"unsupported path command {cmd!r}; the simplifier handles only M L H V Z")
    if cur:
        subpaths.append(cur)
    return subpaths


def dedupe(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for p in points:
        if not out or out[-1] != p:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def simplify_ring(points: list[tuple[int, int]], tolerance: float) -> list[tuple[int, int]]:
    """Douglas-Peucker on a closed ring, tolerance in SVG units. Keeps at least three points."""
    if len(points) <= 3 or tolerance <= 0:
        return points
    eps = tolerance * SCALE
    ring = points + [points[0]]
    keep = [False] * len(ring)
    keep[0] = keep[-1] = True
    stack = [(0, len(ring) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        ax, ay = ring[a]
        bx, by = ring[b]
        dx, dy = bx - ax, by - ay
        length = (dx * dx + dy * dy) ** 0.5
        best_d, best_k = -1.0, -1
        for k in range(a + 1, b):
            px, py = ring[k]
            if length == 0:
                d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            else:
                d = abs(dy * (px - ax) - dx * (py - ay)) / length
            if d > best_d:
                best_d, best_k = d, k
        if best_d > eps:
            keep[best_k] = True
            stack.append((a, best_k))
            stack.append((best_k, b))
    out = [p for p, k in zip(ring, keep) if k][:-1]
    return out if len(out) >= 3 else points


def area_units(points: list[tuple[int, int]]) -> float:
    """Shoelace area in square SVG units."""
    total = 0
    n = len(points)
    for k in range(n):
        x1, y1 = points[k]
        x2, y2 = points[(k + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2 / (SCALE * SCALE)


def fmt_tenths(n: int) -> str:
    sign = "-" if n < 0 else ""
    a = abs(n)
    whole, frac = divmod(a, 10)
    return f"{sign}{whole}" if frac == 0 else f"{sign}{whole}.{frac}"


def encode(subpaths: list[list[tuple[int, int]]]) -> str:
    parts: list[str] = []
    for pts in subpaths:
        if len(pts) < 2:
            continue
        x0, y0 = pts[0]
        seg = [f"M{fmt_tenths(x0)},{fmt_tenths(y0)}"]
        px, py = x0, y0
        deltas = []
        for x, y in pts[1:]:
            deltas.append(f"{fmt_tenths(x - px)},{fmt_tenths(y - py)}")
            px, py = x, y
        if deltas:
            seg.append("l" + " ".join(deltas))
        seg.append("Z")
        parts.append("".join(seg))
    return "".join(parts)


def simplify(source_text: str, min_area: float, tolerance: float) -> tuple[list[str], dict]:
    stats = {"paths_in": 0, "paths_out": 0, "subpaths_in": 0, "subpaths_out": 0}
    elements: list[str] = []
    for m in PATH_RE.finditer(source_text):
        attrs = dict(ATTR_RE.findall(m.group(1)))
        if "data-id" not in attrs or "d" not in attrs:
            continue  # border lines and other non-country paths
        stats["paths_in"] += 1
        subpaths = [dedupe(sp) for sp in parse_path(attrs["d"])]
        subpaths = [sp for sp in subpaths if len(sp) >= 3]
        stats["subpaths_in"] += len(subpaths)
        subpaths = [simplify_ring(sp, tolerance) for sp in subpaths]
        if not subpaths:
            continue
        areas = [area_units(sp) for sp in subpaths]
        largest = max(range(len(subpaths)), key=lambda k: areas[k])
        kept = [sp for k, (sp, a) in enumerate(zip(subpaths, areas)) if k == largest or a >= min_area]
        stats["subpaths_out"] += len(kept)
        stats["paths_out"] += 1
        out_attrs = [f'data-id="{escape(attrs["data-id"])}"']
        if "data-country" in attrs:
            out_attrs.append(f'data-country="{escape(attrs["data-country"])}"')
        if "data-name" in attrs:
            out_attrs.append(f'data-name="{escape(attrs["data-name"])}"')
        out_attrs.append(f'd="{encode(kept)}"')
        elements.append(f"<path {' '.join(out_attrs)}/>")
    return elements, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--min-area", type=float, default=0.1,
                    help="drop non-largest subpaths smaller than this many square SVG units")
    ap.add_argument("--tolerance", type=float, default=0.15,
                    help="Douglas-Peucker tolerance in SVG units (0 disables point reduction)")
    args = ap.parse_args()

    ensure_source(args.source)
    source_text = args.source.read_text(encoding="utf-8")
    elements, stats = simplify(source_text, args.min_area, args.tolerance)
    license_text = fetch_license()

    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!--\n"
        "  World country outlines, simplified for Disaster Commander Edge.\n"
        "  Source: https://github.com/stephanwagner/world-map-data (maps/world.svg)\n"
        "  Copyright and license of the source data:\n\n"
        f"{license_text}\n\n"
        "  Generated by scripts/build_world_map.py. Do not edit by hand.\n"
        "-->\n"
    )
    svg = (
        header
        + f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW_W} {VIEW_H}" '
        + 'role="img" aria-label="World map" focusable="false">\n'
        + '<g class="world-countries">\n'
        + "\n".join(elements)
        + "\n</g>\n</svg>\n"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8", newline="\n")

    size = args.output.stat().st_size
    print(f"paths kept: {stats['paths_out']} of {stats['paths_in']} country paths")
    print(f"subpaths kept: {stats['subpaths_out']} of {stats['subpaths_in']}")
    print(f"wrote {args.output} ({size:,} bytes, {size / 1024 / 1024:.2f} MiB)")
    if size > 1.5 * 1024 * 1024:
        print("warning: output is above the 1.5 MB target; raise --min-area", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
