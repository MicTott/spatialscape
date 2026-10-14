"""The spatialscape mark: a tissue section made of spots whose colored domains roll like hills.

    python/.venv/bin/python python/scripts/gen_brand.py

Writes docs/public/brand/{mark,banner-dark,banner-light}.svg (also copied to docs/public/logo.svg and app/public/favicon.svg).
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "public" / "brand"
out.mkdir(parents=True, exist_ok=True)
CX = CY = 128
R_DISC = 118
R_FILL = 104          # dots live inside this radius
PITCH = 15.5
DOT = 5.6
DISC = "#141a26"
SKY = "#2a3449"
SUN = "#ff8a5b"
BANDS = ["#f5d324", "#35c46a", "#3d7fe0", "#8b5cf6"]  # yellow, green, blue, violet from top to bottom

def curve(k, x):
    """boundary k between band k-1 and band k, as y(x): a hill rising on the left, strata following it"""
    t = (x - CX) / R_FILL
    hill = -26 * math.exp(-((t + 0.35) / 0.55) ** 2) + 10 * math.sin(t * 2.2 + 2.4)   # one crest left, a dip under the sun
    base = [112, 146, 178, 206][k]
    follow = [1.0, 0.75, 0.5, 0.3][k]
    return base + follow * hill + 3 * math.sin(t * 6.1 + k * 1.7)


def band_of(x, y):
    for k in range(4):
        if y < curve(k, x):
            return k - 1      # -1 = sky
    return 3

def dots():
    rows = int(2 * R_FILL / (PITCH * math.sqrt(3) / 2)) + 3
    out = []
    for j in range(-rows, rows + 1):
        y = CY + j * PITCH * math.sqrt(3) / 2
        off = PITCH / 2 if j % 2 else 0
        cols = int(2 * R_FILL / PITCH) + 3
        for i in range(-cols, cols + 1):
            x = CX + i * PITCH + off
            if math.hypot(x - CX, y - CY) > R_FILL:
                continue
            out.append((x, y))
    return out

def mark_svg():
    parts = [f'<circle cx="{CX}" cy="{CY}" r="{R_DISC}" fill="{DISC}"/>']
    sun = (CX + 52, CY - 58)
    parts.append(f'<circle cx="{sun[0]}" cy="{sun[1]}" r="13" fill="{SUN}"/>')
    for x, y in dots():
        if math.hypot(x - sun[0], y - sun[1]) < 20:
            continue
        b = band_of(x, y)
        if b < 0:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{DOT*0.55:.1f}" fill="{SKY}"/>')
        else:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{DOT}" fill="{BANDS[b]}"/>')
    return "\n".join(parts)

inner = mark_svg()
mark = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">\n{inner}\n</svg>\n'
(out / "mark.svg").write_text(mark)

def banner(fill, name):
    txt = (f'<text x="76" y="63" font-family="Inter, \'Helvetica Neue\', Helvetica, Arial, sans-serif" font-size="46" '
           f'font-weight="600" letter-spacing="-1.2" fill="{fill}" textLength="286" lengthAdjust="spacingAndGlyphs">spatialscape</text>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 372 96" width="372" height="96">\n'
           f'<g transform="translate(8 16) scale(0.25)">\n{inner}\n</g>\n{txt}\n</svg>\n')
    (out / name).write_text(svg)

banner("#e6edf3", "banner-dark.svg")
banner("#1f2328", "banner-light.svg")

for copy in (ROOT / "docs" / "public" / "logo.svg", ROOT / "app" / "public" / "favicon.svg"):
    copy.write_text(mark)
print("wrote", sorted(p.name for p in out.iterdir()))
