# Vendored libraries (FIX_PLAN U30, DECISIONS D-108 / D-157)

Pinned copies so the app works without a CDN (no Enterprise, no AG Studio). MIT licensed; licence files kept.

| File | Package | Source |
|---|---|---|
| `ag-grid-community-36.2.0.min.js` | ag-grid-community 36.2.0 | `https://cdn.jsdelivr.net/npm/ag-grid-community@36.2.0/dist/ag-grid-community.min.js` |
| `ag-charts-community-14.2.0.min.js` | ag-charts-community 14.2.0 | `https://cdn.jsdelivr.net/npm/ag-charts-community@14.2.0/dist/umd/ag-charts-community.min.js` |
| `ag-grid-community-LICENSE.txt`, `ag-charts-community-LICENSE.txt` | the packages' `LICENSE.txt` | same packages |

To update: download the new pinned versions, replace the files, and change `AG_GRID_URL` / `AG_CHARTS_URL` in
`app/routes/pages.py`.
