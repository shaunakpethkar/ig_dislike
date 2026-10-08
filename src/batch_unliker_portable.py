"""Portable V4 launcher with per-user Firefox/profile discovery.

This keeps the V4 workflow but avoids machine-specific username and Firefox
paths. Each user gets a separate local profile and must sign in manually on
their first run.
"""

import logging
import os
import shutil
from pathlib import Path

from src import batch_unliker as production
from src import batch_unliker_v2 as v2
from src import batch_unliker_v4 as v4
from src import browser

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTABLE_PROFILE = PROJECT_ROOT / "ig_selenium_profile"
FIREFOX_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES", "")) / "Mozilla Firefox" / "firefox.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Mozilla Firefox" / "firefox.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Mozilla Firefox" / "firefox.exe",
)


def _find_firefox_binary() -> str:
    for candidate in FIREFOX_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    discovered = shutil.which("firefox") or shutil.which("firefox.exe")
    if discovered:
        return discovered
    raise FileNotFoundError(
        "Firefox was not found. Install Firefox or add firefox.exe to PATH."
    )


def _portable_driver():
    firefox_binary = _find_firefox_binary()
    PORTABLE_PROFILE.mkdir(parents=True, exist_ok=True)
    logger.info("Using portable Firefox profile: %s", PORTABLE_PROFILE)
    logger.info("Using Firefox binary: %s", firefox_binary)
    return browser.create_driver(
        profile_path=str(PORTABLE_PROFILE),
        firefox_binary=firefox_binary,
    )


def run_batch_unliker_portable(batch_size: int = 80, max_batches: int = 1) -> dict:
    """Run V4 with automatically discovered local Firefox configuration."""
    original_v2_factory = v2.create_driver
    original_production_factory = production.create_driver
    v2.create_driver = _portable_driver
    production.create_driver = _portable_driver
    try:
        return v4.run_batch_unliker_v4(
            batch_size=batch_size,
            max_batches=max_batches,
        )
    finally:
        v2.create_driver = original_v2_factory
        production.create_driver = original_production_factory


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Portable V4 Instagram batch unliker"
    )
    parser.add_argument("--batch-size", type=int, default=80)
    parser.add_argument("--max-batches", type=int, default=1)
    args = parser.parse_args()
    run_batch_unliker_portable(
        batch_size=args.batch_size,
        max_batches=args.max_batches,
    )
