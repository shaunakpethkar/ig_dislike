"""
batch_unliker.py – Instagram Reel Batch Unliker.

Architecture:
    1. Opens Likes page using existing Selenium profile.
    2. Enters selection mode (clicks exact-text 'Select' button).
    3. Finds visible cards where aria-label.startswith("Video").
       STRICT GUARD: NEVER selects cards starting with Photo or Carousel.
    4. Selects up to `batch_size` (default 18) Video cards by clicking the outer card wrapper.
    5. Scrolls internal container when needed to discover additional Video cards.
    6. Verifies Instagram reports exact batch count selected (e.g. 18 selected).
    7. Clicks 'Unlike' action button.
    8. Waits for confirmation modal dialog and clicks confirmation 'Unlike' via native Selenium .click().
    9. Waits for DOM update / API response.
    10. Repeats for subsequent batches up to `max_batches`.

Configurability:
    batch_size: configurable (default 18, easily changed to 27, 50, 100)
    max_batches: configurable (default 1 for initial single-batch verification)
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)

from src import selectors
from src.browser import create_driver
from src.instagram import is_login_required, wait_for_likes_container, wait_for_manual_login

LOGS_DIR = PROJECT_ROOT / "logs"
DIAGNOSTICS_DIR = PROJECT_ROOT / "diagnostics"
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(DIAGNOSTICS_DIR, exist_ok=True)

logger = logging.getLogger(__name__)

_JS_SCROLL = r"""
var container = document.querySelector(arguments[0]);
if (!container) return null;
var all = container.querySelectorAll('*');
var scrollEl = null;
for (var i = 0; i < all.length; i++) {
    var s = window.getComputedStyle(all[i]);
    if ((s.overflowY === 'scroll' || s.overflowY === 'auto') && all[i].scrollHeight > all[i].clientHeight) {
        scrollEl = all[i]; break;
    }
}
if (!scrollEl) return null;
scrollEl.scrollTop += arguments[1];
try { scrollEl.dispatchEvent(new Event('scroll', { bubbles: true, cancelable: true })); } catch(e) {}
return {
    scrollTop: Math.round(scrollEl.scrollTop),
    scrollHeight: scrollEl.scrollHeight,
    clientHeight: scrollEl.clientHeight,
    maxScroll: Math.max(0, scrollEl.scrollHeight - scrollEl.clientHeight)
};
"""

LOADING_STALL_TIMEOUT = 60.0


def setup_logging(timestamp: str) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S"
    ))
    root.addHandler(ch)

    fh = logging.FileHandler(
        LOGS_DIR / f"batch_unliker_{timestamp}.log", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(name)-20s  %(levelname)-8s  %(message)s"
    ))
    root.addHandler(fh)


def get_selected_count(driver) -> int:
    """Read the current selected count reported by Instagram."""
    for el in driver.find_elements(By.XPATH, "//*[contains(text(), 'selected') or contains(text(), 'Selected')]"):
        try:
            if el.is_displayed():
                txt = el.text.strip().lower()
                for part in txt.split():
                    if part.isdigit():
                        return int(part)
        except Exception:
            continue
    return 0


def ensure_selection_mode(driver) -> bool:
    """Ensure selection mode is active. If in normal mode, click Select."""
    # Check if Cancel button is already visible (selection mode active)
    for c in driver.find_elements(By.XPATH, "//*[normalize-space()='Cancel']"):
        try:
            if c.is_displayed() and c.is_enabled() and c.text.strip() == "Cancel":
                return True
        except Exception:
            continue

    # Not in selection mode -> click Select
    select_btn = None
    for c in driver.find_elements(By.XPATH, "//*[normalize-space()='Select']"):
        try:
            if c.is_displayed() and c.is_enabled() and c.text.strip() == "Select":
                select_btn = c
                break
        except Exception:
            continue

    if not select_btn:
        logger.error("Could not find 'Select' button to enter selection mode.")
        return False

    logger.info("Clicking 'Select' button to enter selection mode...")
    select_btn.click()
    time.sleep(2)

    # Verify Cancel button appears
    for c in driver.find_elements(By.XPATH, "//*[normalize-space()='Cancel']"):
        try:
            if c.is_displayed() and c.text.strip() == "Cancel":
                logger.info("Selection mode CONFIRMED (Cancel button visible).")
                return True
        except Exception:
            continue

    logger.warning("Selection mode entered, but Cancel button not confirmed.")
    return True


def find_unlike_toolbar_button(driver):
    """Locate the Unlike action button in the toolbar / footer."""
    # Try exact-text Unlike button (button or role=button)
    for b in driver.find_elements(By.XPATH, "//*[@role='button' or self::button][normalize-space()='Unlike']"):
        try:
            if b.is_displayed() and b.is_enabled():
                return b
        except Exception:
            continue

    # Try aria-label='Unlike'
    for b in driver.find_elements(By.XPATH, "//*[@aria-label='Unlike']"):
        try:
            if b.is_displayed() and b.is_enabled():
                return b
        except Exception:
            continue

    # Try starts-with Unlike (e.g. 'Unlike (18)')
    for b in driver.find_elements(By.XPATH, "//*[@role='button' or self::button][starts-with(normalize-space(), 'Unlike')]"):
        try:
            if b.is_displayed() and b.is_enabled():
                return b
        except Exception:
            continue

    # Fallback: any visible element with text 'Unlike' and reasonable size
    for b in driver.find_elements(By.XPATH, "//*[normalize-space()='Unlike']"):
        try:
            if b.is_displayed() and b.is_enabled() and b.rect["width"] > 15 and b.rect["height"] > 15:
                return b
        except Exception:
            continue

    return None


def find_confirm_unlike_button(driver, timeout: float = 8.0):
    """Locate the 'Unlike' button inside the confirmation modal dialog."""
    start = time.time()
    while time.time() - start < timeout:
        # Check inside role="dialog" or aria-modal="true" first
        dialogs = driver.find_elements(By.XPATH, "//*[@role='dialog' or @aria-modal='true']")
        for d in dialogs:
            try:
                if d.is_displayed():
                    btns = d.find_elements(
                        By.XPATH,
                        ".//button[normalize-space()='Unlike'] | "
                        ".//*[@role='button'][normalize-space()='Unlike'] | "
                        ".//*[normalize-space()='Unlike']"
                    )
                    for b in btns:
                        if b.is_displayed() and b.is_enabled() and b.rect["width"] > 15:
                            return b
            except Exception:
                continue

        # Fallback: check any newly displayed modal / overlay button with text 'Unlike'
        all_unlike_btns = driver.find_elements(
            By.XPATH,
            "//button[normalize-space()='Unlike'] | //*[@role='button'][normalize-space()='Unlike']"
        )
        for b in all_unlike_btns:
            try:
                if b.is_displayed() and b.is_enabled():
                    parent = driver.execute_script(
                        "return arguments[0].closest('[role=\"dialog\"], [aria-modal=\"true\"], div[style*=\"z-index\"]');",
                        b
                    )
                    if parent is not None:
                        return b
            except Exception:
                continue

        time.sleep(0.3)
    return None


def wait_for_dialog_to_close(driver, timeout: float = 10.0) -> bool:
    """Wait for modal confirmation dialog to disappear from view."""
    start = time.time()
    while time.time() - start < timeout:
        dialogs = [
            d for d in driver.find_elements(By.XPATH, "//*[@role='dialog' or @aria-modal='true']")
            if d.is_displayed()
        ]
        if not dialogs:
            return True
        time.sleep(0.3)
    return False


def _normal_mode_is_ready(driver) -> bool:
    """Return whether the current DOM is in normal mode."""
    try:
        select_visible = any(
            c.is_displayed()
            and c.is_enabled()
            and c.text.strip() == "Select"
            for c in driver.find_elements(By.XPATH, "//*[normalize-space()='Select']")
        )
        selection_controls_visible = any(
            c.is_displayed()
            for c in driver.find_elements(
                By.XPATH,
                "//*[normalize-space()='Cancel'] | //*[@aria-label='Unlike']",
            )
        )
    except (NoSuchElementException, StaleElementReferenceException):
        return False
    return select_visible and not selection_controls_visible


def _wait_for_normal_mode_state(driver, stable_for: float, timeout: float) -> bool:
    """Wait for one normal-mode state window, resetting timing for each DOM."""
    started = time.monotonic()
    normal_since = None
    while time.monotonic() - started < timeout:
        if _normal_mode_is_ready(driver):
            if normal_since is None:
                normal_since = time.monotonic()
            elif time.monotonic() - normal_since >= stable_for:
                return True
        else:
            normal_since = None
        time.sleep(0.5)
    return False


def _reload_is_safe_for_normal_mode_recovery(
    dialog_closed: bool,
    selected_count_after_unlike: int | None,
) -> bool:
    """Guard the post-Unlike reload against an unsafe in-progress operation."""
    if not dialog_closed:
        logger.error(
            "Cannot reload for normal-mode recovery: Unlike confirmation "
            "dialog was not confirmed closed."
        )
        return False

    if selected_count_after_unlike is None:
        logger.error(
            "Cannot restart for normal-mode recovery: post-Unlike selected "
            "count was not verified."
        )
        return False

    if selected_count_after_unlike != 0:
        logger.error(
            "Cannot restart for normal-mode recovery: post-Unlike selected "
            "count was %d, not zero.",
            selected_count_after_unlike,
        )
        return False

    return True


def _terminate_stuck_driver(driver) -> None:
    """Terminate the known Selenium service and its browser process tree."""
    service = getattr(driver, "service", None)
    process = getattr(service, "process", None)
    pid = getattr(process, "pid", None)
    if not pid:
        raise RuntimeError("Selenium service PID is unavailable.")

    logger.warning("Closing/replacing stuck browser session (PID %s)...", pid)
    completed = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Could not terminate Selenium process tree PID {pid}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )


def _start_replacement_driver():
    """Start a fresh configured session using the existing profile."""
    logger.info("Starting fresh Selenium session with existing profile...")
    replacement = create_driver()
    logger.info("Firefox session restored.")
    return replacement


def _recover_empty_batch_grid(driver, wait_timeout: float = 120.0):
    """Reload an empty, safe selection session and wait for media to load."""
    if get_selected_count(driver) != 0:
        logger.error("Cannot recover an empty grid while items are selected.")
        return None, False

    try:
        dialogs = [
            dialog
            for dialog in driver.find_elements(
                By.XPATH, "//*[@role='dialog' or @aria-modal='true']"
            )
            if dialog.is_displayed()
        ]
    except (NoSuchElementException, StaleElementReferenceException):
        dialogs = [True]
    if dialogs:
        logger.error("Cannot recover an empty grid while a dialog is open.")
        return None, False

    # The scan runs after selection mode is entered. Leave that empty mode
    # before restarting so the browser is never replaced during selection.
    cancel_buttons = driver.find_elements(By.XPATH, "//*[normalize-space()='Cancel']")
    for cancel in cancel_buttons:
        try:
            if cancel.is_displayed() and cancel.is_enabled():
                cancel.click()
                break
        except (NoSuchElementException, StaleElementReferenceException):
            continue

    if not _wait_for_normal_mode_state(driver, stable_for=1.5, timeout=10.0):
        logger.error("Could not leave empty selection mode safely.")
        return None, False

    logger.info(
        "No media cards found. Reloading page and waiting up to 120s "
        "for the grid to populate..."
    )
    try:
        logger.info("Reloading current Instagram likes page...")
        driver.refresh()
    except WebDriverException as exc:
        logger.error(
            "Current-session refresh failed during empty-grid recovery: %s",
            exc,
        )
        return None, False

    logger.info("Reload complete. Waiting for likes container...")
    container = wait_for_likes_container(driver, timeout=30)
    if container is None:
        logger.error("Likes container was not restored after empty-grid recovery.")
        return None, False
    logger.info("Likes container restored.")

    deadline = time.monotonic() + wait_timeout
    next_log = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            container = wait_for_likes_container(driver, timeout=1)
            if container is None:
                media_cards = []
            else:
                media_cards = [
                    card
                    for card in container.find_elements(By.CSS_SELECTOR, '[role="button"]')
                    if (card.get_attribute("aria-label") or "").strip().startswith(
                        ("Video", "Photo", "Carousel")
                    )
                ]
        except (NoSuchElementException, StaleElementReferenceException):
            media_cards = []

        if media_cards:
            logger.info("Media cards appeared after reload. Continuing.")
            return driver, True

        if time.monotonic() >= next_log:
            logger.info("Still waiting for media cards to appear...")
            next_log = time.monotonic() + 10
        time.sleep(1)

    logger.info(
        "No media cards appeared after reload and 120s wait. "
        "Assuming no liked items remain."
    )
    logger.info("Automation finished.")
    return driver, False


def wait_for_normal_mode(
    driver,
    stable_for: float = 1.5,
    recovery_timeout: float = 30.0,
    dialog_closed: bool = True,
    selected_count_after_unlike: int | None = None,
):
    """
    After an Unlike batch completes, wait for Instagram to return to normal
    (non-selection) mode.

    Keep the existing stable normal-mode predicate, but protect it with a
    dedicated 30-second watchdog. If the DOM does not recover in that window,
    restart the existing driver/profile only after safety checks pass. A
    restart never authorizes the next batch by itself; normal mode must be
    detected and stable again afterward. Returns the healthy current driver,
    or None when recovery cannot be established safely.
    """
    reloaded = False
    while True:
        logger.info("Waiting for normal mode...")
        if _wait_for_normal_mode_state(driver, stable_for, recovery_timeout):
            if reloaded:
                logger.info("Normal mode restored after reload. Resuming next batch.")
            else:
                logger.info("Normal mode restored and stable — Select button visible.")
            return driver

        logger.warning(
            "Normal mode recovery stalled for %.0fs.",
            recovery_timeout,
        )
        if not _reload_is_safe_for_normal_mode_recovery(
            dialog_closed,
            selected_count_after_unlike,
        ):
            return None

        logger.info("Reloading current Instagram likes page...")
        try:
            driver.refresh()
        except WebDriverException as exc:
            logger.warning(
                "WebDriver/browser appears unresponsive; restarting Selenium session: %s",
                exc,
            )
            try:
                _terminate_stuck_driver(driver)
            except (OSError, RuntimeError, subprocess.SubprocessError) as terminate_exc:
                logger.error("Could not terminate stuck browser safely: %s", terminate_exc)
                return None

            driver = None
            try:
                driver = _start_replacement_driver()
                logger.info("Navigating to Instagram likes page...")
                driver.get(selectors.LIKES_PAGE_URL)
                time.sleep(3)
                if is_login_required(driver):
                    logger.error(
                        "Replacement session requires login; refusing login automation "
                        "during recovery."
                    )
                    return None
            except (OSError, RuntimeError, WebDriverException) as restart_exc:
                logger.error("Fresh Selenium session recovery failed: %s", restart_exc)
                if driver is not None:
                    try:
                        _terminate_stuck_driver(driver)
                    except (OSError, RuntimeError, subprocess.SubprocessError) as cleanup_exc:
                        logger.error(
                            "Could not terminate failed replacement session: %s",
                            cleanup_exc,
                        )
                return None

            reloaded = True
            logger.info("Fresh session navigation complete. Waiting for likes container...")
        else:
            reloaded = True
            logger.info("Reload complete. Waiting for likes container...")

        container = wait_for_likes_container(driver, timeout=30)
        if container is None:
            logger.error(
                "Reload did not restore the likes container; retrying recovery."
            )
            continue

        # The next loop starts fresh timers and re-queries every DOM element.
        logger.info("Likes container restored. Waiting for normal mode...")


def is_clickable_outer_card(driver, btn) -> bool:
    """Verify this element is the clickable outer card for a Video item."""
    try:
        return driver.execute_script(
            """
            var el = arguments[0];
            var s = window.getComputedStyle(el);
            if (s.pointerEvents === 'none') return false;
            // The outer card contains the Toggle checkbox descendant
            var hasCheckbox = el.querySelector('[aria-label="Toggle checkbox"]') !== null;
            var isPointer = s.cursor === 'pointer' || el.style.pointerEvents === 'auto';
            return hasCheckbox || isPointer;
            """,
            btn
        )
    except Exception:
        return False


def reload_likes_page_after_loading_stall(driver):
    """Reload the existing page/profile and return a fresh likes container."""
    logger.warning(
        "Loading stall detected: no new media for 60s. "
        "Reloading Instagram likes page..."
    )
    while True:
        try:
            driver.refresh()
        except WebDriverException:
            logger.exception("Reload failed; retrying Instagram likes page reload.")
            time.sleep(1)
            continue

        logger.info("Reload complete. Waiting for likes container...")
        container = wait_for_likes_container(driver, timeout=30)
        if container is None:
            logger.error("Reload did not restore the likes container; retrying.")
            continue

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                select_visible = any(
                    element.is_displayed() and element.is_enabled()
                    for element in driver.find_elements(
                        By.XPATH, "//*[normalize-space()='Select']"
                    )
                )
                cancel_visible = any(
                    element.is_displayed()
                    for element in driver.find_elements(
                        By.XPATH, "//*[normalize-space()='Cancel']"
                    )
                )
            except (NoSuchElementException, StaleElementReferenceException):
                select_visible = False
                cancel_visible = True

            if select_visible and not cancel_visible:
                logger.info("Likes container restored. Resuming scan.")
                return container
            time.sleep(0.5)

        logger.error("Reload did not restore normal mode; retrying.")


def wait_for_container_with_loading_recovery(driver):
    """Wait for the scan container and recover if it remains unavailable."""
    stalled_since = time.monotonic()
    while True:
        container = wait_for_likes_container(driver, timeout=10)
        if container is not None:
            return container

        if time.monotonic() - stalled_since <= LOADING_STALL_TIMEOUT:
            continue

        if get_selected_count(driver) != 0:
            logger.error(
                "Loading stall detected while items are selected. "
                "Stopping before any reload."
            )
            return None

        return reload_likes_page_after_loading_stall(driver)


def run_batch_unliker(batch_size: int = 18, max_batches: int = 1) -> dict:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    setup_logging(timestamp)

    logger.info("=" * 70)
    logger.info("INSTAGRAM LIKES BATCH UNLIKER")
    logger.info("=" * 70)
    logger.info("Batch Size  : %d items per batch", batch_size)
    logger.info("Max Batches : %s", max_batches if max_batches else "Unlimited")
    logger.info("Target      : All media cards (Video, Photo, Carousel)")
    logger.info("Strategy    : Select from currently loaded grid — no deep scroll")
    logger.info("=" * 70)

    summary = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "timestamp": timestamp,
        "batch_size": batch_size,
        "max_batches": max_batches,
        "batches_completed": 0,
        "total_unliked_count": 0,
        "unliked_items": [],
        "errors": [],
    }

    driver = None
    session_unliked_arias: set[str] = set()

    try:
        logger.info("Launching Firefox with existing profile...")
        driver = create_driver()

        logger.info("Navigating to Likes page...")
        driver.get(selectors.LIKES_PAGE_URL)
        time.sleep(3)

        if is_login_required(driver):
            logger.info("Login required — waiting for manual login...")
            if not wait_for_manual_login(driver, timeout=300):
                logger.error("Login timed out.")
                summary["errors"].append("Login timed out.")
                return summary
            driver.get(selectors.LIKES_PAGE_URL)
            time.sleep(4)

        container = wait_for_likes_container(driver, timeout=25)
        if container is None:
            logger.error("Likes container not found.")
            summary["errors"].append("Likes container not found.")
            return summary

        logger.info("Likes container confirmed.")
        time.sleep(2)

        batch_number = 0

        while True:
            if max_batches is not None and batch_number >= max_batches:
                logger.info("Reached requested max_batches (%d). Stopping.", max_batches)
                break

            batch_number += 1
            logger.info("\n" + "=" * 70)
            logger.info("STARTING BATCH #%d (Target: %d Reels)", batch_number, batch_size)
            logger.info("=" * 70)

            # Ensure we are in selection mode
            if not ensure_selection_mode(driver):
                logger.error("Failed to enter selection mode for Batch #%d.", batch_number)
                break

            current_count = get_selected_count(driver)
            logger.info("Current selection count at start of batch: %d", current_count)

            # per-batch identity set: O(1) dedup
            selected_arias_this_batch: set[str] = set()
            selected_in_this_batch: list[dict] = []

            # ---------------------------------------------------------------
            # COLLECTION: single scan of the currently loaded grid.
            # No scrolling — Instagram reloads the grid after each Unlike,
            # so the next batch always starts fresh from the top.
            # ---------------------------------------------------------------
            container = wait_for_container_with_loading_recovery(driver)
            if not container:
                logger.warning("Likes container vanished. Stopping.")
                break

            all_buttons = container.find_elements(By.CSS_SELECTOR, '[role="button"]')
            total_btns     = len(all_buttons)
            new_selected   = 0
            skipped_not_media = 0
            skipped_too_small = 0
            skipped_not_outer = 0
            skipped_already   = 0

            for btn in all_buttons:
                if len(selected_in_this_batch) >= batch_size:
                    break

                try:
                    aria = (btn.get_attribute("aria-label") or "").strip()
                except Exception:
                    continue

                # Target: Video, Photo, or Carousel media cards
                if not aria.startswith(("Video", "Photo", "Carousel")):
                    skipped_not_media += 1
                    continue

                # Size guard: exclude tiny toolbar/checkbox elements
                try:
                    r = btn.rect
                    if r["width"] < 50 or r["height"] < 50:
                        skipped_too_small += 1
                        continue
                except Exception:
                    continue

                # Must be the clickable outer wrapper (has checkbox, pointer-events != none)
                if not is_clickable_outer_card(driver, btn):
                    skipped_not_outer += 1
                    continue

                # Per-batch dedup
                if aria in session_unliked_arias or aria in selected_arias_this_batch:
                    skipped_already += 1
                    continue

                # ScrollIntoView only if card is outside the visible viewport
                driver.execute_script(
                    "var r=arguments[0].getBoundingClientRect();"
                    "if(r.bottom>window.innerHeight||r.top<0){"
                    "arguments[0].scrollIntoView({block:'nearest',inline:'nearest'});}"
                    , btn
                )
                time.sleep(0.25)

                expected_count_after = len(selected_in_this_batch) + 1

                try:
                    btn.click()
                    time.sleep(0.3)
                except Exception as e:
                    logger.warning("btn.click() raised on %r (%s). Trying ActionChains...", aria, e)
                    try:
                        from selenium.webdriver.common.action_chains import ActionChains
                        ActionChains(driver).move_to_element(btn).click().perform()
                        time.sleep(0.3)
                    except Exception as e2:
                        logger.error("ActionChains also failed on %r: %s", aria, e2)
                        continue

                # AUTHORITATIVE CONFIRMATION
                confirmed_count = get_selected_count(driver)
                if confirmed_count == expected_count_after:
                    selected_arias_this_batch.add(aria)
                    selected_in_this_batch.append({
                        "aria": aria,
                        "selected_at": datetime.now(timezone.utc).isoformat(),
                    })
                    new_selected += 1
                    logger.info("  [%2d/%2d] Confirmed (Instagram=%d): %r",
                                len(selected_in_this_batch), batch_size, confirmed_count, aria)
                else:
                    logger.warning(
                        "NOT confirmed for %r — expected %d, got %d. Skipping.",
                        aria, expected_count_after, confirmed_count
                    )

            logger.info(
                "Scan: total_btns=%d | selected=%d | "
                "not_media=%d not_outer=%d too_small=%d already=%d | progress=%d/%d",
                total_btns, new_selected,
                skipped_not_media, skipped_not_outer, skipped_too_small, skipped_already,
                len(selected_in_this_batch), batch_size,
            )

            actual_selected = len(selected_in_this_batch)
            logger.info("Collected %d items for Batch #%d.", actual_selected, batch_number)

            if actual_selected == 0:
                driver, media_available = _recover_empty_batch_grid(driver)
                if driver is None:
                    summary["errors"].append(
                        f"Batch #{batch_number}: Empty-grid recovery failed safely."
                    )
                    break
                if not media_available:
                    break
                batch_number -= 1
                continue


                # --- FETCH current DOM buttons (needed for count check regardless) ---
                container = wait_for_likes_container(driver, timeout=10)
                if not container:
                    logger.warning("Likes container vanished during batch collection. Stopping.")
                    break

                all_buttons = container.find_elements(By.CSS_SELECTOR, '[role="button"]')
                total_btns = len(all_buttons)

                if total_btns != prev_total_btns:
                    # --- Instagram loaded new content (or first scan) — full scan+select ---
                    prev_total_btns = total_btns
                    new_this_scan = 0
                    skipped_not_video = 0
                    skipped_too_small = 0
                    skipped_not_outer = 0
                    skipped_already   = 0

                    # --- SELECT: click every eligible Video card in this DOM snapshot ---
                    for btn in all_buttons:
                        if len(selected_in_this_batch) >= batch_size:
                            break

                        try:
                            aria = (btn.get_attribute("aria-label") or "").strip()
                        except Exception:
                            continue

                        # STRICT SAFETY FILTER – only Video cards
                        if not aria.startswith("Video"):
                            skipped_not_video += 1
                            continue

                        # Minimum size guard (toolbar buttons are tiny)
                        try:
                            r = btn.rect
                            if r["width"] < 50 or r["height"] < 50:
                                skipped_too_small += 1
                                continue
                        except Exception:
                            continue

                        # Must be the clickable outer wrapper (pointer-events != none, has checkbox)
                        if not is_clickable_outer_card(driver, btn):
                            skipped_not_outer += 1
                            continue

                        # Per-batch dedup (O(1) set lookup)
                        if aria in session_unliked_arias or aria in selected_arias_this_batch:
                            skipped_already += 1
                            continue

                        # --- Click to select (scrollIntoView only if outside current viewport) ---
                        driver.execute_script(
                            "var r=arguments[0].getBoundingClientRect();"
                            "if(r.bottom>window.innerHeight||r.top<0){"
                            "arguments[0].scrollIntoView({block:'nearest',inline:'nearest'});}"
                            , btn
                        )
                        time.sleep(0.25)

                        # Expected Instagram count after this click
                        expected_count_after = len(selected_in_this_batch) + 1

                        try:
                            btn.click()
                            time.sleep(0.3)
                        except Exception as e:
                            logger.warning("btn.click() raised on %r (%s). Trying ActionChains...", aria, e)
                            try:
                                from selenium.webdriver.common.action_chains import ActionChains
                                ActionChains(driver).move_to_element(btn).click().perform()
                                time.sleep(0.3)
                            except Exception as e2:
                                logger.error("ActionChains also failed on %r: %s", aria, e2)
                                continue  # skip this card entirely

                        # --- AUTHORITATIVE CONFIRMATION: ask Instagram how many are selected ---
                        confirmed_count = get_selected_count(driver)
                        if confirmed_count == expected_count_after:
                            selected_arias_this_batch.add(aria)
                            selected_in_this_batch.append({
                                "aria": aria,
                                "selected_at": datetime.now(timezone.utc).isoformat(),
                            })
                            new_this_scan += 1
                            logger.info("  [%2d/%2d] Confirmed selected (Instagram=%d): %r",
                                        len(selected_in_this_batch), batch_size,
                                        confirmed_count, aria)
                        else:
                            logger.warning(
                                "Selection NOT confirmed for %r — "
                                "expected Instagram count %d, got %d. Skipping this card.",
                                aria, expected_count_after, confirmed_count
                            )

                    # Log scan result (only fires when new content was actually present)
                    logger.info(
                        "Scan after scroll %d: total_btns=%d | new_selected=%d | "
                        "not_video=%d not_outer=%d too_small=%d already=%d | "
                        "batch_progress=%d/%d",
                        scroll_attempts, total_btns, new_this_scan,
                        skipped_not_video, skipped_not_outer, skipped_too_small, skipped_already,
                        len(selected_in_this_batch), batch_size,
                    )
                else:
                    # Content unchanged since last scan — nothing new to select, skip.
                    logger.info(
                        "  Scroll %d: btns=%d (no new content). Scrolling toward next page...",
                        scroll_attempts, total_btns
                    )

                if len(selected_in_this_batch) >= batch_size:
                    break

                # --- SCROLL: adaptive delta ---
                # Instagram's lazy loader requires *incremental* scroll events approaching
                # the bottom; a single jump to maxScroll is silently ignored.
                #
                # • No Video found this scan → 1000px step + 0.5s sleep (2x faster traversal
                #   of Photo/Carousel regions without breaking the incremental trigger).
                # • Video found this scan    → 500px step + 1.2s sleep (fine-grained so no
                #   Video card is ever scrolled past before being selected).
                scroll_attempts += 1
                if scroll_attempts > max_scroll_attempts:
                    logger.warning("Reached max scroll attempts (%d). Ending batch collection.", max_scroll_attempts)
                    break

                if new_this_scan == 0:
                    scroll_delta = 1000
                    sleep_normal = 0.5   # DOM scroll registration; no render wait needed
                else:
                    scroll_delta = 500
                    sleep_normal = 1.2   # give Instagram time to render newly exposed cards

                m = driver.execute_script(_JS_SCROLL, selectors.LIKES_CONTAINER, scroll_delta)
                if m is None:
                    logger.warning("Scroll container gone at step %d. Stopping.", scroll_attempts)
                    break

                current_scroll_top = m.get("scrollTop", 0)
                max_scroll         = m.get("maxScroll", 0)
                near_bottom        = max_scroll > 0 and current_scroll_top >= max_scroll - 200

                if current_scroll_top <= prev_scroll_top:
                    non_advancing_scrolls += 1
                    if near_bottom:
                        logger.info(
                            "  Scroll %d: scrollTop not advancing (%d/%d). "
                            "Near bottom — waiting 2.5s for network load...",
                            scroll_attempts, current_scroll_top, max_scroll
                        )
                        time.sleep(2.5)
                    if non_advancing_scrolls >= MAX_NON_ADVANCING:
                        logger.info(
                            "scrollTop stuck at %d for %d consecutive steps — "
                            "true end of content reached. Ending batch collection.",
                            current_scroll_top, non_advancing_scrolls
                        )
                        break
                else:
                    non_advancing_scrolls = 0
                    prev_scroll_top       = current_scroll_top
                    step_label = f"+{scroll_delta}px"
                    if near_bottom:
                        logger.info(
                            "  Scroll %d [%s]: scrollTop=%d/%d (near bottom). "
                            "Waiting 2.0s for network load...",
                            scroll_attempts, step_label, current_scroll_top, max_scroll
                        )
                        time.sleep(2.0)
                    else:
                        logger.info("  Scroll %d [%s]: scrollTop=%d/%d.",
                                    scroll_attempts, step_label, current_scroll_top, max_scroll)
                        time.sleep(sleep_normal)


            actual_selected = len(selected_in_this_batch)
            logger.info("Collected %d Video cards for Batch #%d.", actual_selected, batch_number)

            if actual_selected == 0:
                logger.info("No Video cards available to unlike. Automation finished.")
                break

            # ---------------------------------------------------------------
            # Verify Count  — any mismatch is a HARD SAFETY STOP
            # ---------------------------------------------------------------
            time.sleep(1.0)
            reported_count = get_selected_count(driver)
            logger.info("Instagram reported count: %d (Expected: %d)", reported_count, actual_selected)

            if reported_count != actual_selected:
                logger.error(
                    "HARD STOP — count mismatch: Instagram reports %d selected, "
                    "script recorded %d. Aborting to prevent action on wrong items.",
                    reported_count, actual_selected
                )
                summary["errors"].append(
                    f"Batch #{batch_number}: count mismatch "
                    f"(Instagram={reported_count}, script={actual_selected})."
                )
                break

            # ---------------------------------------------------------------
            # Click 'Unlike' Action Button
            # ---------------------------------------------------------------
            logger.info("Locating 'Unlike' action button...")
            unlike_btn = find_unlike_toolbar_button(driver)
            if not unlike_btn:
                logger.error("Could not locate 'Unlike' action button on toolbar.")
                summary["errors"].append(f"Batch #{batch_number}: Unlike button missing.")
                break

            logger.info("Clicking 'Unlike' toolbar button...")
            unlike_btn.click()
            time.sleep(1.5)

            # ---------------------------------------------------------------
            # Confirm in Modal Dialog
            # ---------------------------------------------------------------
            logger.info("Waiting for confirmation modal dialog...")
            confirm_btn = find_confirm_unlike_button(driver, timeout=8.0)
            if not confirm_btn:
                logger.error("Confirmation modal 'Unlike' button not found!")
                summary["errors"].append(f"Batch #{batch_number}: Confirmation dialog missing.")
                break

            logger.info("Clicking confirmation 'Unlike' button via native Selenium .click()...")
            confirm_btn.click()

            # ---------------------------------------------------------------
            # Wait for DOM Update / API Response
            # ---------------------------------------------------------------
            logger.info("Waiting for confirmation dialog to close and API update...")
            dialog_closed = wait_for_dialog_to_close(driver, timeout=10.0)
            logger.info("Dialog closed: %s. Waiting for grid DOM to update...", dialog_closed)
            time.sleep(2.0)  # brief settle before polling for Select

            # Record batch completion
            for item in selected_in_this_batch:
                session_unliked_arias.add(item["aria"])
                summary["unliked_items"].append(item)

            summary["batches_completed"] += 1
            summary["total_unliked_count"] += actual_selected

            logger.info(
                ">>> BATCH #%d COMPLETE: Successfully unliked %d Reels. (Total unliked session: %d)",
                batch_number, actual_selected, summary["total_unliked_count"]
            )

            # ---------------------------------------------------------------
            # Wait for page to return to normal mode before next batch
            # ---------------------------------------------------------------
            try:
                selected_count_after_unlike = get_selected_count(driver)
            except WebDriverException:
                logger.exception(
                    "Could not verify zero selected items after Unlike; "
                    "stopping safely."
                )
                selected_count_after_unlike = None

            recovered_driver = wait_for_normal_mode(
                driver,
                dialog_closed=dialog_closed,
                selected_count_after_unlike=selected_count_after_unlike,
            )
            if recovered_driver is None:
                logger.error(
                    "Aborting: healthy browser session and normal mode were "
                    "not restored after Batch #%d.",
                    batch_number
                )
                summary["errors"].append(
                    f"Batch #{batch_number}: Normal mode recovery failed safely."
                )
                break
            driver = recovered_driver
            time.sleep(0.5)  # small settle after Select appears

    except KeyboardInterrupt:
        logger.info("Batch unliker interrupted by user.")
    except Exception:
        logger.exception("Unexpected error in batch unliker.")
        summary["errors"].append("Unexpected exception occurred.")
    finally:
        # Save session summary report
        try:
            import json
            diag_file = DIAGNOSTICS_DIR / f"batch_unliker_{timestamp}.json"
            with open(diag_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
            logger.info("Batch summary saved to: %s", diag_file)
        except Exception:
            logger.exception("Failed to save batch summary.")

        if driver:
            try:
                driver.quit()
                logger.info("Firefox closed.")
            except Exception:
                pass

    print("\n" + "=" * 70)
    print("BATCH UNLIKER SUMMARY")
    print("=" * 70)
    print(f"Batches Completed : {summary['batches_completed']}")
    print(f"Total Reels Unliked: {summary['total_unliked_count']}")
    print(f"Batch Size Used   : {batch_size}")
    print(f"Errors Logged     : {len(summary['errors'])}")
    print("=" * 70 + "\n")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Instagram Reel Batch Unliker")
    parser.add_argument(
        "--batch-size", type=int, default=18,
        help="Number of Reels to select per batch (default: 18)"
    )
    parser.add_argument(
        "--max-batches", type=int, default=1,
        help="Maximum number of batches to run (default: 1 for single-batch verification, set higher for continuous)"
    )
    args = parser.parse_args()

    run_batch_unliker(batch_size=args.batch_size, max_batches=args.max_batches)


if __name__ == "__main__":
    main()
