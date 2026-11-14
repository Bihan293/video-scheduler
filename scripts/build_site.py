#!/usr/bin/env python3
"""Build the static compliance site for GitHub Pages.

Copies ``site/`` to ``site-dist/`` and replaces deployment placeholders with
repository variables (or environment variables when run locally):

  APP_NAME       — product name, default "Video Scheduler"
  APP_URL        — public URL of the web app
  CONTACT_EMAIL  — support email shown in the policies
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site"
OUT = ROOT / "site-dist"


def main() -> None:
    app_name = os.getenv("APP_NAME", "Video Scheduler")
    app_url = os.getenv("APP_URL", "https://example.com").rstrip("/")
    contact = os.getenv("CONTACT_EMAIL", "support@example.com")
    updated = time.strftime("%Y-%m-%d", time.gmtime())
    year = str(time.gmtime().tm_year)

    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(SRC, OUT)

    replacements = {
        "__APP_NAME__": app_name,
        "__APP_URL__": app_url,
        "__CONTACT_EMAIL__": contact,
        "__YEAR__": year,
        "__UPDATED__": updated,
    }
    for path in OUT.rglob("*"):
        if path.suffix not in {".html", ".css", ".js", ".txt", ".xml"}:
            continue
        text = path.read_text(encoding="utf-8")
        for key, value in replacements.items():
            text = text.replace(key, value)
        path.write_text(text, encoding="utf-8")

    print(f"Built {OUT} for {app_url} ({contact})")


if __name__ == "__main__":
    main()
