#!/usr/bin/env python3
"""Rebuild the approved Taskrivet identity from vector paths and a pinned font.

Install scripts/brand-requirements.txt in an isolated environment, then run this
script from any directory. No network, external font service, or AI call is used.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import shutil

import cairosvg
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageDraw
import uharfbuzz as hb

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "brand"
FONT = ROOT / "scripts" / "brand-font" / "Manrope[wght].ttf"
FONT_SHA256 = "3ae11c49db0455a3cc33e37d380f20fdb8c7f8b41dc07625c177e3d87a9d6ae6"
INK, TEAL, MINT, PAPER = "#10191e", "#087f71", "#46c6aa", "#f5f7f5"

# Three substantial members and one circular rivet. The gaps are intentional:
# the symbol reads without a tile and does not depend on shading or a typeface.
TOP = "M84 72H336C405 72 450 116 450 182C450 226 430 255 397 281L349 319Q340 326 332 318L294 278Q286 269 295 262L337 228C360 210 372 200 372 181C372 158 356 144 333 144H84Q72 144 72 132V84Q72 72 84 72Z"
STEM = "M72 249Q72 239 80 234L171 174Q180 168 191 168H211C246 168 270 192 270 225C270 258 246 282 212 282H201L162 309Q156 313 156 322V434Q156 446 144 446H84Q72 446 72 434Z"
LEG = "M253 279L438 426Q453 446 430 446H355Q340 446 330 435L215 314Q207 306 216 298Z"


def mark(ink: str, accent: str, *, tiny: bool = False) -> str:
    # A larger solid rivet survives 16px use; monochrome keeps a clear knockout.
    circle = 35 if tiny else 31
    if ink == accent:
        hole = f"M{211 - circle} 225a{circle} {circle} 0 1 0 {circle * 2} 0a{circle} {circle} 0 1 0 {-circle * 2} 0Z"
        return (f'<path fill="{ink}" d="{TOP}"/>'
                f'<path fill="{ink}" fill-rule="evenodd" d="{STEM}{hole}"/>'
                f'<path fill="{ink}" d="{LEG}"/>')
    return (f'<path fill="{ink}" d="{TOP}"/>'
            f'<path fill="{ink}" d="{STEM}"/>'
            f'<circle fill="{accent}" cx="211" cy="225" r="{circle}"/>'
            f'<path fill="{accent}" d="{LEG}"/>')


def svg(body: str, box: str, title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{box}" '
            f'role="img" aria-labelledby="title"><title id="title">{title}</title>'
            f'{body}</svg>\n')


def word_paths() -> tuple[str, float]:
    raw = FONT.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FONT_SHA256:
        raise ValueError("Bundled Manrope font does not match its pinned digest")
    tt = instantiateVariableFont(TTFont(io.BytesIO(raw)), {"wght": 800})
    glyphs = tt.getGlyphSet()
    names = tt.getGlyphOrder()
    face = hb.Face(raw)
    font = hb.Font(face)
    font.scale = (face.upem, face.upem)
    font.set_variations({"wght": 800})
    buffer = hb.Buffer()
    buffer.add_str("Taskrivet")
    buffer.guess_segment_properties()
    hb.shape(font, buffer)
    paths, x = [], 0
    for info, position in zip(buffer.glyph_infos, buffer.glyph_positions):
        pen = SVGPathPen(glyphs)
        glyphs[names[info.codepoint]].draw(pen)
        paths.append(f'<path transform="translate({x + position.x_offset} '
                     f'{position.y_offset})" d="{pen.getCommands()}"/>')
        x += position.x_advance
    scale = 210 / face.upem
    return f'<g transform="translate(350 245) scale({scale} {-scale})">{"".join(paths)}</g>', x * scale


def render(source: str, size: int, destination: Path) -> None:
    cairosvg.svg2png(bytestring=source.encode(), write_to=str(destination),
                    output_width=size, output_height=size)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    words, width = word_paths()
    logo_width = round(350 + width + 28)
    for suffix, ink, accent in [("", INK, TEAL), ("-light", PAPER, MINT),
                                ("-mono", INK, INK), ("-mono-light", PAPER, PAPER)]:
        (OUT / f"mark{suffix}.svg").write_text(svg(mark(ink, accent), "44 44 432 432", "Taskrivet riveted R"))
        body = f'<g transform="translate(0 0) scale(.64)">{mark(ink, accent)}</g><g fill="{ink}">{words}</g>'
        (OUT / f"logo{suffix}.svg").write_text(svg(body, f"0 0 {logo_width} 330", "Taskrivet"))

    # macOS icon artwork fills the standard 824/1024 footprint. Its corner
    # transparency is part of the asset; packaging never edits a signed bundle.
    tile = ('<defs><linearGradient id="tile" x2="0" y2="1">'
            '<stop stop-color="#21343e"/><stop offset="1" stop-color="#10191e"/>'
            '</linearGradient></defs><rect x="100" y="100" width="824" height="824" '
            'rx="184" fill="url(#tile)"/><rect x="102" y="102" width="820" height="820" '
            'rx="182" fill="none" stroke="#36505b" stroke-width="2"/>'
            f'<g transform="translate(112 100) scale(1.56)">{mark(PAPER, MINT)}</g>')
    icon = svg(tile, "0 0 1024 1024", "Taskrivet app icon")
    (OUT / "app-icon.svg").write_text(icon)
    render(icon, 1024, OUT / "app-icon.png")
    small = svg(f'<rect width="512" height="512" rx="108" fill="{INK}"/>'
                f'<g transform="translate(-8 -8) scale(1.03)">{mark(PAPER, MINT, tiny=True)}</g>',
                "0 0 512 512", "Taskrivet")
    (OUT / "favicon.svg").write_text(small)
    for size in (16, 32, 48, 64, 128, 180, 256, 512):
        render(small if size <= 32 else icon, size, OUT / ("apple-touch-icon.png" if size == 180 else f"icon-{size}.png"))
    shutil.copyfile(OUT / "icon-32.png", OUT / "favicon-32.png")
    with Image.open(OUT / "app-icon.png") as im:
        im.save(OUT / "app.icns", format="ICNS")
    with Image.open(OUT / "icon-32.png") as im:
        im.save(OUT / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32)])

    social = svg(f'<rect width="1280" height="640" fill="{INK}"/>'
                 '<rect x="56" y="56" width="1168" height="528" rx="28" fill="none" stroke="#2a454c" stroke-width="2"/>'
                 f'<g transform="translate(112 160) scale({1056 / logo_width})">'
                 f'<g transform="scale(.64)">{mark(PAPER, MINT)}</g><g fill="{PAPER}">{words}</g></g>',
                 "0 0 1280 640", "Taskrivet — local-first coding-agent workspace")
    (OUT / "social-preview.svg").write_text(social)
    cairosvg.svg2png(bytestring=social.encode(), write_to=str(OUT / "social-preview.png"))

    ui = ROOT / "desktop" / "ui" / "brand"
    ui.mkdir(parents=True, exist_ok=True)
    for name in ("mark.svg", "mark-light.svg"):
        shutil.copyfile(OUT / name, ui / name)
    # A deterministic contact sheet is a build artifact for visual inspection.
    sheet = Image.new("RGB", (1000, 360), PAPER)
    draw = ImageDraw.Draw(sheet)
    x = 24
    for size in (16, 32, 48, 64, 128, 256):
        with Image.open(OUT / f"icon-{size}.png") as im:
            sheet.paste(im, (x, 45 + (256 - size) // 2), im)
        draw.text((x, 315), f"{size} px", fill=INK)
        x += size + 32
    sheet.save(OUT / "size-check.png")
    manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(OUT.iterdir()) if p.suffix in {".svg", ".png", ".ico", ".icns"}}
    (OUT / "asset-hashes.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built {len(manifest)} brand assets and two desktop copies")


if __name__ == "__main__":
    main()
