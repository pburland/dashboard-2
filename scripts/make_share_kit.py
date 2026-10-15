"""Build a shareable copy of the app: all the code, none of Patrick's data or keys.

    python -m scripts.make_share_kit [out_dir]     # -> <out_dir>/training-console-kit.zip

What changes in the copy:
  * db/seed/ holds only a fill-in template (share/template/001_athlete.sql) and
    the generic volume targets. Patrick's seed history becomes example data for
    the tests (tests/fixtures/example_seeds/) with health details and body
    metrics replaced by neutral values.
  * Personal docs (decision log, audits, build report, brand files) are left out.
  * Names, home location, illness wording and his server address are scrubbed.
  * START_HERE.md (architecture, accounts, keys, the prompt for your Claude) is
    added at the top level.
Only committed files are read, so no secret can be included (none are
committed); the build also fails if anything that looks like one, or any
scrubbed word, is still present.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_PREFIXES = ("db/seed/", "brand/", "share/", "audit/", "preview/")
EXCLUDE_FILES = {"docs/DECISIONS.md", "docs/AUDIT_BRIEF.md", "docs/AUDIT_PROMPT.md", "docs/BUILD_REPORT_2-5.md",
                 "scripts/make_audit_bundle.py", "scripts/make_share_kit.py"}
TEXT = {".py", ".sql", ".md", ".js", ".html", ".css", ".json", ".txt", ".ini", ".yml", ".webmanifest", ".example",
        ".toml", ""}

# (pattern, replacement, flags). Order matters: specific before general.
SCRUB = [
    (r"\(for mono: spleen back to normal, cleared for running and lifting\)", "(cleared for running and lifting)", 0),
    (r"\(spleen OK for running and lifting\)", "(cleared for running and lifting)", 0),
    (r"pain under the left ribs", "new pain", 0),
    (r"Mono \(infectious mononucleosis\)", "Viral illness", 0),
    (r"infectious mononucleosis", "viral illness", 0),
    (r"Spleen risk: no running", "No running", 0),
    (r"is the spleen back to normal size", "is recovery complete", 0),
    (r"Mono enlarges the spleen, which can rupture under impact\s*--\s*or straining, so", "So", 0),
    (r"Mono can enlarge the spleen[^.]*\.\s*", "", 0),
    (r"[^.'\n]*[Ss]pleen[^.'\n]*\.\s?", "", 0),
    (r"\bmono\b", "illness", 0),
    (r"\bMono\b", "Illness", 0),
    # Body metrics and metabolism (example values instead).
    (r"update profile set rmr_kcal = 1958.*?where id = 1;",
     "update profile set rmr_kcal = 1800, rmr_measured_on = '2026-09-23', rmr_note = 'Example value.' where id = 1;",
     re.S),
    (r"\('2026-09-18', 160\.0, 19\.4, 123\.9, 31\.4, 1\.191, 'dexa',\s*'\{.*?\}'\)",
     "('2026-09-18', 165.0, 18.0, 130.0, 29.7, 1.200, 'dexa', '{}')", re.S),
    (r"DEXA Sep 18: 160 lb, 19\.4% fat \(31\.4 lb fat, 124 lb lean\)\.", "Example DEXA numbers.", 0),
    (r't\["fuel"\]\["kcal"\] == 2550 and t\["body"\]\["bf_pct"\] == 19\.4',
     't["fuel"]["kcal"] == 2340 and t["body"]["bf_pct"] == 18.0', 0),
    # Race history, names, places, ids.
    (r"'\{\"race\":\"Eagleman.*?\}'", "null", re.S),
    (r"Eagleman( 70\.3)?", "the last race", 0),
    (r"values \('Patrick',", "values ('Alex',", 0),
    (r"Patrick's", "the athlete's", 0),
    (r"Patrick", "the athlete", 0),
    (r"Pat-GPT", "Coach", 0),
    (r"Arlington, VA", "their home city", 0),
    (r"Arlington", "home", 0),
    (r"38\.8816", "40.7128", 0),
    (r"-77\.0910", "-74.0060", 0),
    (r"24474801626", "10000000001", 0),
    (r"dashboard-2-production-6f5f", "your-app", 0),
]
FORBIDDEN = [r"(?i)patrick", r"(?i)\bmono\b", r"(?i)mononucleosis", r"(?i)spleen", r"(?i)arlington", r"acc\.eco",
             r"6f5f", r"rmr_kcal = 1958", r"19\.4% fat",
             # anything shaped like a key or token value
             r"sk-ant-[A-Za-z0-9_-]{8,}", r"(?i)(api_key|secret|token|password)\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"]

# The tests read example seeds from tests/fixtures/example_seeds instead of db/seed.
TEST_PATCHES = {
    "tests/test_ingest.py": [(
        '''    files = [f for f in migrate.files(seed=True)
             if last_seed is None or f.parent.name != "seed" or f.name <= last_seed]''',
        '''    files = [f for f in example_files()
             if last_seed is None or f.parent.name != "example_seeds" or f.name <= last_seed]''')],
    "tests/test_backup.py": [
        ('''    migrate.run(DB, seed=True)
    with psycopg.connect(DB) as c:
        c.execute("insert into integrations''',
         '''    from tests.test_ingest import example_files
    with psycopg.connect(DB, autocommit=True) as c:
        migrate.apply(c, example_files())
    with psycopg.connect(DB) as c:
        c.execute("insert into integrations'''),
        ('''    assert migrate.run(DB, seed=True) == []''', '''    assert migrate.run(DB, seed=False) == []'''),
    ],
}
EXAMPLE_FILES_FN = '''

def example_files():
    """Migrations plus the example athlete's seed history (tests only)."""
    from pathlib import Path
    from scripts import migrate
    seeds = sorted((Path(__file__).parent / "fixtures" / "example_seeds").glob("*.sql"))
    return migrate.files(seed=False) + seeds
'''


def scrub(text: str) -> str:
    for pat, rep, flags in SCRUB:
        text = re.sub(pat, rep, text, flags=flags)
    return text


def main(out_dir: str) -> Path:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    stage = Path(out_dir) / "training-console"
    if stage.exists():
        shutil.rmtree(stage)
    for f in files:
        if f.startswith(EXCLUDE_PREFIXES) or f in EXCLUDE_FILES:
            continue
        src, dst = ROOT / f, stage / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in TEXT and src.name != "uv.lock":
            dst.write_text(scrub(src.read_text()))
        else:
            shutil.copy2(src, dst)
    # Seeds: a template to fill in, plus the generic volume targets.
    seed = stage / "db" / "seed"
    seed.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "share" / "template" / "001_athlete.sql", seed / "001_athlete.sql")
    (seed / "002_volume_targets.sql").write_text(scrub((ROOT / "db" / "seed" / "008_volume_targets.sql").read_text()))
    # Patrick's seed history, scrubbed, as test fixtures.
    fx = stage / "tests" / "fixtures" / "example_seeds"
    fx.mkdir(parents=True, exist_ok=True)
    for f in sorted((ROOT / "db" / "seed").glob("*.sql")):
        (fx / f.name.replace("mono", "illness").replace("patrick", "athlete")).write_text(scrub(f.read_text()))
    for rel, patches in TEST_PATCHES.items():
        p = stage / rel
        t = p.read_text()
        for old, new in patches:
            if old not in t:
                raise SystemExit(f"test patch no longer applies to {rel}: {old[:60]!r}")
            t = t.replace(old, new)
        if rel == "tests/test_ingest.py":
            t += EXAMPLE_FILES_FN
        p.write_text(t)
    shutil.copy2(ROOT / "share" / "START_HERE.md", stage / "START_HERE.md")
    shutil.copy2(ROOT / "share" / "template" / "SETUP.md", stage / "docs" / "SETUP.md")   # generic, not Patrick's
    readme = stage / "README.md"
    readme.write_text("# Training Console\n\nStart with **START_HERE.md**.\n\n" + readme.read_text().split("\n", 2)[-1])
    # Nothing personal or secret may remain.
    problems = []
    for p in stage.rglob("*"):
        if p.is_file() and p.suffix in TEXT:
            text = p.read_text(errors="ignore")
            for pat in FORBIDDEN:
                for m in re.finditer(pat, text):
                    line = text[:m.start()].count("\n") + 1
                    problems.append(f"{p.relative_to(stage)}:{line}: {m.group(0)!r}")
    allowed = {"START_HERE.md"}         # it explains that the original was Patrick's
    problems = [x for x in problems if x.split(":")[0] not in allowed]
    if problems:
        raise SystemExit("personal or secret text left in the kit:\n" + "\n".join(problems[:40]))
    out = Path(out_dir) / "training-console-kit.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                z.write(p, p.relative_to(stage.parent))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "share" / "dist"))
