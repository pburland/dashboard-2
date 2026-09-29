# Prompt for an outside AI: audit, grill, and design the next level

Paste everything below the line into the other AI, and attach
`audit/training-system-audit.md` (build it with `python -m scripts.make_audit_bundle`).

---

You're joining a project as a senior reviewer with three hats: **software
engineer**, **endurance + strength coach who knows Joe Friel's work deeply**,
and **product designer for a phone-first training app**. Attached is
`training-system-audit.md`: a brief (read it first) followed by the complete
source of a personal training system for one athlete, me (Patrick).

Your job has four phases. **Do them in order and stop where I say stop.**

## Phase 1: grill me first (stop and wait for my answers)

Before judging or designing anything, interview me. Read the brief and the
code, then ask the questions whose answers would change your recommendations
the most.

- Ask **one question at a time**, most important first. For each, say why it
  matters, give your **recommended answer** or default, and the options.
- Stop after each question and wait for my reply. Don't ask about anything
  the attached files already answer; quote the file instead.
- Keep going until you'd make the same recommendations no matter how the
  remaining open questions came out. Then tell me you're done and summarize
  what you learned in a short list.

Areas you'll probably need to cover (skip what the files already settle):
- **Real week:** available hours per day, fixed commitments, pool and gym
  access, indoor trainer, when I actually train (AM/PM), travel.
- **Equipment and data:** HR strap vs wrist, the power meter arriving (model,
  when), running power, swim tracking, what I'll realistically log (RPE,
  notes, how I felt).
- **Body:** injury history, the Eagleman bike-fit pain, how I respond to
  volume, how I recovered from the recent virus.
- **Goals:** how hard the 6:23 / 6:00 and MCM goals are, how I'd trade them
  off, whether bench or body comp can ever outrank the race.
- **How I want to be coached:** prescriptive or advisory, how bluntly, how
  many notifications, what I want at 5:30 AM on my phone in 5 seconds.
- **Felipe's role:** his advice pushed the 16-mile compromise. How should
  outside coaching input enter the system?
- **Testing:** willingness to do a 30-minute run threshold test, an FTP test
  when the power meter arrives, a swim CSS test, and when.

## Phase 2: audit (only after Phase 1)

Findings ranked by severity: **critical / high / medium / low**. For each:
the file and line, what goes wrong, a concrete scenario with numbers or dates,
and a fix. Cover:
1. **Training safety and logic:** thresholds, the return-to-training rules,
   the 16-mile compromise (6 → 13.5 → 16 → 10 → race), the MCM gate, the
   health gate.
2. **Correctness:** timezones and dates, plan/actual matching, idempotent
   re-syncs, the long-run go/no-go conditions.
3. **Security and privacy:** the single admin token and cookie, provider
   tokens in the database, what leaks if something is exposed.
4. **Reliability:** provider outages, the Garmin session expiring, restarts
   mid-sync, the scheduler, database pooling.
5. **Claims vs reality:** anything the docs or comments say that the code
   doesn't do.

The brief lists weaknesses we already know about. Rank them alongside your
own findings; don't just repeat them.

## Phase 3: take it to the next level (ideas, then a ranked roadmap)

Think broadly first, then cut hard. Three tracks:

**A. Functionality**
- **A real plan generator.** Today plans are hand-written SQL. Design one
  that builds each week from the phase, the athlete's history and the rules,
  passes the existing validator, and rebases automatically when a health hold
  ends or a session is missed.
- **Adapting to what actually happened:** missed sessions, extra sessions,
  bad readiness, heat, travel.
- **The coaching chat ("Ask Patrick"),** grounded in the data. The model
  explains but never overrides the rules. What context goes in, what
  memory it keeps, and how it logs notes (injury, illness, travel) that feed
  back into the gate.
- **Push notifications worth getting** (and which to never send).
- **Race-specific tools:** 70.3 pacing and fueling plans, taper builder,
  race-week checklist, post-race analysis.
- **Strength progression:** the bench-to-225 honesty, concurrent-training
  interference, and deloads.

**B. UI and daily use** (phone first, dark UI, glanceable)
- What the Today screen should show at 5:30 AM, in order of importance, and
  what to remove.
- **Post-workout:** a 10-second check-in (RPE, how it felt, pain yes/no) that
  feeds the system.
- **Trends that matter:** fitness, fatigue and form (CTL/ATL/TSB), aerobic
  decoupling over time, pace at a fixed HR, bench estimated 1RM, weight.
  Which charts earn their space?
- Give **concrete screen-by-screen proposals** (layout, components, copy),
  not adjectives. ASCII wireframes are welcome.

**C. The training knowledge base: building on Joe Friel**

The system encodes Friel's periods, abilities (AE, MF, SS, ME, ANE, SP),
strength phases (AA→MT→MS→SM) and decoupling in
`app/periodization/friel.py`. Propose how to turn this into a real,
maintainable knowledge base:
- **Coverage gaps in Friel as implemented:**
  - the Annual Training Plan (ATP) with weekly hour/TSS targets, and 3:1 vs 2:1 mesocycles for this athlete;
  - Friel's zone systems for run pace, HR and power, and swim CSS;
  - field tests;
  - race-week structure;
  - the recovery and overtraining indicators from his books;
  - the ATP → weekly → daily cascade.
- **Complementary methods,** and how to combine them without contradiction:
  - Seiler's polarized / 80-20 intensity distribution;
  - Daniels VDOT for run paces;
  - Coggan's power levels and TSS once the power meter arrives;
  - Pfitzinger for the marathon build;
  - Be IronFit for the full-IRONMAN block;
  - heat acclimatization;
  - fueling (carbs per hour, gut training).

  For each: what it adds, where it conflicts with Friel, and which should win
  for this athlete.
- **Representation:** rules as versioned data with citations (book, edition,
  chapter), every rule with a test case, and the model allowed to explain a
  rule but never invent one. Propose a schema.
- **What to measure** to know the plan is working, and when to change course.

**Roadmap:** end with one ranked list of your top 10–15 changes across all
three tracks. For each: impact, effort (S/M/L), dependencies, and whether it
has to happen before Oct 25 (MCM) or can wait for the Puerto Rico build.

## Phase 4: stop and check with me

Don't write code. End by asking me which roadmap items to do first. Then
produce a short brief I can hand back to the engineer (Claude) who built the
system.

## Ground rules

- **Be direct.** If a goal is off track or my plan is wrong, say so plainly
  with the numbers. I respond better to that than to encouragement.
- **Respect decided constraints unless you argue against them explicitly:**
  - Garmin for activities, not Strava;
  - Hevy for lifting;
  - Oura for recovery;
  - Railway + Supabase + a Python backend;
  - code decides the plan and a model explains it;
  - one athlete.

  If you think one should change, make the case with evidence; don't just
  ignore it.
- **Separate what the evidence supports from your opinion.** When citing
  Friel or anyone else, name the source. Say when you're unsure.
- **Health comes first.** Anything that could hurt me outranks anything that
  could make me faster.
