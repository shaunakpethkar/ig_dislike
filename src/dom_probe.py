"""
dom_probe.py – Phase 1: READ-ONLY DOM Discovery.

This script inspects the Instagram Likes page DOM without modifying anything.

It will:
  1. Launch Firefox using the existing Selenium profile.
  2. Navigate to the Likes page.
  3. Detect login state (URL-based) and allow manual login if needed.
  4. Locate the likes container.
  5. Discover the internal scrollable element.
  6. Enumerate currently-rendered media cards and collect detailed attributes.
  7. Scroll the internal container to several positions (READ-ONLY) and
     re-enumerate cards at each position.
  8. Save a comprehensive diagnostic report (JSON + TXT + screenshot) into
     the diagnostics/ directory.

It does NOT:
  - Click "Select"
  - Select any items
  - Click "Unlike"
  - Modify Instagram in any way

Usage:
    python -m src.dom_probe
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure the project root is on sys.path when run as `python -m src.dom_probe`.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.browser import create_driver, save_screenshot
from src.instagram import (
    collect_card_diagnostics,
    find_scrollable_container,
    get_rendered_cards,
    get_scroll_metrics,
    is_login_required,
    navigate_to_likes,
    scroll_internal_container,
    wait_for_likes_container,
    wait_for_manual_login,
)
from src.selectors import LIKES_CONTAINER

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DIAGNOSTICS_DIR = PROJECT_ROOT / "diagnostics"
LOGS_DIR = PROJECT_ROOT / "logs"

# How many distinct scroll positions to probe (beyond the initial viewport).
NUM_SCROLL_PROBES = 5

# Pixels to scroll for each probe step.
SCROLL_STEP_PX = 1500

# Seconds to wait after each scroll for the virtualised DOM to settle.
SCROLL_SETTLE_SECONDS = 2.0

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(timestamp: str) -> None:
    """Configure logging to both console and a timestamped log file."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file = LOGS_DIR / f"dom_probe_{timestamp}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Console handler (INFO level).
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S"
    ))
    root_logger.addHandler(console)

    # File handler (DEBUG level).
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(name)-20s  %(levelname)-8s  %(message)s"
    ))
    root_logger.addHandler(file_handler)

    logging.info("Log file: %s", log_file)


# ---------------------------------------------------------------------------
# Probe logic
# ---------------------------------------------------------------------------

def probe_scroll_position(
    driver,
    position_label: str,
    report: dict,
) -> dict:
    """
    Collect diagnostics for the current scroll position.

    Returns a dict describing this scroll position's state.
    """
    logger = logging.getLogger("dom_probe")

    snapshot: dict = {
        "position_label": position_label,
        "timestamp": datetime.now().isoformat(),
        "scroll_metrics": None,
        "card_count": 0,
        "cards": [],
    }

    # 1. Read scroll metrics.
    metrics = get_scroll_metrics(driver)
    snapshot["scroll_metrics"] = metrics
    if metrics:
        logger.info(
            "[%s] scrollTop=%d  scrollHeight=%d  clientHeight=%d",
            position_label,
            metrics.get("scrollTop", -1),
            metrics.get("scrollHeight", -1),
            metrics.get("clientHeight", -1),
        )
    else:
        logger.warning("[%s] Could not read scroll metrics.", position_label)

    # 2. Enumerate rendered cards.
    cards = get_rendered_cards(driver)
    snapshot["card_count"] = len(cards)
    logger.info("[%s] Rendered cards: %d", position_label, len(cards))

    # 3. Collect diagnostics for each card.
    for i, card in enumerate(cards):
        card_info = collect_card_diagnostics(card)
        card_info["index_in_viewport"] = i
        snapshot["cards"].append(card_info)

        # Summarise for console output.
        aria = card_info.get("aria-label", "")
        tag = card_info.get("tag", "?")
        has_video = len(card_info.get("descendant_videos", [])) > 0
        has_svg = len(card_info.get("descendant_svgs", [])) > 0
        n_imgs = len(card_info.get("descendant_imgs", []))
        n_links = len(card_info.get("descendant_links", []))

        logger.debug(
            "  Card %2d: <%s> aria=%r  imgs=%d  videos=%s  svgs=%s  links=%d",
            i, tag, aria[:60] if aria else "", n_imgs, has_video, has_svg, n_links,
        )

    return snapshot


def run_probe() -> None:
    """Main probe entry point."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    setup_logging(timestamp)
    logger = logging.getLogger("dom_probe")

    logger.info("=" * 70)
    logger.info("DOM PROBE – Phase 1 – READ-ONLY Discovery")
    logger.info("=" * 70)

    # ---- Full diagnostic report ----
    report: dict = {
        "probe_timestamp": timestamp,
        "probe_version": "1.0.0",
        "phase": "dom_discovery",
        "read_only": True,
        "environment": {
            "python": sys.version,
        },
        "likes_container_found": False,
        "scrollable_container": None,
        "scroll_positions": [],
        "type_distribution_summary": {},
        "notes": [],
    }

    driver = None
    try:
        # ---- 1. Launch browser ----
        driver = create_driver()

        # ---- 2. Navigate to Likes page ----
        navigate_to_likes(driver)

        # ---- 3. Login detection ----
        if is_login_required(driver):
            logger.info("Login required. Please log in via the browser window.")
            if not wait_for_manual_login(driver, timeout=300):
                report["notes"].append("Login timed out – aborting probe.")
                logger.error("Login timed out. Aborting.")
                return
            # Re-navigate after login since IG may not land on Likes page.
            navigate_to_likes(driver)
            time.sleep(3)

        # ---- 4. Wait for Likes container ----
        container = wait_for_likes_container(driver, timeout=20)
        if container is None:
            report["likes_container_found"] = False
            report["notes"].append(
                f"Likes container '{LIKES_CONTAINER}' not found. "
                "The page may have a different structure or the session expired."
            )
            # Save what we can.
            save_diagnostics(report, driver, timestamp)
            return

        report["likes_container_found"] = True
        logger.info("Likes container found.")

        # Small stabilisation wait.
        time.sleep(2)

        # ---- 5. Discover scrollable container ----
        scroll_info = find_scrollable_container(driver)
        report["scrollable_container"] = {
            "method": scroll_info.get("method"),
            "candidates": scroll_info.get("candidates", []),
            "found": len(scroll_info.get("candidates", [])) > 0,
        }

        # ---- 6. Initial viewport probe ----
        logger.info("-" * 50)
        logger.info("Probing initial viewport (scrollTop=0)")
        logger.info("-" * 50)
        initial = probe_scroll_position(driver, "initial", report)
        report["scroll_positions"].append(initial)

        # ---- 7. Scroll probes ----
        for probe_idx in range(1, NUM_SCROLL_PROBES + 1):
            label = f"scroll_{probe_idx}"
            logger.info("-" * 50)
            logger.info("Scrolling down %dpx for probe '%s'", SCROLL_STEP_PX, label)
            logger.info("-" * 50)

            scroll_internal_container(driver, SCROLL_STEP_PX)
            time.sleep(SCROLL_SETTLE_SECONDS)

            snapshot = probe_scroll_position(driver, label, report)
            report["scroll_positions"].append(snapshot)

        # ---- 8. Scroll back to top ----
        logger.info("Scrolling back to top.")
        scroll_internal_container(driver, -999999)
        time.sleep(SCROLL_SETTLE_SECONDS)

        # ---- 9. Compute type distribution summary ----
        report["type_distribution_summary"] = compute_type_summary(report)

        # ---- 10. Save diagnostics ----
        save_diagnostics(report, driver, timestamp)

        logger.info("=" * 70)
        logger.info("DOM PROBE COMPLETE")
        logger.info("=" * 70)
        print_summary(report)

    except Exception:
        logger.exception("Unhandled exception during DOM probe.")
        if driver:
            try:
                save_screenshot(driver, str(DIAGNOSTICS_DIR), f"dom_probe_error_{timestamp}")
            except Exception:
                pass
        raise
    finally:
        if driver:
            logger.info("Closing browser.")
            driver.quit()


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def classify_card_label(aria_label: str | None) -> str:
    """
    Classify a card based on its aria-label prefix.

    Returns one of: "photo", "carousel", "video", "unknown".

    WARNING: This classification is preliminary. The probe exists to
    determine whether this is reliable. Do NOT treat "video" as confirmed
    Reel identification until the probe results are analysed.
    """
    if not aria_label:
        return "unknown"
    label = aria_label.strip()
    if label.startswith("Photo,"):
        return "photo"
    if label.startswith("Carousel with"):
        return "carousel"
    if label.startswith("Video,"):
        return "video"
    if label.startswith("Reel"):
        return "reel"
    return "unknown"


def compute_type_summary(report: dict) -> dict:
    """
    Aggregate card type counts across all scroll positions.
    """
    summary: dict = {
        "total_cards_seen": 0,
        "by_position": [],
        "unique_aria_prefixes": set(),
    }

    for pos in report.get("scroll_positions", []):
        pos_counts = {"photo": 0, "carousel": 0, "video": 0, "reel": 0, "unknown": 0}
        for card in pos.get("cards", []):
            aria = card.get("aria-label", "")
            ctype = classify_card_label(aria)
            pos_counts[ctype] = pos_counts.get(ctype, 0) + 1
            summary["total_cards_seen"] += 1

            # Track unique prefixes for diagnostic purposes.
            if aria:
                prefix = aria.split(",")[0] if "," in aria else aria[:30]
                summary["unique_aria_prefixes"].add(prefix)

        summary["by_position"].append({
            "label": pos.get("position_label"),
            "card_count": pos.get("card_count", 0),
            **pos_counts,
        })

    # Convert set to sorted list for JSON serialisation.
    summary["unique_aria_prefixes"] = sorted(summary["unique_aria_prefixes"])

    return summary


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def save_diagnostics(report: dict, driver, timestamp: str) -> None:
    """Save JSON report, human-readable TXT, and screenshot."""
    logger = logging.getLogger("dom_probe")
    os.makedirs(DIAGNOSTICS_DIR, exist_ok=True)

    # ---- JSON ----
    json_path = DIAGNOSTICS_DIR / f"dom_probe_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("JSON report saved: %s", json_path)

    # ---- TXT summary ----
    txt_path = DIAGNOSTICS_DIR / f"dom_probe_{timestamp}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"DOM Probe Report – {timestamp}\n")
        f.write("=" * 60 + "\n\n")

        f.write(f"Likes container found: {report.get('likes_container_found')}\n")

        sc = report.get("scrollable_container", {})
        f.write(f"Scrollable containers found: {sc.get('found')}\n")
        if sc.get("candidates"):
            for i, c in enumerate(sc["candidates"]):
                f.write(f"  Candidate {i}: <{c.get('tag')}> "
                        f"scrollHeight={c.get('scrollHeight')} "
                        f"clientHeight={c.get('clientHeight')} "
                        f"children={c.get('childCount')}\n")
        f.write("\n")

        ts = report.get("type_distribution_summary", {})
        f.write(f"Total card observations: {ts.get('total_cards_seen', 0)}\n")
        f.write(f"Unique aria-label prefixes: {ts.get('unique_aria_prefixes', [])}\n\n")

        for pos_summary in ts.get("by_position", []):
            f.write(
                f"  {pos_summary.get('label', '?'):>12}:  "
                f"cards={pos_summary.get('card_count', 0):3d}  "
                f"photo={pos_summary.get('photo', 0):3d}  "
                f"carousel={pos_summary.get('carousel', 0):3d}  "
                f"video={pos_summary.get('video', 0):3d}  "
                f"reel={pos_summary.get('reel', 0):3d}  "
                f"unknown={pos_summary.get('unknown', 0):3d}\n"
            )

        f.write("\n")
        for note in report.get("notes", []):
            f.write(f"NOTE: {note}\n")

    logger.info("TXT report saved: %s", txt_path)

    # ---- Screenshot ----
    if driver:
        try:
            save_screenshot(driver, str(DIAGNOSTICS_DIR), f"dom_probe_{timestamp}")
        except Exception:
            logger.exception("Failed to save screenshot.")


def print_summary(report: dict) -> None:
    """Print a short summary to the console."""
    ts = report.get("type_distribution_summary", {})
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Likes container found: {report.get('likes_container_found')}")
    print(f"Scrollable container found: {report.get('scrollable_container', {}).get('found')}")
    print(f"Scroll positions probed: {len(report.get('scroll_positions', []))}")
    print(f"Total card observations: {ts.get('total_cards_seen', 0)}")
    print(f"Unique aria-label prefixes: {ts.get('unique_aria_prefixes', [])}")
    print()

    for pos_summary in ts.get("by_position", []):
        print(
            f"  {pos_summary.get('label', '?'):>12}:  "
            f"cards={pos_summary.get('card_count', 0):3d}  "
            f"photo={pos_summary.get('photo', 0):3d}  "
            f"carousel={pos_summary.get('carousel', 0):3d}  "
            f"video={pos_summary.get('video', 0):3d}  "
            f"reel={pos_summary.get('reel', 0):3d}  "
            f"unknown={pos_summary.get('unknown', 0):3d}"
        )

    print()
    print("Diagnostic files saved in: diagnostics/")
    print("Review the JSON report for full card details.")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_probe()
