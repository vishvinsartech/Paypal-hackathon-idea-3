# Vendored libraries (FIX_PLAN U30, DECISIONS D-108 / D-157)

Pinned copies so the app works without a CDN (no Enterprise, no AG Studio). MIT licensed; licence files kept.

| File | Package | Source |
|---|---|---|
| `ag-grid-community-36.2.0.min.js` | ag-grid-community 36.2.0 | `https://cdn.jsdelivr.net/npm/ag-grid-community@36.2.0/dist/ag-grid-community.min.js` |
| `ag-charts-community-14.2.0.min.js` | ag-charts-community 14.2.0 | `https://cdn.jsdelivr.net/npm/ag-charts-community@14.2.0/dist/umd/ag-charts-community.min.js` |
| `ag-grid-community-LICENSE.txt`, `ag-charts-community-LICENSE.txt` | the packages' `LICENSE.txt` | same packages |

To update: download the new pinned versions, replace the files, and change `AG_GRID_URL` / `AG_CHARTS_URL` in
`app/routes/pages.py`.

## Font (docs/UI_REDESIGN.md, D-191)

| File | Package | Source |
|---|---|---|
| `fonts/atkinson-hyperlegible-next-latin-wght.woff2` | @fontsource-variable/atkinson-hyperlegible-next 5.2.6 (Latin subset, weights 200-800) | `https://cdn.jsdelivr.net/npm/@fontsource-variable/atkinson-hyperlegible-next@5.2.6/files/atkinson-hyperlegible-next-latin-wght-normal.woff2` |
| `fonts/atkinson-hyperlegible-next-OFL.txt` | the package's `LICENSE` (SIL Open Font License 1.1) | same package |

Declared in `app/static/tokens.css` with `font-display: swap` and a system fallback.
