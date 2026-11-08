# Briareus brand assets

Only the approved copper palette is built: faces/arms `#E87516`, dark field
`#0A1928`. The outside of each icon is transparent.

- `base/`: four SVGs in one folder: main logo and frame in copper and monochrome (`*-marble.svg`). No PNGs or subfolders.
- `sources/`: only source SVGs used by the builder.
- `services/`: eight finished framed service icons, SVG + upload PNG.
- `build.json`: source paths, frame slot, service scales and PNG size limit.

## Rebuild

From the repository root, install the renderer once:

```sh
npm ci --prefix scripts/brand
```

Then regenerate all service SVGs and the eight service upload PNGs:

```sh
python scripts/brand_assets.py build
```

Requires Python 3.10+ and Node.js 20.9+. PNGs are at most **10,000 bytes**.
The builder tries the largest configured dimension first and reduces palette
colors, then dimensions, to fit. It fails rather than exceed the limit.
Actual dimensions and byte counts are printed; no manifests, archives or
intermediate SVGs are written. Source margins and SigNoz's unwanted black
tile and shadows are removed in memory; the original eye paths use the original orange gradient over transparency. The source SVG is unchanged.

To add a service, put its SVG in `sources/` and add an entry to `services`
in `build.json`:

```json
"my-mcp": { "source": "sources/my-mcp.svg", "scale": 1.0 }
```

Rerun the build after changing a service source or `base/frame.svg`.
Use `currentColor: true` for a generic monochrome source; optional `viewBox`
trims transparent margins. PNG budget, sizes and palette options are configurable.
The build reads the approved base artwork without replacing its geometry.
Generated files are ready for manual upload; the builder does not deploy them.

The optional `python scripts/brand_assets.py palettes` command rebuilds the
copper base SVGs from `base/*-marble.svg`. If master geometry changes, update
`STRUCTURE_CONTOURS` in the script before using that command.

## Source attribution

`provenance.json` is the single source record for all service SVGs: URLs, hashes
and transformations. Ghidra uses the original vector by Ryan Kurtz published
in the upstream Ghidra discussion, with Apache-2.0 attribution retained in
`LICENSES.txt`. Sources are necessary to regenerate combined icons after a
frame change. Analysis combines the original Ghidra SVG with a repository-authored reverse-engineering badge (code brackets and a reverse arrow). Server is repository-authored. The optional `overlay` service setting combines source SVGs in memory; no intermediate SVG is written.

The build also copies the approved main SVG to the control-panel UI public directory
(`frontendLogo` in `build.json`). The web app uses this SVG for its brand mark. The builder also exports a
trimmed SVG for the browser tab (`frontendFavicon`); Vite fingerprints its URL
so updated artwork gets a new cache key, including under `/admin/`.
