# ROLE
You are a senior product-marketing designer on a world-class design team. Your creative
director is a CMO who has shipped flagship product pages. The bar is the restraint, pacing,
and polish of apple.com product pages. Every section should feel inevitable, not decorated.

# THE PRODUCT
"Training Console": a personal training coach for hybrid athletes who train for triathlon
and strength at the same time. It is a phone-first web app (installs on iPhone) that:
- Plans every week automatically with Joe Friel-style periodization
  (Base -> Build -> Peak -> Race), shown as a horizontal phase timeline, and rebuilds the
  plan every Sunday from a weekly report on what actually happened
- Places strength around endurance by the rules (no heavy legs before a long run) and
  tracks lifts like a bench press climbing toward a 225 lb goal
- Picks the best time for each workout from the weather forecast and your work calendar
- Syncs automatically from Garmin (workouts), Oura (sleep, readiness) and Hevy (lifts)
- Has a health gate: when you're sick or hurt, training pauses; after clearance it brings
  you back with a graded comeback, never a jump back to full volume
- Pat-GPT, a built-in coach you can ask anything; it can move a workout for you, checks
  every safety rule first, and changes nothing until you tap Confirm
- A 3-tap check-in after each workout ("How was it?") that eases the next two days if
  something felt wrong
- Re-plans a missed long run later in the week on its own (undo for 7 days)
- Phone notifications: tomorrow's workout the night before, a check-in after
Use clean, aspirational DEMO data throughout (athlete "Alex"). No real personal metrics.

# VISUAL IDENTITY (match the actual dashboard; screenshots attached)
- Background: pure black #000000. Cards #1C1C1E; raised surfaces and inactive buttons
  #2C2C2E; hairline dividers #38383A.
- Text: primary #F5F5F7, secondary #AEAEB2, muted captions #86868B.
- Primary accent: #0A84FF (blue). Secondary accent: #30D158 (green, "done / on track").
  Status: warning #FF9F0A (orange), health hold #FF453A (red).
- Sport color coding: Run #0A84FF (blue) | Strength #FF375F (pink) |
  Swim + Bike #64D2FF (teal) | Rest #86868B (gray).
- Tints: pills and highlights use the accent at about 14% opacity on black; glows and
  borders at 35-45%.
- Typeface(s): the app uses SF Pro for text and SF Mono for every number. On the site use
  Inter (display weights 600-700, tracking -0.03em on headlines; 400 for body) and
  JetBrains Mono for numerals, so big stats read like the app.
- Corner radius: cards 16px, buttons and tiles 10-12px, pills fully round.
- Charts: flat and minimal. Rounded bars (3px) in blue for actuals, short 2px teal ticks
  for planned values, 2px trend lines with no fill, faint #2C2C2E gridlines, small gray
  axis labels. No 3D, no gradients inside charts.
- Iconography: almost none. Sessions are marked by a thin colored bar or dot in the sport
  color; status uses small check / cross / triangle glyphs in tinted pills. App icon: a
  rising blue line on black ending in a green dot (attached).
- Signature UI to feature: countdown cards ("101 days, IM 70.3 Puerto Rico"); the
  workout card with huge mono stats ("4 mi  ~44 min  Z2") and the line "Best time:
  6:00 PM, feels like 50°F"; the "How was it?" check-in; a Pat-GPT proposal card with
  Confirm / Cancel.
The page should feel like the dashboard's world, elevated: same palette, more air.

# DESIGN LANGUAGE (the "Apple product page" feel)
- One idea per section. Huge headline, one short supporting line, one hero visual.
- Massive negative space. Content max-width ~980px for text, full-bleed for visuals.
- Headline scale: 64-96px desktop, short and declarative (2-5 words).
- Subheads: 21-28px, muted gray, one sentence.
- Dark, cinematic sections, with at most one light section for rhythm.
- Product renders are the hero: the app shown in a sleek, generic phone frame (primary)
  and laptop frame (secondary), no real-brand hardware logos, soft reflections, a subtle
  blue glow, gentle perspective tilt. Use the attached screenshots as the screen content.
- Restrained motion cues: indicate scroll-driven reveals (fade-up, scale-in, sticky
  pinned visuals) with annotations on the artboard.
- No clutter: no stock photos, no badges, no gradients-for-their-own-sake, no emoji.

# PAGE STRUCTURE (desktop artboard 1440 wide; mobile artboard 390 wide)
1. Sticky nav: wordmark "Training Console" left; section links (Overview, Plan, Coach,
   Health, Specs); small pill CTA "Get started" right. Translucent blur bar.
2. Hero: eyebrow "Training Console" in blue. Headline: "Two sports. One brain."
   Subhead: "Strength and triathlon, planned together." Phone render rising into view,
   laptop behind it.
3. Phase timeline: full-width close-up of the Base -> Build -> Peak -> Race timeline with
   a "you are here" marker. Headline: "Every week knows its place." One line: the plan
   builds for three weeks, eases for one, and peaks right before race day.
4. The plan rewrites itself: a week view where Sunday's report reshapes next week (sessions
   sliding into place). Headline: "Next week, already written." Large stat callout "+8%"
   with caption "volume after a clean week. Less after a rough one."
5. Best time to train: phone render of the workout card with "Best time: 6:00 PM, feels
   like 50°F", a soft weather curve and calendar blocks behind it. Headline:
   "Fits around your day."
6. Pat-GPT: split layout. Left, a short chat ("Move Saturday's long run, dinner Saturday");
   right, the proposal card with Confirm. Headline: "Ask. It moves your week."
   Subhead: "Every change is checked against the rules, and nothing happens until you say so."
7. Health gate: the one light section. A calm card that turns from red "Health hold" to
   green "Return to training", with a 21-day comeback ramp line. Headline:
   "Comes back when you do."
8. Strength, placed right: pinned bench-press chart climbing toward a 225 goal line.
   Headline: "Strength that doesn't cost you the long run." Stat callout "225" with caption
   "lb goal, tracked set by set."
9. Feature grid ("Everything, at a glance"): 6 bento tiles, mixed sizes, icon + 3-word
   title + one line each:
   - "How was it?": three taps after every workout; a bad day eases the next two.
   - "Missed it? Handled.": a missed long run moves later in the week, with undo.
   - "Readiness built in": Oura sleep and resting heart rate cap a rough morning.
   - "Travel-aware plans": time zone and weather follow the trip.
   - "Fuel that follows": calories and protein rise and fall with tomorrow's training.
   - "Tomorrow, the night before": an 8:30 PM notification with the workout and best time.
10. Specs strip: clean table rows. Platforms: web app, installs on iPhone.
    Integrations: Garmin, Oura, Hevy, Google Calendar. Coach: Pat-GPT, powered by Claude.
    Methodology: Friel periodization (3:1 build/recover), 10% ramp rule, heat and recovery
    checks. Data: yours, with a weekly encrypted backup.
11. Closing CTA: centered, huge headline "Train like you mean both." Blue pill button.
    Fine-print footer in small gray type.

# COPY RULES
- Confident, short, a little witty. Never more than two sentences per block.
- Numbers as heroes where possible (101 days, +8%, 225, 21-day comeback, 3 taps).
- No exclamation points. No jargon without a plain-English follow-up
  (e.g. "Z2: easy enough to talk").

# DELIVERABLES
- Desktop artboard (1440w) and mobile artboard (390w) of the full page.
- Bonus artboards: a 1200x630 social share card and a 1080x1080 square post using the
  hero render and headline.
- Annotate motion/scroll behavior with small, unobtrusive notes beside sections.

# ATTACHED REFERENCES
phone-today.png, phone-plan.png, phone-trends-full.png, phone-reports.png,
phone-pat-gpt.png, desktop-today.png, desktop-plan.png, desktop-trends.png, icon.svg.
Treat them as the source of truth for UI details. In renders, hide the "server clock"
label and show the bench chart's status as on track.
