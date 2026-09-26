"""Project text rules (docs/ENGINEERING.md): no em dashes (U+2014) anywhere in ParkIQ text.

Checks every git-tracked text file, and, when the portfolio site repo is present (``NDEOGO_DIR``
or ``../ndeogo`` next to this repo), the ParkIQ cards in its ``index.html`` (no em dash, no
"coming soon") and the ParkIQ report PDFs in ``documentation/``. A commit message can be checked
with ``--msg FILE``. Exit status 1 lists every violation.

    python scripts/check_text.py [--msg COMMIT_MSG_FILE]
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

EM = chr(0x2014)  # em dash
BINARY = {".png", ".jpg", ".jpeg", ".pdf", ".gpkg", ".zip", ".xlsx", ".parquet", ".tif", ".ico"}
REPO = Path(__file__).resolve().parents[1]


def tracked_violations(repo: Path = REPO) -> list[str]:
    """Tracked text files containing an em dash (file:line)."""
    files = subprocess.run(
        ["git", "ls-files"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    out = []
    for f in files:
        p = repo / f
        if p.suffix.lower() in BINARY or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if EM in line:
                out.append(f"{f}:{i}: em dash")
    return out


def parkiq_cards(html: str) -> list[str]:
    """The ParkIQ <article> cards of the site's index.html."""
    arts = re.findall(r"<article\b.*?</article>", html, flags=re.S)
    return [a for a in arts if "parkiq" in a.lower()]


def site_violations(site: Path) -> list[str]:
    """ParkIQ cards: no em dash, no 'coming soon'; ParkIQ report PDFs: no em dash."""
    out = []
    idx = site / "index.html"
    if idx.exists():
        for card in parkiq_cards(idx.read_text(encoding="utf-8")):
            title = re.search(r'card-title">(?:<button[^>]*>)?([^<]+)', card)
            name = title.group(1).strip() if title else "?"
            if EM in card:
                out.append(f"ndeogo card '{name}': em dash")
            if "coming soon" in card.lower():
                out.append(f"ndeogo card '{name}': 'coming soon' item")
    for pdf in sorted((site / "documentation").glob("parkiq-*.pdf")):
        import pypdf

        text = "".join(pg.extract_text() or "" for pg in pypdf.PdfReader(pdf).pages)
        if EM in text:
            out.append(f"ndeogo {pdf.name}: em dash")
    return out


def main(argv: list[str]) -> int:
    if "--msg" in argv:
        msg = Path(argv[argv.index("--msg") + 1]).read_text(encoding="utf-8")
        problems = ["commit message: em dash"] if EM in msg else []
    else:
        problems = tracked_violations()
        site = Path(os.environ.get("NDEOGO_DIR", REPO.parent / "ndeogo"))
        if site.exists():
            problems += site_violations(site)
        else:
            print(f"(site repo not found at {site}; ParkIQ cards not checked)")
    for p in problems:
        print(p)
    print(f"text rules: {len(problems)} violation(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
