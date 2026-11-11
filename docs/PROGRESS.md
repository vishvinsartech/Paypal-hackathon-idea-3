# SubGuard build progress

v3 work follows `docs/FIX_PLAN.md` (phases 0-6). Tick each phase only after its checks pass and it is committed.
The v1-v2 milestone history (from the original spec, now `docs/archive/BUILD_PROMPT.md`) is in
`docs/archive/PROGRESS_v1_v2.md`.

## v3 (docs/FIX_PLAN.md), branch `prototype-v3`

- [x] **Phase 0. Baseline** (2026-11-11). `make test`: **286 passed**, 2 deselected (sandbox), 127 s.
  `make lint`: clean. `make ui-check`: passed (story + Start demo with all three answers, no console errors).
  Added `scripts/shots.py` (`make shots ARGS="--phase p1"`): 25 screenshots per viewport (1440×900, 390×844) in
  `docs/img/v3/<phase>/`. The baseline set `p0/` shows B1 (companion opens scrolled down), B4 (steps never tick by
  hand), B6 (floating chat button over the timeline) and B7 (axis to Day 31, "from Day 101").

- [x] **Phase 1. Correctness bugs and story logic** (2026-11-11, commits `a1ff74b`..`b4396cd`). Done: persona
  Priya, B1-B8, B10, B11, D6, D7, D8, D10, Fair Trial badge (DECISIONS D-130..D-141). Deferred as FIX_PLAN says:
  B9 (Phase 3) and B12 (Phase 4). `make test`: **298 passed** (was 286), 2 deselected. `make lint`: clean.
  `make ui-check`: passed, now also checking the companion in view at 1440×900 and 390×844, steps ticking by hand,
  the toast top right, the chat chips and the act-by dates. Screenshots: `docs/img/v3/p1/` (looked at: companion
  opens at the top at both sizes; steps tick on a manual run; five-dot timeline with no overlaps; chat entry in the
  top bar). Seen for later phases: the mobile top bar wraps onto three lines (U27), and the KPI count-up can still
  be running when a screenshot is taken (U29).

- [x] **Phase 2. Make the AI matter** (2026-11-11, commit `e93912d`). Done: A1-A6 (DECISIONS D-142..D-147).
  Quillnote (Layer 2, prose traps): AI risk 73 vs basic check 25; the AI finds the notice period, the step-up and
  the hard cancel the basic check misses, and "seventy-two hours" -> act by Day 4 (basic: Day 7, too late).
  Penwright still 87 on both paths. `make test`: **310 passed** (was 298), 2 deselected. `make lint`: clean.
  `make ui-check`: passed, now with the Quillnote path (companion 73, AI vs basic panel, Cancel -> email + ACTION
  NEEDED -> simulated PayPal Automatic payments -> polled until CANCELLED). Two of four ui-check runs timed out on a
  page `load` (server answered in < 1 s throughout; most likely the AG Grid/Charts CDN): U30 vendoring fixes that.
  Screenshots: `docs/img/v3/p2/` (looked at: Quillnote checkout, companion, AI vs basic panel, ACTION NEEDED card).
  Seen for Phase 3: raw enums and `llm` source strings in the findings grid (U24), the delivery lines (U4), and
  the Quillnote card still offering Keep/Cancel plus a "cancel Nov 13" timer text while the handoff is open.

- [x] **Phase 3. UI restructure** (2026-11-11, commit `7b39592`). Done: U1-U30 and B9 (DECISIONS D-148..D-157).
  `/` is Priya's product view (`/user`, `/me` redirect); demo controls are a presenter bar behind `?demo=1` / D;
  companion, shop and evidence page restructured; AG Grid / Charts vendored. `make test`: **317 passed** (was 310),
  2 deselected. `make lint`: clean. `make ui-check`: passed (empty state, D key, companion order, welcome-only shop,
  merged card, one Keep / Cancel pair, U12 card, clause highlight, audit drawer with routine hidden, evidence tabs,
  390 px layout + bottom sheet, Start demo with all three answers on the card, Quillnote; no CDN requests).
  Penwright still 87, Quillnote 73. Screenshots: `docs/img/v3/p3/` (looked at: companion desktop + mobile sheet,
  Day 5 card with band, Day 11 with presenter bar, email modal with highlight, evidence summary, shop). `make sandbox-ui-check`:
  passed against the real PayPal sandbox (commit `74010ed`; the check was stale since D-120 and now serves the SDK
  button path). Left for Phase 5: the
  video narration still says "Day 7"; scenes.json only has its targets updated.
