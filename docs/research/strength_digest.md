# Strength digest (from "Strength plan while cutting", Oct 2026)

Plan of record for lifting. Evidence vs. inference is marked; the full report is kept outside the repo.

## Bottom line
- Push Tue / Pull Wed / Legs Thu, crossover sets (bench twice a week: heavy Tue, lighter 3 x 8 Thu). Rest 2:30 after heavy compounds, 1:30 after superset rounds.
- Re-entry after mono (inference): wk1 ~75% of last working loads at RPE 6-7, wk2 ~85%, wk3 ~92.5%, wk4 ~97.5%, then the weekly rule engine. Legs ramp slowest, no lunges or slow eccentrics for the first 3 weeks.
- Bench 225 before Lake Placid is unlikely (<1 in 5, judgement). Checkpoints for the smoothed e1RM: >=170 by Nov 24, >=185 by Dec 15, >=195 (stretch 200) by Mar 1, hold >=190 Apr-Jul. Go/no-go Apr 1 2027 only if trend >=215. Then a bench block after the race: ~205 Nov 2027, ~215 Feb-Mar 2028, 225 about mid-2028. 225 x 5 needs a 1RM of ~253-262.
- Weekly hard sets: re-entry 30 -> 50; Base 45-55; Build 1 28-35; Build 2 20-28; Peak 10-16; race weeks <=6. Keep one heavy top set (3-6 reps, RPE 8, ~80-87% e1RM) per main lift in every phase: intensity, not volume, keeps strength (Spiering 2021; Bickel 2011; Ronnestad 2010).
- A calorie deficit costs muscle growth more than strength (Murphy & Koehler 2022). Concurrent endurance training barely dents max strength (Schumann 2022).

## Placement (inference from Doma 2017, Devantier-Thomas 2024, Schumann 2022, Murlasits 2018)
- Same evening: when lifting is the main session, lift first, then easy aerobic. When the endurance session is the key one, do it first and lift upper body only. Never heavy legs after a hard run.
- Heavy legs >=48 h before the long ride (Thu -> Sat is fine once used to it), >=72 h before a key brick or race-pace session. Brick weeks and Build 2 / Peak: legs move to Tuesday at a maintenance dose.
- Keep Wednesday RDLs to 2 sets at RPE <=8. Recovery weeks: cut lifting sets 30-50%, keep loads.
- Last heavy lower body: Thu Mar 4 before the 70.3 (upper primer only Tue Mar 9); Tue Jul 13 before Lake Placid (Jul 15 at the latest), optional upper primer Tue Jul 20.

## Weekly weight rules (the app computes these; see app/strength.py)
- e1RM per set: reps-to-failure = reps + (10 - RPE) + bias; mean of Epley and Brzycki; only sets <=10 reps at RPE >=7. Smoothed 0.3 / 0.7.
- Next top set from last week's RPE gap (logged - target): <=-1.5 +4%; -1..-0.5 +2%; 0 +1-2%; +0.5 same; >=+1 -2% per point; missed reps -5 to -10%. Cap +5 lb a week while cutting. Back-offs at 90%.
- Accessories: double progression (top of the range on every set at RPE <=8 -> +5 lb, back to the bottom).
- Deload when two flags (stalled trend, missed reps twice, RPE drift, poor sleep/HRV, recovery week): half the sets, top set RPE <=7.
- Lifters under-rate reps left by ~1 rep on average (Halperin 2022): log RPE on every working set; a set to failure every 4-6 weeks calibrates it.

## Open uncertainties
No study tests mono re-entry percentages, strength tapers before long-course races, or any RPE-to-load step size. 1RM uncertain by ~10 lb (155 x 8 implies ~192 but the best single is 175).
