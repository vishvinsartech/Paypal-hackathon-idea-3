# UI redesign v5 ("ui3" commits): plan

Status: **approved 2026-11-12 with the review changes in section 0b.** Step 1 done.
Skill: `.claude/skills/frontend-design/SKILL.md`.

## 0. What this covers, and four facts found while planning

| Brief name | Real URL in this app | Template |
|---|---|---|
| `/` landing (judges) | `/` signed out | `intro.html` (+ `_hero.html`, `_steps.html`) |
| `/app` dashboard (Priya) | `/` signed in | `home.html` (+ `_settings.html`, `_dialogs.html`, `timeline.css`) |
| `/presenter` (judges) | `/?demo=1` | `demo.html` (+ `_landing.html`, `_presenter.html`) |
| login | `/login` | `login.html` (`auth.css`) |

1. **There are no `/app` or `/presenter` routes.** Rule 1 forbids touching routes, so the brief's names map to the URLs
   above (D-181, D-167). Nothing is added or renamed.
2. **`docs/UI_FIXES_DAY2.md` does not exist** (not in the tree, not in git history). Until you point me to it, I lock
   **all visible copy on these four pages** word for word (stricter than rule 3), except the changes listed in section 7.
   The sidebar and bottom-bar behaviour I keep is the one recorded in DECISIONS D-174/D-175.
3. **Rule 6 overrides D-176**, which put a coloured left stripe on subscription cards and rows, gradient text on
   Priya's name, colour washes on the header and per-section rainbow hues. All of these go. I'll record this as D-191.
4. **Developer text on Priya's screen:** the footer's collapsed "Developer" menu (Health JSON, API docs) must stay,
   because `ui_check.py` clicks it on `/` and `test_user_page.py` expects it. It stays collapsed in a quiet footer. The
   sandbox mode pill's model name (`· gpt-5.4`, `.badge-model`) is hidden on Priya's dashboard with CSS only. It stays
   on `/?demo=1` for judges and in the pill's `title`.

Out of scope (rule 2 and the brief): the shops, `shop.css`, the companion overlay (`companion.js` `sg-*`), the evidence
page `/subscriptions/{id}`, and the mock PayPal page. They inherit tokens only where they already use the shared
classes. The evidence page uses `app.css`, so it gets the new tokens for free and is screenshotted but not restyled.

## 0b. Review changes (approved with these; they override the sections below)

1. Colour rules apply to this plan too. **Sidebar active item:** an ink marker / the `--surface-2` pill, no teal bar.
   **Reset on `/?demo=1`:** a ghost/secondary button with its existing confirm, not red (red = still at risk only).
2. **Intro:** `hero-brand` stays (tests) but becomes a small lockup: shield + name at `--t-lg`, ink. `topnav-signin`
   is a plain text link, so the hero "Sign in" is the only primary button in the first view.
3. D-176's decoration is removed: recorded as **D-191** (D-188..D-190 were already taken).
4. `UI_FIXES_DAY2.md` won't be added: all current copy stays word for word (section 7 lists the only changes).
5. Order: steps 1-3, then stop for review with screenshots. The `#sim-scrubber` ruler is the last, optional part of
   step 6: run `record_demo.py` / `check_scenes.py` before and after; any change in the recording or scenes ->
   revert it and leave the scrubber as it is.
6. Dark theme: check `--surface` on `--paper` in the screenshots; if cards don't separate without borders, raise the
   surface step a little (never borders or shadows).

## Progress

- **Step 1 tokens** (2026-11-12): `app/static/tokens.css` (loaded first by `base.html`) holds every colour, type,
  space and radius token, plus the old names as aliases. Every hex and `rgba()` in app/dashboard/home/demo/panels/
  auth/timeline.css is now a token (or a `color-mix()` of one), every `rem` font size a `--t-*` step, every px radius
  a `--r-*` step. D-176's colour block (section hues, gradient name, washes, card stripes) removed. Text on fills
  uses `--on-accent` / `--on-fill` / `--on-risk`; "ok" / done ticks and finished pipeline steps are green, not teal.
  Shots: `docs/img/v5/1-tokens/`. Not yet: borders, webfont, teal links (steps 2-6). Noticed for step 6: the
  "SubGuard" actor chips in "What SubGuard did" on `/?demo=1` overlap their text.

## 1. The idea: the deadline ruler

SubGuard's whole insight is **two dates**: the day the shop says the trial ends, and the earlier day you really have
to act. Everything else on the screen is quiet so that this one comparison is loud.

**The one memorable element: a measuring-rule timeline.** It has tick marks for each trial day in tabular numerals. The
merchant's "trial ends" sits at the far end in muted ink. A single teal notch cuts into the ruler at **Act by**, and
the first charge sits past the end in red. It appears in exactly three places, always drawn the same way:

- `/`: under the hero headline, built from `landing_view` (Day 0 → act by `act_by_day` → terms' last day
  `terms_last_day` → `trial_days` → first charge `first_charge_day`). This is the 10-second explanation.
- `/` signed in: the existing card timeline (`.stl`, its markup untouched) restyled as the same ruler.
- `/?demo=1`: the day scrubber (`#sim-scrubber`, a range input) restyled as the ruler, with the jump buttons as its
  labelled ticks.

No other decoration: no washes, no shadows under cards, no glows and no per-section colours.

## 2. Tokens

### Colour (6 named hexes per theme, all checked for WCAG AA)

| Token | Role | Light | Dark | Contrast on surface (L / D) |
|---|---|---|---|---|
| `--paper` | page background | `#E9EEEC` | `#152225` | |
| `--surface` | cards, sidebar, top bar | `#FFFFFF` | `#1D2D30` | |
| `--ink` | text | `#13201E` | `#E3ECEA` | 16.8 / 11.9 |
| `--ink-2` (muted) | secondary text | `#4D5E5A` | `#9DB0AC` | 6.9 / 6.3 |
| `--accent` (teal) | **only** the key number + the main button | `#0B6B68` | `#4CC9BF` | 6.3 / 7.1 |
| `--done` green | done | `#2A7539` | `#7ACB8E` | 5.7 / 7.3 |
| `--ask` amber | needs Priya's answer | `#8A5300` (text), `#F0B13A` (fill) | `#F2B544` | 6.3 / 7.8 |
| `--risk` red | still at risk | `#B0242E` | `#FF8080` | 6.7 / 5.9 |

- The main-button text is white on light-mode teal (6.3:1) and `#0F1B1D` on dark-mode teal (8.7:1). Amber fills carry
  ink text (8.8:1 / 9.6:1).
- Derived tokens: `--surface-2` (nested wells, the ruler's track), `--rule` (hairline and ruler ticks), `--focus`
  (= accent), `--overlay`, `--shadow-pop` (menus and dialogs only). These are built from the six with `color-mix()`,
  with a plain hex fallback first.
- **The key number** is the money figure SubGuard protects: `.key-num` on the card, "Saved so far", "Charges
  avoided". Links stop being teal: they use ink with an underline, so teal means only "the number" and "the next step".
- Dark mode is a deep petrol slate, not navy and not near-black. Light mode is a cool, slightly green statement-paper
  grey, not cream.
- Old token names (`--navy-900`, `--teal`, `--red`, `--amber`, `--ok`, …) stay as **aliases** of the new ones, so
  anything I don't restyle (evidence page, chat, dialogs, the companion's shared classes) keeps working.

### Type: one family

**Atkinson Hyperlegible Next** (Braille Institute, OFL), one variable `woff2`, Latin subset, vendored in
`app/static/vendor/fonts/` next to the AG Grid files (ui_check fails on CDN requests, and it must work offline).
- `font-display: swap`, fallback `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`.
- **Why this face:** it was designed so that look-alike characters (1/l/I, 0/O, 5/S) can't be confused. That fits a
  product about reading fine print and quoting it word for word. It is not a face I'd reach for on any other project.
- Used everywhere: pills, `code`, buttons, AG Grid (its `--ag-font-family`) and charts.
- If the font's tabular figures turn out to be missing, I'll report it and keep the face; money and dates already use
  `font-variant-numeric: tabular-nums`.

Scale (rem at 16 px; a classic 12/14/16/18/21/24/36/48 ladder):

| Token | Size / line height | Use |
|---|---|---|
| `--t-xs` | 0.75 / 1.4 | ruler numerals, tiny notes |
| `--t-sm` | 0.875 / 1.45 | secondary text, pills, grid |
| `--t-md` | 1 / 1.5 | body |
| `--t-lg` | 1.125 / 1.4 | card headlines, section titles |
| `--t-xl` | 1.3125 / 1.3 | page section headings |
| `--t-2xl` | 1.5 / 1.25 | greeting |
| `--t-3xl` | `clamp(2.25rem, 1.6rem + 2.6vw, 3rem)` / 1.1 | hero headline only |

Weights: 400 body, 600 labels and buttons, 750 key numbers and the hero. No all-caps anywhere: the existing
`text-transform: uppercase` and `letter-spacing` on eyebrows and section heads are removed. Measure: body copy is capped
at 68ch.

### Spacing, radii, elevation

- Space: `--s-1` 4, `--s-2` 8, `--s-3` 12, `--s-4` 16, `--s-5` 24, `--s-6` 32, `--s-7` 48, `--s-8` 64 (px).
- Radii by hierarchy, not one value for everything: `--r-ctl` 8 (buttons, inputs, chips), `--r-card` 14 (cards),
  `--r-panel` 20 (the sidebar and the presenter controls), `--r-pill` 999 (pills), `0` on the ruler.
- Elevation: cards are `--surface` on `--paper`, with no border and no shadow. Only floating things (menus, dialogs,
  toasts, the chat drawer) get `--shadow-pop`.
- Focus: `outline: 3px solid var(--focus); outline-offset: 2px` on every focusable element.
- Motion: one moment only, the ruler's notch sliding to Act by on first paint (300 ms). It is off under
  `prefers-reduced-motion`. The existing coin burst (JS, D-176) is unchanged and already skips reduced motion.

## 3. Wireframes

### `/` signed out (intro): left-aligned, one column, max 72ch for text

```
+------------------------------------------------------------------------------+
| [shield] SubGuard  (Demo data)                     Demo shops  Sign in  [moon] |
+------------------------------------------------------------------------------+
|                                                                              |
|  [shield] SubGuard                                                           |
|  AI reads the fine print. PayPal enforces the outcome.        (ink-2, t-lg)  |
|                                                                              |
|  SubGuard reads the fine print on free trials, and uses       (t-3xl, 750)   |
|  PayPal to stop the charge you didn't agree to.                              |
|                                                                              |
|  0    1    2    3    4    5    6   |7|   8    9    10  | 11                   |
|  |....|....|....|....|....|....|...|#|...|....|....|..|..|                   |
|  Signed up                       Act by  Terms'   Trial  First               |
|                                  (teal)  last day ends   charge (red)        |
|                                                                              |
|  [ Sign in ]  ( Browse the demo shops )                                      |
|                                                                              |
|  How it works with PayPal                                                    |
|  1  You subscribe with PayPal    2  SubGuard checks the    3  It cancels ... |
|     ...                             terms ...                 ...            |
|                                                                              |
|  What the AI does   (surface card, no border)                                |
|   Reads the fine print: ...                                                  |
|   Finds the traps: ...                                                       |
|   Quotes them word for word ...                                              |
|   Code, not the AI, makes every decision.                                    |
|                                                                              |
|  Fictional merchant for the SubGuard demo.                                   |
+------------------------------------------------------------------------------+
| Fictional merchant   PayPal Sandbox   Help center   Privacy   MIT   GitHub   |
+------------------------------------------------------------------------------+
390 px: the ruler keeps every tick and shows only the Act by and First charge labels under it (the others
become sr-only text). Buttons go full width.
```

### `/` signed in (Priya's dashboard): sidebar left, attention first

```
+------------------------------------------------------------------------------+
| [shield] SubGuard (PayPal Sandbox)  Priya's dashboard  Presenter v   [chat][moon][P]|
+------------------------------------------------------------------------------+
|  Hi Priya, here's your dashboard                        (t-2xl, plain ink)   |
|  No surprise charges. That's the plan                   (ink-2)              |
+----------------+-------------------------------------------------------------+
| [=] Collapse   |  Needs your attention                    (t-xl, sentence)   |
| Overview   *   |  +-------------------------------------------------------+  |
| Subscriptions 2|  | [Pw] Penwright Studio  Penwright Pro . free trial  87 v|  |
|   In use     0 |  |      $0 today, then $24.99/month ...  (key num teal)   |  |
|   Trials     2 |  |      (shield) My plan: I'll check in with you on ...   |  |
|   Cancelled  0 |  |  ---------------------------------------------------   |  |
| Activity    (1)|  |  sub-line ...                  [Keep] [Cancel trial]   |  |
| Emails         |  |  0 .... 5 .... |7| .. 8 .... 10 | 11   <- the ruler    |  |
| Analytics      |  |  See evidence      Verified with PayPal v              |  |
|                |  +-------------------------------------------------------+  |
| Coming up      |                                                             |
|  Penwright $24.99  +--------------------------+ +--------------------------+ |
|  Nov 22 . first |  | Saved so far            | | Recent activity          | |
|  charge (red)  |  | $123.98   (key, teal)    | | Nov 17  ok Cancelled ... | |
|                |  | ... in this demo         | | ...           See all    | |
| Settings       |  +--------------------------+ +--------------------------+ |
| (P) Priya ...  |                                                             |
+----------------+-------------------------------------------------------------+
- Sidebar: --surface, --r-panel, no border; the active item is an ink pill on --surface-2 with a 3px accent bar
  on its leading edge. That bar is nav state, not a card stripe. Icons are ink-2. Folded = 56 px icon strip
  (D-175, unchanged).
- Status colours appear only as text plus small marks: risk pill red, check-in amber, done tick green.
- 390 px: no sidebar; header, attention cards, Coming up card, Saved, Recent; the bottom bar is fixed with 4 items,
  --surface, and the active item is ink on --surface-2 (D-174 behaviour unchanged).
```

### `/?demo=1` (Live demo / presenter): judge-facing, two zones

```
+------------------------------------------------------------------------------+
| top bar (Presenter v is current)                                             |
+------------------------------------------------------------------------------+
| hero (same as intro, with sub paragraph)        | Meet Priya (surface card)  |
| [ Try it yourself: open the checkout ]          | "10-day free trial, $0..." |
|                                                 | 1 After 10 days ...        |
|                                                 | 2 ... Day 8, not Day 10    |
|                                                 | 3 no cancel button         |
|                                                 | Without: $524.88 (red)     |
|                                                 | With: $0.00 (teal key)     |
| 1 Before you pay   2 Before the deadline   3 At the deadline                  |
| Built with: PayPal Subscriptions API . JS SDK . MCP . model . AI proposes... |
+------------------------------------------------------------------------------+
| Run the demo yourself  v                                                     |
| +-- Controls (r-panel) ----------------------------------------------------+ |
| | Controls . today is Day 5             [ > Play Priya's story ] (teal)    | |
| | 1 Day 0 Sign-up ...  2 ...  (story list, two columns at 1440)            | |
| | Move the days yourself                                                   | |
| | 0 ... 5 ... 6 ... |7| ......... 11   <- the scrubber drawn as the ruler  | |
| | (Day 0 sign-up)(Day 5 check-in)(Day 6 timer)(Day 7 act-by)(Day 11) (+1)  | |
| | (Open Penwright shop)  (Open Quillnote shop)                             | |
| | (Quillnote connected: off) (See the full record)            [Reset] red  | |
| +--------------------------------------------------------------------------+ |
| The story, step by step:  (1)--(2)--(3)--(4)--(5)--(6)--(7)  done = green     |
| +-- Priya's side -----------------------------+ +-- Charges avoided -------+ |
| | Check-in (amber band, no border)            | | $24.99  (key, teal, 3xl) | |
| | Keep it or cancel?   [Keep] [Cancel trial]  | | What SubGuard did        | |
| +---------------------------------------------+ +--------------------------+ |
+------------------------------------------------------------------------------+
390 px: one column; the controls stack; the scrubber ruler shows 0, act-by and 11 labels only.
```

### `/login`

A single centred surface card (max 400 px), the heading, "Demo account: Priya", 44 px fields with a 16 px font
(already tested), the main button full width, and "← Back". No border.

## 4. Review against the skill's list of generic AI defaults

| Default the skill warns about | Where it is today | What I changed in the plan, and why |
|---|---|---|
| #2 near-black + one bright accent | navy `#0b1626` + bright teal | Deep petrol slate `#152225`, with teal softened to `#4CC9BF` and used in two places only. The base now relates to the teal instead of sitting under it. |
| #4 SaaS card kit: identical rounded bordered cards, the same shadow, gradient washes | every block is `.card` with a 1 px border, the header has washes, D-176 adds washes per card | No borders and no card shadows. Three radii by hierarchy. Washes and gradient text are removed. Cards are separated by tone and space. |
| #5 tracked ALL-CAPS eyebrows | "NEEDS YOUR ATTENTION", "COMING UP" with coloured dots | Sentence-case section heads at `--t-xl`. The dots go. |
| #5 a monospace face for data | none (already one font) | Kept to one family, including `code`. |
| #5 `→` appended to links | "Show all →" on `/?demo=1` | Changed to "Show all" (section 7). `↗` stays: it says "opens a new tab". |
| #5 middle-dot meta strings | footer separators; lots of locked copy | Footer `·` spans hidden with CSS and replaced by a gap. Locked copy keeps its dots (rule 3). |
| Hero as big number + small label + gradient | not today, but the obvious move for "money saved" | Rejected. The hero is the ruler, the product's actual argument. |
| Numbered markers when content isn't a sequence | 3 "how it works" steps, 7 pipeline steps | Both are real sequences, so the numbers stay. Nothing else gets numbers. |
| Rainbow per-section colour (D-176) | sky / violet / pink / amber sections | Removed. Colour now means only the key number, the next step, done, needs-answer and at-risk. |
| Scattered motion | hover lifts, pulse dots, fades | One moment (the ruler notch). The handoff's pulse dot stays: it shows live polling. |

First draft, revised before writing this: I first reached for "light = warm off-white paper + serif headlines for a
legal feel". That is default #1 almost exactly, so I swapped it for the cool statement-paper grey and the single
hyperlegible sans. Hyperlegibility is the subject-specific choice here; a serif would only have been costume.

## 5. AG Grid (step 5)

Restyled only through `--ag-*` CSS custom properties on `.ag-root-wrapper`, scoped by `html[data-ag-theme-mode=…]`
(`--ag-background-color`, `--ag-foreground-color`, `--ag-header-background-color`, `--ag-border-color`,
`--ag-odd-row-background-color`, `--ag-row-hover-color`, `--ag-accent-color`, `--ag-font-family`,
`--ag-font-size`, `--ag-wrapper-border-radius`). `grids.js` (its `withParams`, column definitions and grid options)
is not edited. If the Theming API's own variables win over mine, I'll raise specificity in CSS. I won't touch JS.

## 6. Build order and checks

As the brief says: 1 tokens, 2 type, buttons and pills, 3 `/` intro, 4 dashboard and sidebar, 5 AG Grid, 6 presenter
and login. Each step ends with a `ui3: <step>` commit. After every step:
`python scripts/tasks.py test`, `lint`, `ui-check`, plus screenshots at 1440x900 and 390x844 in light and dark into
`docs/img/v5/<step>/`, which I look at before moving on. A failing check means fix or revert, never continue.

The ruler on `/` is the only **new markup**: a `<figure class="dl-ruler">` in `intro.html` (and in `_hero.html` via a
new optional macro argument, so the Live demo's landing is unchanged unless the flag is set). Every number in it comes
from `landing_view`. All other steps are CSS plus new classes added next to existing ones.

## 7. Copy changes (everything else is unchanged)

| Where | Before | After |
|---|---|---|
| `demo.html` "What SubGuard did" | `Show all →` | `Show all` |
| `/` new ruler labels | (new) | `Signed up`, `Act by`, `Terms' last day`, `Trial ends`, `First charge` (the timeline's existing words, D-177), with "Day N" from `landing_view` |

## 8. Protected selectors (rule 1)

Rule followed: **no existing `id`, `data-*` attribute, `data-testid` or class is renamed or removed.** New classes are
only added. The lists below are generated from `app/templates/*.html`, cross-checked against `app/static/*.js`,
`tests/*.py`, `scripts/ui_check.py`, `scripts/sandbox_ui_check.py`, `demo-video/scenes.json`,
`demo-video/record_demo.py`, `check_scenes.py` and `schema.py`.

Also load-bearing (not selectors): `auth.css` must contain `font: 16px` (test_intro), phone inputs must be
>= 16 px (ui_check), no CDN requests (ui_check U30), and no hardcoded hosts in `.css` (test_hosting).

### Classes referenced by JS, tests, ui_check or the video scripts (194)

| class | referenced in |
|---|---|
| `ac-detail` | test_timeline.py |
| `ac-text` | test_timeline.py |
| `advice` | test_chat.py, test_scenario.py |
| `ai-vs-basic` | scenes.json, ui_check.py, test_ai_value.py, test_scenes.py |
| `avatar` | ui_check.py, test_account.py, test_dashboard.py |
| `avatar-menu` | user-nav.js, test_dashboard.py |
| `bad` | grids.js, test_ai_value.py, test_auditor.py, test_corner_cases.py, test_notices.py |
| `badge` | ui_check.py, test_user_page.py |
| `band` | autoplay.js, home.js, ui_check.py |
| `brand` | schema.py, ui_check.py, test_intro.py, test_pages.py, test_user_page.py, test_video_tooling.py |
| `btn` | app.js, autoplay.js, email.js, ui_check.py, test_demo_sandbox_start.py, test_pages.py, test_user_page.py |
| `btn-danger` | app.js |
| `btn-ghost` | app.js, email.js |
| `btn-sm` | email.js |
| `btn-start` | test_pages.py |
| `built` | companion.js, dash-charts.js, scenes.json, test_chat.py, test_pages.py, test_paypal_sdk.py, test_run_summary.py |
| `card` | app.js, autoplay.js, chat.js, companion.js, evidence.js, home.js, paypal-card.js, user-nav.js, scenes.json, schema.py, sandbox_ui_check.py, ui_check.py, story_helpers.py, test_account.py, test_ai_value.py, test_chat.py, test_demo_sandbox_start.py, test_key_dates.py, test_pages.py, test_paypal_card.py, test_paypal_sdk.py, test_policy.py, test_scenario.py, test_scenes.py, test_user_page.py, test_v3_phase3.py, test_video_tooling.py |
| `chain` | grids.js, home.js, ui_check.py, test_user_page.py |
| `chart` | charts.js, ui_check.py, test_user_page.py |
| `chart-empty` | charts.js, dash-charts.js |
| `charts` | charts.js, dash-charts.js, evidence.js, user-nav.js, ui_check.py, test_user_page.py |
| `chat` | chat.js, user-nav.js, ui_check.py, test_chat.py, test_intro.py, test_llm_providers.py, test_notices.py, test_scenario.py, test_scenes.py |
| `chat-form` | chat.js |
| `chat-log` | chat.js |
| `chat-suggest` | chat.js |
| `chip` | chat.js, grids.js, user-nav.js, test_chat.py |
| `chips` | chat.js, ui_check.py, test_chat.py |
| `coin` | app.js, ui_check.py |
| `coin-burst` | app.js |
| `coin-plus` | app.js, ui_check.py |
| `confirm-card` | app.js, scenes.json, sandbox_ui_check.py, ui_check.py, test_pages.py |
| `dash` | ui_check.py |
| `day-bump` | home.js |
| `delivery` | test_deploy.py, test_policy.py, test_story.py |
| `demo` | app.js, autoplay.js, autoplay_sandbox.js, chat.js, companion.js, email.js, home.js, presenter.js, user-nav.js, sandbox_ui_check.py, ui_check.py, conftest.py, story_helpers.py, test_account.py, test_dashboard.py, test_demo_sandbox_start.py, test_pages.py, test_paypal_gateway.py, test_run_summary.py, test_scenario.py, test_story.py, test_user_page.py |
| `demo-priya` | ui_check.py, test_pages.py, test_user_page.py |
| `dev-menu` | ui_check.py, test_pages.py, test_user_page.py |
| `dialog` | autoplay.js, companion.js, email.js |
| `did` | ui_check.py, test_run_summary.py, test_timeline.py, test_user_page.py |
| `done` | autoplay.js, autoplay_sandbox.js, chat.js, companion.js, email.js, home.js, presenter.js, ui_check.py, story_helpers.py, test_ai_value.py, test_chat.py, test_key_dates.py, test_notices.py, test_run_summary.py, test_scenario.py, test_story.py, test_user_page.py, test_video_tooling.py |
| `dot` | app.js, presenter.js |
| `drawer` | grids.js, presenter.js, ui_check.py, test_run_summary.py |
| `email-card` | email.js |
| `email-demo-note` | email.js |
| `email-dialog` | email.js |
| `email-ok` | email.js |
| `email-pre` | email.js |
| `evidence` | charts.js, companion.js, evidence.js, paypal-card.js, ui_check.py, test_pages.py, test_paypal_card.py, test_scenario.py, test_user_page.py |
| `field` | email.js, record_demo.py, schema.py, ui_check.py |
| `grid` | app.js, grids.js, presenter.js, ui_check.py |
| `health` | app.js, record_demo.py |
| `hero` | test_intro.py |
| `hero-brand` | test_pages.py |
| `hi-name` | scenes.json, test_auth.py, test_pages.py, test_user_page.py, test_video_tooling.py |
| `hl-back` | email.js |
| `hl-key` | email.js |
| `hl-wrap` | email.js |
| `honest` | test_ai_value.py, test_corner_cases.py, test_pages.py, test_v3_review.py |
| `how` | paypal-card.js, scenes.json, test_pages.py |
| `intro-ai` | test_intro.py |
| `is-` | presenter.js |
| `is-active` | presenter.js |
| `is-bumped` | home.js |
| `is-celebrating` | app.js |
| `is-done` | presenter.js, ui_check.py |
| `is-key` | ui_check.py, test_user_page.py |
| `is-new` | autoplay.js |
| `is-skipped` | presenter.js |
| `is-warn` | presenter.js |
| `js-day` | home.js |
| `js-ft` | presenter.js |
| `kpi` | autoplay.js, home.js, test_scenario.py, test_story.py |
| `landing` | presenter.js, test_pages.py |
| `light` | app.js, charts.js, companion.js, dash-charts.js, grids.js, record_demo.py, ui_check.py, test_user_page.py |
| `menu` | user-nav.js, ui_check.py, test_dashboard.py |
| `menu-body` | app.js, user-nav.js |
| `money` | app.js, charts.js, dash-charts.js, home.js, ui_check.py, test_auditor.py, test_pages.py, test_pricing.py, test_scenario.py |
| `msg` | app.js, chat.js, schema.py |
| `msg-` | chat.js |
| `msg-card` | chat.js |
| `msg-warn` | chat.js |
| `muted` | email.js, grids.js |
| `my-plan` | test_user_page.py |
| `nav-label` | user-nav.js |
| `notice` | scenes.json, ui_check.py, test_ai_value.py, test_auditor.py, test_chat.py, test_notices.py, test_story.py, test_v3_phase3.py |
| `offer` | companion.js, ui_check.py, test_llm_providers.py, test_pages.py |
| `ok` | grids.js, test_ai_value.py, test_audit_log.py, test_auth.py, test_chat.py, test_demo_sandbox_start.py, test_pages.py, test_paypal_card.py, test_paypal_gateway.py, test_paypal_seed.py, test_policy.py, test_run_summary.py, test_scenario.py, test_store.py, test_story.py, test_v3_phase3.py |
| `order-confirm` | autoplay.js, ui_check.py, test_pages.py |
| `panel` | autoplay.js, chat.js, dash-charts.js, user-nav.js, ui_check.py, test_dashboard.py, test_user_page.py |
| `pill` | grids.js, paypal-card.js, record_demo.py, test_user_page.py, test_video_tooling.py |
| `pill-` | (set by JS) |
| `pipe-done` | autoplay.js |
| `pipe-fill` | autoplay.js, presenter.js |
| `pipe-saved` | autoplay.js |
| `pipe-status` | autoplay.js |
| `pipeline` | ui_check.py, test_auditor.py, test_pages.py |
| `plain` | app.js, companion.js, grids.js, ui_check.py, test_access_log.py, test_auditor.py, test_pages.py, test_paypal_sdk.py, test_run_summary.py, test_timeline.py, test_user_page.py, test_v3_phase3.py |
| `pp-card` | paypal-card.js |
| `pp-cycles` | paypal-card.js |
| `pp-earlier` | paypal-card.js |
| `pp-grid` | paypal-card.js |
| `pp-head` | paypal-card.js |
| `pp-line` | paypal-card.js |
| `pp-link` | paypal-card.js |
| `pp-mark` | paypal-card.js |
| `pp-meta` | paypal-card.js |
| `pp-more` | paypal-card.js |
| `pp-plan` | paypal-card.js |
| `pp-row` | paypal-card.js |
| `pp-status` | paypal-card.js |
| `pp-title` | paypal-card.js |
| `pp-warn` | paypal-card.js |
| `presenter` | autoplay_sandbox.js, presenter.js, ui_check.py, test_demo_sandbox_start.py, test_pages.py |
| `priya-card` | test_pages.py |
| `priya-money` | test_pages.py |
| `proof-banner` | ui_check.py, test_user_page.py |
| `row` | app.js, autoplay.js, chat.js, email.js, grids.js, ui_check.py, test_corner_cases.py, test_pages.py, test_user_page.py |
| `rule-chip` | test_timeline.py |
| `run-demo` | presenter.js, test_pages.py |
| `saved-seal` | autoplay.js |
| `saved-total` | test_dashboard.py |
| `settings` | check_scenes.py, record_demo.py, sandbox_ui_check.py, conftest.py, story_helpers.py, test_dashboard.py, test_policy.py, test_sandbox_smoke.py, test_user_page.py |
| `sev` | companion.js, grids.js |
| `sg-actions` | companion.js |
| `sg-back` | companion.js |
| `sg-backdrop` | companion.js |
| `sg-body` | companion.js |
| `sg-btn` | companion.js |
| `sg-card` | companion.js |
| `sg-chip` | companion.js |
| `sg-consent` | companion.js |
| `sg-dates` | companion.js |
| `sg-evidence` | companion.js |
| `sg-go` | companion.js |
| `sg-h3` | companion.js |
| `sg-head` | companion.js |
| `sg-ico` | companion.js |
| `sg-label` | companion.js |
| `sg-light` | companion.js |
| `sg-loading` | companion.js |
| `sg-mode` | companion.js |
| `sg-promise` | companion.js |
| `sg-q` | companion.js |
| `sg-quotes` | companion.js |
| `sg-risk` | companion.js |
| `sg-sec` | companion.js |
| `sg-shield` | companion.js |
| `sg-spin` | companion.js |
| `sg-sub` | companion.js |
| `sg-summary` | companion.js |
| `sg-t` | companion.js |
| `sg-table` | companion.js |
| `sg-things` | companion.js |
| `sg-verdict` | companion.js |
| `side-toggle` | user-nav.js, test_dashboard.py |
| `sidebar` | user-nav.js |
| `sl-filters` | user-nav.js |
| `small` | email.js, grids.js, ui_check.py, test_ai_value.py |
| `sr-only` | companion.js |
| `step` | autoplay.js, home.js, presenter.js, scenes.json, schema.py, test_pages.py, test_run_summary.py, test_user_page.py |
| `step-detail` | autoplay.js, presenter.js |
| `step-dot` | autoplay.js, presenter.js |
| `steps` | autoplay.js, autoplay_sandbox.js, companion.js, presenter.js, record_demo.py, ui_check.py, test_chat.py, test_run_summary.py |
| `stl-date` | test_user_page.py |
| `stl-node` | test_user_page.py |
| `story` | autoplay.js, home.js, presenter.js, sandbox_ui_check.py, ui_check.py, test_pages.py, test_scenario.py, test_story.py, test_user_page.py, test_v3_story.py |
| `story-actions` | test_user_page.py |
| `story-sub` | test_user_page.py |
| `sub` | autoplay.js, charts.js, dash-charts.js, sandbox_ui_check.py, test_checkout.py, test_demo_sandbox_start.py, test_key_dates.py, test_paypal_gateway.py, test_pricing.py, test_review_api.py, test_store.py, test_v3_phase3.py, test_v3_story.py |
| `sub-card` | scenes.json, ui_check.py, test_dashboard.py, test_user_page.py |
| `sub-fold` | test_user_page.py |
| `sub-headline` | scenes.json, ui_check.py, test_user_page.py |
| `sub-tile` | test_user_page.py |
| `subs` | paypal-card.js, sandbox_ui_check.py, test_corner_cases.py, test_paypal_sdk.py, test_video_tooling.py |
| `switch` | test_chat.py |
| `table` | companion.js, test_v3_phase3.py |
| `theme-toggle` | app.js, ui_check.py, test_pages.py, test_user_page.py |
| `things` | companion.js, ui_check.py, test_ai_value.py, test_pages.py, test_v3_phase3.py |
| `tiny` | email.js, scenes.json |
| `toast` | app.js, ui_check.py, test_account.py |
| `toast-` | app.js |
| `toast-close` | app.js |
| `toasts` | app.js, home.js |
| `topbar` | ui_check.py, test_dashboard.py, test_user_page.py |
| `topnav-signin` | ui_check.py, test_intro.py |
| `traps` | ui_check.py |
| `up-danger` | test_dashboard.py |
| `up-row` | test_dashboard.py |
| `usage` | charts.js, conftest.py, test_demo_sandbox_start.py, test_llm_providers.py, test_pages.py, test_user_page.py |
| `warn` | autoplay.js, companion.js, email.js, presenter.js, test_run_summary.py |
| `who` | test_run_summary.py, test_user_page.py |
| `with` | app.js, autoplay.js, autoplay_sandbox.js, charts.js, companion.js, email.js, evidence.js, home.js, paypal-card.js, presenter.js, check_scenes.py, record_demo.py, scenes.json, schema.py, sandbox_ui_check.py, ui_check.py, conftest.py, story_helpers.py, test_account.py, test_audit_log.py, test_auditor.py, test_auth.py, test_config.py, test_corner_cases.py, test_dashboard.py, test_demo_sandbox_start.py, test_deploy.py, test_hosting.py, test_intro.py, test_llm_providers.py, test_pages.py, test_paypal_card.py, test_paypal_gateway.py, test_paypal_rest.py, test_paypal_sdk.py, test_policy.py, test_pricing.py, test_review_api.py, test_run_summary.py, test_sandbox_smoke.py, test_scenario.py, test_shop_session.py, test_store.py, test_story.py, test_user_page.py, test_video_tooling.py |
| `without` | email.js, check_scenes.py, record_demo.py, sandbox_ui_check.py, test_auditor.py, test_dashboard.py, test_notices.py, test_policy.py, test_review_api.py, test_run_summary.py, test_story.py, test_user_page.py, test_v3_story.py, test_video_tooling.py |
| `you` | autoplay.js, charts.js, companion.js, grids.js, presenter.js, ui_check.py, test_account.py, test_ai_value.py, test_chat.py, test_intro.py, test_key_dates.py, test_pages.py, test_review_api.py, test_run_summary.py, test_scenario.py, test_story.py, test_user_page.py, test_v3_review.py, test_v3_story.py |

### Element ids (all frozen) (101)

`about`, `act-h`, `an1-h`, `an2-h`, `an3-h`, `att-h`, `audit-drawer`, `audit-export`, `audit-filter`, `audit-grid`, `audit-h`, `audit-routine`, `avb-h`, `chain`, `chat`, `chat-close`, `chat-form`, `chat-input`, `chat-log`, `chat-open`, `chat-suggest`, `confirm-dialog`, `conn-h`, `data-h`, `decision-skip`, `demo-bar`, `demo-reset`, `demo-start`, `did-h`, `email`, `ev-activity`, `ev-evidence`, `ev-paypal`, `ev-paypal-card`, `ev-summary`, `evidence`, `findings-data`, `findings-grid`, `health`, `hero-h`, `ins-h`, `intro-ai-h`, `intro-how-h`, `kpi-protected`, `live-badge-activity`, `live-badge-emails`, `live-coming`, `live-coming-m`, `live-did`, `live-emails`, `live-kpis`, `live-priya`, `live-saved`, `live-subs`, `live-subs-list`, `live-timeline`, `login-h`, `mail-h`, `main`, `order-approve`, `order-confirm`, `order-h`, `order-text`, `panel-activity`, `panel-analytics`, `panel-emails`, `panel-overview`, `panel-settings`, `panel-subscriptions`, `password`, `pipe-done`, `pipe-fill`, `pipe-h`, `pipe-status`, `pipeline`, `pipeline-steps`, `pr-h`, `priya-card-h`, `priya-h`, `prof-h`, `profile`, `run-demo`, `saved-h`, `sec-h`, `set-h`, `settings-form`, `settings-status`, `side-toggle`, `sidebar`, `sim-scrubber`, `sim-ticks`, `sl-h`, `sub-audit-export`, `sub-audit-grid`, `sub-audit-routine`, `subs-add-hint`, `theme-toggle`, `toasts`, `toggle-fair-trial`, `up-h`, `up-m-h`

### data-* attributes (all frozen) (51)

`data-action`, `data-actor`, `data-advance`, `data-alert`, `data-analytics-sub`, `data-cancel`, `data-card`, `data-celebrate`, `data-chart`, `data-chart-sub`, `data-close-audit`, `data-countup`, `data-day`, `data-dchart`, `data-dchart-sub`, `data-email-open`, `data-ev-panel`, `data-ev-tab`, `data-evidence`, `data-filter`, `data-go`, `data-group`, `data-h`, `data-help`, `data-hint`, `data-jump`, `data-key`, `data-kind`, `data-live`, `data-merchant`, `data-nav`, `data-open-audit`, `data-panel`, `data-poll-sub`, `data-pp-body`, `data-pp-full`, `data-pp-status`, `data-pp-sub`, `data-proof`, `data-sandbox`, `data-sim-day`, `data-sl-more`, `data-soon`, `data-source`, `data-state`, `data-step`, `data-sub`, `data-sub-`, `data-sub-details`, `data-tip`, `data-user`

### data-testid values (all frozen) (220)

`act-by`, `action-autopay`, `action-needed`, `action-review-email`, `activity-list`, `activity-raw-log`, `ai-vs-basic`, `alert-cancel`, `alert-keep`, `all-clear`, `attention`, `audit-chain`, `audit-chain-mini`, `audit-drawer`, `audit-filter`, `audit-full-toggle`, `audit-log-export`, `audit-log-grid`, `audit-routine`, `audit-summary`, `audit-summary-row`, `autopay-cancel`, `autopay-cancelled`, `autopay-demo-note`, `autopay-empty`, `avatar-dashboard`, `avatar-emails`, `avatar-help`, `avatar-profile`, `avatar-settings`, `avatar-signed-in`, `avatar-signout`, `avb-act-by`, `avb-notice`, `avb-notice-quote`, `avb-risk`, `avb-verdict`, `brand`, `built-ai`, `built-with`, `cancellation-notice`, `card-never-charged`, `card-saved`, `change-plan`, `chart-cost`, `chart-monthly`, `chart-risk`, `chart-saved`, `chart-upcoming`, `chart-usage`, `chat-chip-email`, `chat-chip-keep`, `chat-chip-nothing`, `chat-close`, `chat-input`, `chat-open`, `chat-provider`, `chat-send`, `coming-up`, `conn-paypal`, `conn-paypal-mode`, `conn-zapier`, `connected-accounts`, `crosscheck-table`, `dash-head`, `data-card`, `decision-skip`, `delete-account`, `delivery`, `demo-bar`, `demo-day`, `demo-open-dashboard`, `demo-open-quillnote`, `demo-open-shop`, `demo-priya`, `demo-priya-empty`, `demo-start`, `demo-subs`, `dev-docs`, `dev-health`, `dev-menu`, `download-activity`, `email-review`, `empty-open-shop`, `ev-activity`, `ev-paypal-card`, `ev-raw-log`, `ev-verdict`, `evidence-tabs`, `findings-grid`, `footer`, `footer-github`, `footer-help`, `footer-license`, `footer-privacy`, `health-dots`, `hero`, `hero-brand`, `hero-try`, `hi-name`, `honest-note`, `how-it-works`, `injection-note`, `intro`, `intro-ai`, `intro-fictional`, `intro-rule`, `intro-shops`, `intro-signin`, `landing`, `layer2-controls`, `layer2-waiting`, `live-demo`, `login-back`, `login-email`, `login-error`, `login-form`, `login-hint`, `login-page`, `login-password`, `login-submit`, `mock-autopay`, `mode-badge`, `my-plan`, `my-plan-text`, `nav-activity`, `nav-analytics`, `nav-emails`, `nav-overview`, `nav-settings`, `nav-subscriptions`, `order-approve`, `order-confirm`, `order-text`, `panel-activity`, `panel-analytics`, `panel-emails`, `panel-overview`, `panel-settings`, `panel-subscriptions`, `partner-note`, `paypal-sub-id`, `paypal-verified`, `pipeline`, `pipeline-status`, `presenter-audit`, `priya-card`, `priya-money`, `priya-traps`, `profile-card`, `profile-edit`, `profile-email`, `proof-banner`, `reminder-advice`, `reminder-usage`, `risk-score`, `run-demo`, `saved-so-far`, `saved-total`, `sec-2fa`, `sec-password`, `security-card`, `settings-auto-cancel`, `settings-auto-send`, `settings-form`, `settings-remind-email`, `settings-status`, `side-coming-up`, `side-last-signin`, `side-nav`, `side-toggle`, `side-user`, `sim-plus-1`, `sim-reset`, `sim-scrubber`, `sim-toggle-fair-trial`, `story-steps`, `sub-audit-export`, `sub-card`, `sub-headline`, `sub-line`, `sub-row`, `sub-toggle`, `subs-action`, `subs-add`, `subs-add-hint`, `subs-empty`, `subs-ended`, `subs-filters`, `subs-list`, `subs-risk`, `subs-row`, `subs-source`, `subs-status`, `theme-toggle`, `tl-day`, `tl-email`, `tl-entry`, `tl-proof`, `tl-proof-body`, `tl-today`, `topnav`, `topnav-dashboard`, `topnav-demo`, `topnav-presenter`, `topnav-shop`, `topnav-shops`, `topnav-signin`, `trial-timeline`, `user-analytics`, `user-avatar`, `user-avoided`, `user-dashboard`, `user-email-ready`, `user-empty`, `user-protected`, `user-reminder`, `user-year-one`, `view-review`, `what-is-subguard`
