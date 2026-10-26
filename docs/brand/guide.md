# Taskrivet identity

The riveted R joins three substantial members around one circular fastener. It
connects the product name to a compact, recognizable mark for apps and repositories.
The approved concept was redrawn as editable vector paths; the production files
are generated from `scripts/build_brand.py`.

## Choose an asset

| Use | Asset |
| --- | --- |
| Light background | `logo.svg` or `mark.svg` |
| Dark background | `logo-light.svg` or `mark-light.svg` |
| One-color printing | `logo-mono.svg` or `mark-mono.svg` |
| One-color reversed printing | `logo-mono-light.svg` or `mark-mono-light.svg` |
| macOS application bundle | `app.icns` |
| Editable app artwork / large raster | `app-icon.svg` / `app-icon.png` |
| Browser tab | `favicon.svg`, `favicon-32.png`, or `favicon.ico` |
| Touch shortcut | `apple-touch-icon.png` |
| Repository or link preview | `social-preview.png` (1280 × 640) |

All SVG wordmarks contain outlined lettering. They need no installed font and make
no network requests. Use the standalone mark at 24 px or larger; use the optically
adjusted favicon at 16–32 px. Keep wordmarks at least 160 px wide. Preserve aspect
ratio, and allow clear space of at least one rivet diameter around the visible art.
Do not add text inside the app icon or remove the gaps between its members.

The app tile includes transparent outer margins for macOS. The favicon fills its
canvas more fully so the symbol remains legible in small browser tabs. Review
`size-check.png` at actual pixel size when changing the geometry.

## Color and lettering

| Color | Hex | Use |
| --- | --- | --- |
| Ink | `#10191e` | Primary mark and wordmark on light surfaces |
| Teal | `#087f71` | Accent on light surfaces |
| Mint | `#46c6aa` | Accent on dark surfaces |
| Paper | `#f5f7f5` | Reversed mark and wordmark |

The wordmark uses the bundled Manrope font at weight 800, shaped with kerning and
converted to paths. Its SIL Open Font License and pinned upstream provenance are
in [`scripts/brand-font`](../../scripts/brand-font/README.md). The generated artwork
is covered by the repository license; the bundled font retains its own license.

## Rebuild

From the repository root, with Python and Cairo installed:

```sh
python3 -m venv /tmp/taskrivet-brand-venv
/tmp/taskrivet-brand-venv/bin/pip install -r scripts/brand-requirements.txt
/tmp/taskrivet-brand-venv/bin/python scripts/build_brand.py
```

Generation uses the checked-in font and vector geometry without network access.
The tool checks the font digest, emits the asset SHA-256 manifest, and copies the
two app marks into `desktop/ui/brand`. Commit those copies with the source assets.
Both desktop packaging paths embed the same `app.icns` before bundle signing.
Rebuilds can differ across Cairo or operating-system versions; review the manifest
and rendered output when changing the toolchain.
