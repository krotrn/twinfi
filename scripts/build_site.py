#!/usr/bin/env python3
"""Stage the documentation website in site-src/ for `zensical build`.

The README becomes the home page and docs/*.md the other pages. Each page
gets a search-friendly title and description as front matter here, so the
files on GitHub stay plain markdown.

    scripts/build_site.py && zensical build
"""

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site-src"
REPO_BLOB = "https://github.com/krotrn/twinfi/blob/main/"

# path in site-src -> (title, description)
PAGES = {
    "index.md": (
        "twinfi: Linux Wi-Fi hotspot that keeps your Wi-Fi connected",
        "Run a Wi-Fi hotspot on Linux while staying connected to Wi-Fi (AP+STA). "
        "CLI and GTK 4 app for NetworkManager, hostapd and dnsmasq on Ubuntu, Fedora and Arch.",
    ),
    "how-it-works.md": (
        "How AP+STA works: a hotspot and a Wi-Fi connection on one card",
        "Why sharing Wi-Fi from a Linux laptop is harder than it looks, which problems "
        "you may hit, and how twinfi handles each one. No networking background needed.",
    ),
    "5ghz-wifi.md": (
        "Linux hotspot won't start on 5 GHz: DFS and no-IR channels explained",
        "Why a Linux hotspot refuses to start while your Wi-Fi is on 5 GHz (radar/DFS "
        "and no-IR channels, Intel LAR) and every way to fix it.",
    ),
    "wifi-direct.md": (
        "Wi-Fi Direct hotspot on Linux with wpa_supplicant",
        "How twinfi runs the hotspot as a Wi-Fi Direct group on its own channel when "
        "your Wi-Fi's channel can't host one, and which cards and distributions support it.",
    ),
    "json-output.md": (
        "twinfi JSON output for scripts",
        "Keys and exit codes of twinfi status, detect, config, clients and start --json.",
    ),
    "ARCHITECTURE.md": (
        "twinfi architecture",
        "How twinfi is put together: capability detection, hotspot methods, rollback, "
        "the watcher, firewall backends and the GTK app.",
    ),
}


def front_matter(title: str, description: str) -> str:
    return f'---\ntitle: "{title}"\ndescription: "{description}"\n---\n\n'


def home_page() -> str:
    """The README with links back into docs/ made relative to the site."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    text = re.sub(rf"{re.escape(REPO_BLOB)}docs/([\w./-]+\.md)", r"\1", text)
    return text


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.copytree(ROOT / "docs", OUT)
    (OUT / "index.md").write_text(home_page(), encoding="utf-8")
    shutil.copy(ROOT / "llms.txt", OUT / "llms.txt")
    (OUT / "assets").mkdir()
    shutil.copy(ROOT / "twinfi_gui/data/icons/hicolor/scalable/apps/com.github.twinfi.Gtk.svg", OUT / "assets/icon.svg")
    for name, (title, description) in PAGES.items():
        page = OUT / name
        page.write_text(front_matter(title, description) + page.read_text(encoding="utf-8"), encoding="utf-8")
    missing = sorted(p.name for p in OUT.glob("*.md") if p.name not in PAGES)
    if missing:
        print(f"No title/description in PAGES for: {', '.join(missing)}")
        return 1
    print(f"Staged {len(PAGES)} pages in {OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
