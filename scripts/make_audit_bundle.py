"""Build one Markdown file an outside reviewer (human or AI) can audit.

    python -m scripts.make_audit_bundle            # -> audit/training-system-audit.md

Contents: docs/AUDIT_BRIEF.md, then every tracked text file in the repo.
Only committed files are included, so no secrets can leak in (none are
committed), but the seeds do contain Patrick's health notes and goals.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "audit" / "training-system-audit.md"
SKIP_SUFFIXES = {".png", ".jpg", ".ico"}
LANG = {".py": "python", ".sql": "sql", ".js": "javascript", ".html": "html", ".css": "css",
        ".json": "json", ".md": "markdown", ".webmanifest": "json", ".txt": "text", ".ini": "ini"}


def main() -> None:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                           check=True).stdout.split()
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True).stdout.strip()
    parts = [(ROOT / "docs" / "AUDIT_BRIEF.md").read_text(),
             f"\n\n---\n\n# Source (commit {commit}, bundled "
             f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)\n\n"
             "## File index\n\n" + "\n".join(f"- `{f}`" for f in files) + "\n"]
    for f in files:
        p = ROOT / f
        if p.suffix in SKIP_SUFFIXES or f == "docs/AUDIT_BRIEF.md":
            continue
        parts.append(f"\n\n## `{f}`\n\n````{LANG.get(p.suffix, '')}\n{p.read_text()}\n````\n")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("".join(parts))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB, {len(files)} files)")


if __name__ == "__main__":
    main()
