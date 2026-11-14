#!/usr/bin/env python3
"""Record a demo video and screenshots of the web flow with Playwright.

Usage:
    python3 scripts/record_demo.py --url http://127.0.0.1:8000

The video is written to demo/video/video-scheduler-demo.mp4 and key frames to
demo/frames/. Run it against the real deployment (with real TikTok keys) to
produce the demo required for the Content Posting API review.
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "demo"
VIDEO_DIR = OUT_DIR / "video"
FRAMES_DIR = OUT_DIR / "frames"
RAW_DIR = OUT_DIR / "raw"
SAMPLE = OUT_DIR / "sample.mp4"

CAPTION_CSS = """
#__cap {
  position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%);
  z-index: 2147483646; background: rgba(8, 8, 14, .9); color: #fff;
  border: 1px solid rgba(255,255,255,.18); padding: 9px 17px;
  border-radius: 100px; font: 600 14px/1.4 -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
  box-shadow: 0 10px 40px rgba(0,0,0,.45); backdrop-filter: blur(8px);
  max-width: 78%; text-align: center; white-space: nowrap;
}
#__cursor {
  position: fixed; left: 0; top: 0; width: 11px; height: 11px; border-radius: 50%;
  background: rgba(255,255,255,.5); border: 1.5px solid rgba(255,255,255,.95);
  box-shadow: 0 0 0 3px rgba(37,244,238,.2), 0 2px 8px rgba(0,0,0,.5);
  z-index: 2147483647; pointer-events: none;
  transform: translate(-50%, -50%); opacity: 0;
}
#__demo-badge {
  position: fixed; left: 16px; top: 14px; z-index: 2147483646;
  background: rgba(255,200,87,.14); border: 1px solid rgba(255,200,87,.4);
  color: #ffd98a; font: 600 11px/1 -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
  padding: 6px 9px; border-radius: 7px; letter-spacing: .04em; text-transform: uppercase;
}
@media (max-width: 760px) { #__cap { white-space: normal; } }
"""


def find_chromium() -> str | None:
    pattern = "/root/.cache/ms-playwright/chromium-*/chrome-linux*/chrome"
    candidates = [path for path in glob.glob(pattern) if os.access(path, os.X_OK)]
    # Older builds are tried first: a partially downloaded newer build can
    # launch and then crash while recording. Override with PLAYWRIGHT_CHROMIUM.
    candidates.sort(key=lambda path: path)
    return candidates[0] if candidates else None


def install_overlay(page: Page) -> None:
    page.add_style_tag(content=CAPTION_CSS)
    page.evaluate(
        """() => {
            if (document.getElementById('__cursor')) return;
            const cursor = document.createElement('div');
            cursor.id = '__cursor';
            document.body.appendChild(cursor);
            document.addEventListener('mousemove', (event) => {
                cursor.style.left = event.clientX + 'px';
                cursor.style.top = event.clientY + 'px';
                cursor.style.opacity = '1';
            }, true);
        }"""
    )


def caption(page: Page, text: str) -> None:
    page.evaluate(
        """(text) => {
            let el = document.getElementById('__cap');
            if (!el) {
                el = document.createElement('div');
                el.id = '__cap';
                document.body.appendChild(el);
            }
            el.textContent = text;
        }""",
        text,
    )


def demo_badge(page: Page) -> None:
    page.evaluate(
        """() => {
            if (document.getElementById('__demo-badge')) return;
            const badge = document.createElement('div');
            badge.id = '__demo-badge';
            badge.textContent = 'demo mode';
            document.body.appendChild(badge);
        }"""
    )


def smooth_click(page: Page, selector: str) -> None:
    locator = page.locator(selector).first
    locator.wait_for(state="visible", timeout=15000)
    box = locator.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=18)
        page.wait_for_timeout(250)
    locator.click()


def shot(page: Page, name: str) -> None:
    """Save a clean still without the video caption overlay."""
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    page.evaluate(
        """() => {
            for (const id of ['__cap', '__cursor']) {
                const el = document.getElementById(id);
                if (el) el.style.visibility = 'hidden';
            }
        }"""
    )
    page.screenshot(path=str(FRAMES_DIR / name), full_page=False)
    page.evaluate(
        """() => {
            for (const id of ['__cap', '__cursor']) {
                const el = document.getElementById(id);
                if (el) el.style.visibility = 'visible';
            }
        }"""
    )


def record(url: str) -> None:
    if not SAMPLE.exists():
        raise SystemExit("demo/sample.mp4 not found: run scripts/make_sample_video.py")

    for directory in (VIDEO_DIR, FRAMES_DIR, RAW_DIR):
        if directory.exists():
            shutil.rmtree(directory)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    exe = os.getenv("PLAYWRIGHT_CHROMIUM") or find_chromium()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=exe, args=["--no-sandbox"]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(RAW_DIR),
            record_video_size={"width": 1440, "height": 900},
            locale="ru-RU",
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle")
        install_overlay(page)
        demo_badge(page)
        caption(page, "1 · Подключаем TikTok через официальный OAuth")
        page.wait_for_timeout(2200)
        shot(page, "01-landing.png")

        smooth_click(page, "a.btn.primary")
        page.wait_for_load_state("networkidle")
        install_overlay(page)
        demo_badge(page)
        caption(page, "2 · Подтверждаем доступ к аккаунту")
        page.wait_for_timeout(2200)
        shot(page, "02-consent.png")

        smooth_click(page, "a.btn.primary")
        page.wait_for_load_state("networkidle")
        install_overlay(page)
        demo_badge(page)
        caption(page, "3 · Кабинет: аккаунт подключён")
        page.wait_for_timeout(1800)
        shot(page, "03-dashboard.png")

        page.set_input_files("#file", str(SAMPLE))
        page.wait_for_timeout(900)
        page.fill(
            "#title",
            "Утренний влог · публикация из Video Scheduler #demo",
        )
        caption(page, "4 · Выбираем видео, описание и режим")
        page.locator("#submit").scroll_into_view_if_needed()
        page.wait_for_timeout(1600)
        shot(page, "04-upload.png")

        smooth_click(page, "#submit")
        caption(page, "5 · Загружаем видео в TikTok")
        page.wait_for_timeout(900)
        page.locator("#progress").scroll_into_view_if_needed()
        page.wait_for_timeout(700)
        shot(page, "05-processing.png")

        try:
            page.wait_for_function(
                """() => {
                    const el = document.querySelector('.post .status');
                    return el && /Отправлено|Опубликовано|Ошибка/.test(el.textContent);
                }""",
                timeout=45000,
            )
        except Exception:
            pass
        page.wait_for_timeout(1200)
        caption(page, "6 · Готово: видео в черновиках TikTok")
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1800)
        shot(page, "06-done.png")

        page.wait_for_timeout(800)
        context.close()
        browser.close()

    raw_videos = sorted(RAW_DIR.glob("*.webm"), key=os.path.getmtime)
    if not raw_videos:
        raise SystemExit("Playwright did not produce a video")
    raw = raw_videos[-1]
    target = VIDEO_DIR / "video-scheduler-demo.mp4"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(raw),
            "-vf",
            "scale=1440:-2,fps=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "21",
            "-movflags",
            "+faststart",
            "-an",
            str(target),
        ],
        check=True,
    )
    shutil.rmtree(RAW_DIR)
    print(f"video: {target} ({target.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"frames: {FRAMES_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    record(args.url.rstrip("/"))


if __name__ == "__main__":
    sys.exit(main())
