"""Generate the project marks.

Kept in the repository rather than committing only the SVGs, because a logo
nobody can regenerate is a logo that cannot be adjusted. Run:

    python assets/_generate.py
"""

from __future__ import annotations

import math
import pathlib

GREEN = "#8FE64A"
GREEN_DIM = "#5FA82F"
INK = "#0D0D0D"
PAPER = "#E8E8E8"
MUTED = "#9BA3AF"

FONT = (
    "ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

# Node positions traced over a two-lobe brain silhouette. Hand-placed rather
# than generated: a random layout reads as noise, and the shape has to stay
# recognisable at 32px.
NODES = [
    # outer contour, clockwise from the top of the frontal lobe
    (52, 14),
    (74, 8),
    (96, 12),
    (114, 24),
    (124, 42),
    (128, 62),
    (122, 80),
    (110, 94),
    (96, 104),
    (78, 110),
    (58, 108),
    (42, 98),
    (30, 84),
    (24, 66),
    (26, 46),
    (36, 28),
    # inner structure
    (60, 34),
    (84, 30),
    (100, 44),
    (76, 50),
    (54, 56),
    (94, 66),
    (68, 74),
    (46, 76),
    (86, 88),
    # the stem
    (66, 122),
    (74, 134),
]

MARK_W, MARK_H = 152, 142

# Connect nodes close enough to read as a network without becoming a blob.
EDGES = [
    (i, j)
    for i, a in enumerate(NODES)
    for j, b in enumerate(NODES)
    if i < j and math.dist(a, b) <= 30
]


def mark(scale: float = 1.0, offset: tuple[float, float] = (0, 0)) -> str:
    ox, oy = offset
    out = [f'<g transform="translate({ox} {oy}) scale({scale})">']
    out.append(f'<g stroke="{GREEN_DIM}" stroke-width="1.4" opacity="0.85">')
    out += [
        f'<line x1="{NODES[i][0]}" y1="{NODES[i][1]}" '
        f'x2="{NODES[j][0]}" y2="{NODES[j][1]}"/>'
        for i, j in EDGES
    ]
    out.append("</g>")
    out.append(f'<g fill="{GREEN}">')
    out += [
        f'<circle cx="{x}" cy="{y}" r="{3.6 if k < 16 else 3.0}"/>'
        for k, (x, y) in enumerate(NODES)
    ]
    out.append("</g></g>")
    return "\n".join(out)


def write(name: str, body: str) -> None:
    pathlib.Path(f"assets/{name}").write_text(body, encoding="utf-8")
    print("wrote", name)


# --- icon: the mark alone, square, for avatars and favicons --------------
write(
    "icon.svg",
    f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160" width="160" height="160" role="img" aria-label="aimai-kit">
<rect width="160" height="160" rx="28" fill="{INK}"/>
{mark(1.0, (16, 12))}
</svg>
''',
)

# --- logo: mark plus wordmark, for docs and slides -----------------------
write(
    "logo.svg",
    f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 540 176" width="540" height="176" role="img" aria-label="aimai-kit">
<rect width="540" height="176" rx="20" fill="{INK}"/>
{mark(1.0, (22, 18))}
<text x="192" y="110" font-family="{FONT}" font-size="76" font-weight="600" fill="{GREEN}">aimai</text>
<text x="378" y="110" font-family="{FONT}" font-size="76" font-weight="300" fill="{PAPER}">-kit</text>
</svg>
''',
)

# --- header: the README banner -------------------------------------------
# One image rather than a stack of markdown, so the framing survives GitHub's
# renderer, dark mode and a narrow window.
write(
    "header.svg",
    f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 440" width="1200" height="440" role="img" aria-label="aimai-kit — a framework-free LLM engineering toolkit">
<rect width="1200" height="440" fill="{INK}"/>
{mark(1.15, (513, 44))}
<text x="600" y="288" text-anchor="middle" font-family="{FONT}" font-size="64" font-weight="600" fill="{GREEN}">aimai<tspan font-weight="300" fill="{PAPER}">-kit</tspan></text>
<line x1="230" y1="326" x2="970" y2="326" stroke="#2A2A2A" stroke-width="1"/>
<text x="600" y="368" text-anchor="middle" font-family="{FONT}" font-size="25" font-weight="600" fill="{PAPER}">Five layers, measured. <tspan font-weight="400" fill="{MUTED}">Providers, prompts, tools, an agent loop, a harness.</tspan></text>
<text x="600" y="406" text-anchor="middle" font-family="{MONO}" font-size="17" fill="#6B7280">pip install aimai-kit</text>
</svg>
''',
)


# --- PNG rendering -------------------------------------------------------
# The SVGs are the source of truth, but PyPI needs a raster: relative paths do
# not resolve on a project page, and an SVG served from a raw URL is not
# reliably displayed there. Drawing the PNG directly rather than converting
# the SVG keeps the aspect ratio exact and embeds the type, so the header
# looks the same everywhere it is shown.
#
#     uvx --from pillow python assets/_generate.py --png


def _render_png() -> None:
    from PIL import Image, ImageDraw, ImageFont

    def font(name: str, size: int):
        for path in (
            f"/System/Library/Fonts/Supplemental/{name}.ttf",
            f"/System/Library/Fonts/{name}.ttf",
            f"/usr/share/fonts/truetype/dejavu/{name}.ttf",
        ):
            if pathlib.Path(path).is_file():
                return ImageFont.truetype(path, size)
        return ImageFont.load_default(size)

    def draw_mark(
        draw: ImageDraw.ImageDraw, scale: float, ox: float, oy: float
    ) -> None:
        for i, j in EDGES:
            x1, y1 = NODES[i]
            x2, y2 = NODES[j]
            draw.line(
                (ox + x1 * scale, oy + y1 * scale, ox + x2 * scale, oy + y2 * scale),
                fill=GREEN_DIM,
                width=max(1, round(1.4 * scale)),
            )
        for k, (x, y) in enumerate(NODES):
            r = (3.6 if k < 16 else 3.0) * scale
            cx, cy = ox + x * scale, oy + y * scale
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GREEN)

    def centered(draw, y, parts, size, weight="Regular"):
        """Draw a run of (text, colour, font) pieces centred as one line."""
        widths = [draw.textlength(t, font=f) for t, _, f in parts]
        x = (W - sum(widths)) / 2
        for (text, colour, f), width in zip(parts, widths, strict=True):
            draw.text((x, y), text, font=f, fill=colour)
            x += width

    scale = 2  # draw at 2x for crisp downsampling
    W, H = 1200 * scale, 440 * scale
    img = Image.new("RGB", (W, H), INK)
    draw = ImageDraw.Draw(img)

    draw_mark(draw, 1.15 * scale, 513 * scale, 44 * scale)

    bold = font("Arial Bold", 64 * scale)
    light = font("Arial", 64 * scale)
    centered(
        draw,
        228 * scale,
        [("aimai", GREEN, bold), ("-kit", PAPER, light)],
        64 * scale,
    )

    draw.line(
        (230 * scale, 326 * scale, 970 * scale, 326 * scale),
        fill="#2A2A2A",
        width=scale,
    )

    tag_bold = font("Arial Bold", 25 * scale)
    tag = font("Arial", 25 * scale)
    centered(
        draw,
        348 * scale,
        [
            ("Five layers, measured.  ", PAPER, tag_bold),
            ("Providers, prompts, tools, an agent loop, a harness.", MUTED, tag),
        ],
        25 * scale,
    )

    # Monaco rather than Menlo: Menlo ships as a .ttc collection, which the
    # simple .ttf lookup above cannot open, and it silently fell back to the
    # default face.
    mono = font("Monaco", 17 * scale)
    centered(
        draw, 390 * scale, [("pip install aimai-kit", "#6B7280", mono)], 17 * scale
    )

    img.resize((1200, 440), Image.LANCZOS).save("assets/header.png")
    print("wrote header.png")

    # Square icon for avatars and social cards. The offsets are computed from
    # the node extents rather than guessed, so the mark stays centred if a
    # node moves.
    S = 512
    xs = [x for x, _ in NODES]
    ys = [y for _, y in NODES]
    icon = Image.new("RGB", (S * 2, S * 2), INK)
    idraw = ImageDraw.Draw(icon)
    icon_scale = (S * 2 * 0.74) / (max(ys) - min(ys))
    ox = (S * 2 - (max(xs) - min(xs)) * icon_scale) / 2 - min(xs) * icon_scale
    oy = (S * 2 - (max(ys) - min(ys)) * icon_scale) / 2 - min(ys) * icon_scale
    draw_mark(idraw, icon_scale, ox, oy)
    icon.resize((S, S), Image.LANCZOS).save("assets/icon.png")
    print("wrote icon.png")


if __name__ == "__main__" and "--png" in __import__("sys").argv:
    _render_png()
