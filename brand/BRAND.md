# Training Console: brand assets for the marketing page

All values below are pulled from the live app (`app/web/app.css`, `app.js`, `icon.svg`).
Screenshots in `screens/` use a demo athlete ("Alex") with made-up, aspirational data.

---

## Paste-in block: VISUAL IDENTITY (replaces the bracketed section of the prompt)

```
# VISUAL IDENTITY (match the actual dashboard)
- Background: pure black #000000 (the app is true black, iOS-dark style).
- Surface/card color: #1C1C1E; raised surface / inactive buttons #2C2C2E;
  hairline dividers #38383A.
- Text: primary #F5F5F7, secondary #AEAEB2, muted/captions #86868B.
- Primary accent: #0A84FF (system blue: active states, primary buttons, run sessions,
  the main chart series). Secondary accent: #30D158 (green: done, on track, recovery OK).
- Status colors: warn #FF9F0A (orange), stop/health hold #FF453A (red).
- Sport color coding: Run #0A84FF (blue) · Strength #FF375F (pink) ·
  Swim + Bike #64D2FF (teal) · Rest #86868B (gray).
  Phase timeline segments use these too: base/build in blue, peak/taper in teal at
  85%/35% opacity, health hold in red.
- Tinted fills: the accent at 12-16% opacity on black (e.g. pills: #0A84FF @ 14%,
  #30D158 @ 14%, #FF9F0A @ 14%, #FF453A @ 14%); glow/borders at 35-45%.
- Typeface(s): SF Pro (system font: -apple-system) for all UI text; SF Mono for
  every number (big stats, dates, paces, heart rates). For the website use Inter
  (display 700, tight tracking -0.03em on headlines; 400 body) and JetBrains Mono for
  numerals, which matches the app's sans + mono pairing.
- Type scale in the app: page title 30px/800 (-0.03em); big stat numerals 28-30px mono
  800 (-0.03em); card titles 22px/700; body 15px/1.45; section labels 11px/700
  UPPERCASE, letter-spacing 0.08em, muted gray.
- Corner radius: cards 16px; inner tiles and buttons 10-12px; segmented tab bar 12px
  outer / 9px inner; pills fully round (999px); small chips 6px.
- Layout: single centered column, max-width 760px, 16px gutters, 12px gap between cards.
  Cards are flat (no shadows), separated by spacing and 1px #38383A hairlines.
- Chart style: flat and minimal. Rounded bars (3px radius) in #0A84FF for actuals;
  planned values as short 2px #64D2FF tick lines; trend lines 2px with no fill
  (orange #FF9F0A for effort/RPE); gridlines #2C2C2E; axis labels 10-11px #86868B.
  No 3D, no gradients inside charts, no drop shadows.
- Iconography: almost none, by design. Sessions are marked with a 4px colored vertical
  bar or a 7px dot in the sport color; status uses ✓ ✕ ▲ ● glyphs inside tinted pills.
  App icon: black square, a rising blue (#0A84FF) line chart with round caps, ending in
  a green (#30D158) dot (icons/icon.svg).
- Signature components: segmented tab bar (Today · Plan · Trends · Reports · Pat-GPT);
  countdown cards ("101 days · IM 70.3 Puerto Rico", the primary one outlined in blue);
  the "How was it?" 3-tap check-in (1-10 RPE grid, Good/Fine/Bad, pain yes/no);
  workout card with huge mono stats ("4 mi ~44 min Z2") and paired tiles (pace, HR cap);
  "Best time: Thu 6:00 PM · feels like 50°F" line; red health-hold card with checklist.
```

---

## Reality check: the prompt vs. the product as built

The prompt was written from the earlier prototype. Several claims don't match what the
dashboard does today. A product page should only promise what exists, so I'd swap these:

| Prompt says | What's actually built | Suggested change |
|---|---|---|
| Exports .FIT files to Garmin | Garmin is a **data source** (activities sync in). Workouts reached the watch once, by hand, not via .FIT export. | Section 5: "Your watch, already synced." Garmin, Oura and Hevy flow in automatically. Drop the .FIT chip; remove ".FIT" from Specs. |
| Hevy: AI builds routines live | Hevy **syncs logged lifts in**; the planner places strength sessions. No routine writing into Hevy. | Section 6 → **Pat-GPT**: "Ask. It moves your week." The chat proposes a change, checks the rules, and applies it when you tap Confirm. |
| Double progression, sets auto-advance | Bench estimated-1RM **trend** is tracked; no auto-advancing set/rep targets. | Keep the 225 chart, but say "every set tracked toward 225" rather than "auto-advance". |
| Body recomp trend chart | DEXA + metabolic-rate snapshots drive **daily calorie/protein targets**; there's no recomp chart in the app yet. | Section 7 → "Fuel that follows the work." (calories rise and fall with tomorrow's training), or keep the recomp chart as a clearly future-facing visual. |
| AI generates phase updates | A **rules-based planner** rebuilds each week from a weekly report; AI writes the report narrative. | "The plan rewrites itself every Sunday." |
| Phase timeline | The phase names and dates exist; the horizontal timeline is styled (`.phasebar` in the CSS) but isn't on screen today. | Fine for marketing; it's the same data. |

**Strong features the prompt leaves out** (good bento tiles):
- **Health gate:** illness or injury puts training on hold until cleared, then a graded comeback. "Comes back when you do."
- **Best time to train:** uses the forecast and your work calendar. "Fits around your calendar."
- **Auto-rebase:** a missed long run gets re-placed later in the week, with 7-day undo. "Missed it? Handled."
- **Readiness:** Oura readiness and resting HR cap intensity on bad mornings.
- **Travel-aware:** time zone and weather follow the trip; run-only weeks on the road.
- **Notifications:** tomorrow's workout at 8:30 PM, "How was it?" after.

Suggested Specs rows: Platforms: Web app, installs on iPhone · Integrations: Garmin, Oura,
Hevy, Google Calendar · Methodology: Friel periodization (3:1 build/recover), 10% ramp rule,
heat and recovery gates · Coach: Pat-GPT (Claude) · Exports: CSV backup.

---

## Demo data used in the screenshots (reuse on the page)
- Athlete: "Alex" · Phase: Base 2 · Date: Thu, Dec 3
- Countdowns: IM 70.3 Puerto Rico 101 days (goal 6:23, stretch 6:00) · IM Lake Placid 234 days
- Today: Easy run 4 mi, ~44 min, Z2, pace 10:45-11:30/mi, HR ≤ 140, best time 6:00 PM, feels like 50°F
- Weekly run miles: ~20 per week, building 8% after a clean week
- Bench: top set climbs from 185 lb toward the 225 goal line (the app labels it "off track" until it gets there; restyle that pill for the page)
- Fuel today: 2,720 kcal · protein 1 g/lb
- Weekly report: "Seven of seven sessions, 21.4 run miles, and every easy run actually stayed easy."
- Readiness 78-91, resting HR 46-50

## Files
- `icons/icon.svg`, `icon-512.png`, `icon-192.png`, `icon-180.png`: app icon
- `screens/phone-*.png`: 390-wide iPhone screens at 3x (Today, Plan, Trends, Reports, Pat-GPT; `-full` = whole page)
- `screens/desktop-*.png`: 1440-wide at 2x (Today, Plan, Trends)
