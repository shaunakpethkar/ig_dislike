"""Multi-load batch unliker.

Unlike the original batch unliker, this runner keeps Instagram's selection
mode open while it loads additional cards into the likes grid.  This permits
batch sizes larger than the first rendered page without changing the
original, conservative runner.
"""

import logging
import sys
import time
from datetime import datetime, timezone

from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By

from src import selectors
from src.batch_unliker import (
    _JS_SCROLL,
    ensure_selection_mode,
    find_confirm_unlike_button,
    find_unlike_toolbar_button,
    get_selected_count,
    is_clickable_outer_card,
    setup_logging,
    wait_for_container_with_loading_recovery,
    wait_for_dialog_to_close,
    wait_for_normal_mode,
)
from src.browser import create_driver
from src.instagram import is_login_required, wait_for_likes_container, wait_for_manual_login

logger = logging.getLogger(__name__)

_MEDIA_PREFIXES = ("Video", "Photo", "Carousel")
_SCROLL_DELTA = 700
_MAX_STALLED_SCROLLS = 4


def _visible_media_cards(container):
    """Return the currently rendered media card elements."""
    cards = []
    for card in container.find_elements(By.CSS_SELECTOR, '[role="button"]'):
        try:
            aria = (card.get_attribute("aria-label") or "").strip()
            rect = card.rect
            if (
                aria.startswith(_MEDIA_PREFIXES)
                and rect["width"] >= 50
                and rect["height"] >= 50
            ):
                cards.append(card)
        except (StaleElementReferenceException, KeyError):
            continue
    return cards


def _select_rendered_cards(driver, container, target, already_seen):
    """Select rendered cards, scrolling until *target* selections are confirmed."""
    selected = []
    selected_arias = set()
    previous_scroll_top = -1
    stalled_scrolls = 0

    while len(selected) < target:
        container = wait_for_container_with_loading_recovery(driver)
        if container is None:
            break

        progress = False
        for card in _visible_media_cards(container):
            if len(selected) >= target:
                break
            try:
                aria = (card.get_attribute("aria-label") or "").strip()
                if not aria or aria in already_seen or aria in selected_arias:
                    continue
                if not is_clickable_outer_card(driver, card):
                    continue
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'nearest',inline:'nearest'});",
                    card,
                )
                time.sleep(0.2)
                expected = len(selected) + 1
                card.click()  # Native Selenium click; do not use JavaScript.
                time.sleep(0.3)
                if get_selected_count(driver) != expected:
                    logger.warning("Selection count did not advance for %r.", aria)
                    continue
                selected_arias.add(aria)
                selected.append(
                    {"aria": aria, "selected_at": datetime.now(timezone.utc).isoformat()}
                )
                progress = True
                logger.info("  [%d/%d] Selected %r", len(selected), target, aria)
            except (StaleElementReferenceException, Exception) as exc:
                logger.warning("Could not select rendered card: %s", exc)

        if len(selected) >= target:
            break

        metrics = driver.execute_script(
            _JS_SCROLL, selectors.LIKES_CONTAINER, _SCROLL_DELTA
        )
        if metrics is None:
            logger.warning("Likes scroll container disappeared.")
            break
        scroll_top = metrics.get("scrollTop", 0)
        max_scroll = metrics.get("maxScroll", 0)
        near_bottom = max_scroll > 0 and scroll_top >= max_scroll - 200
        if scroll_top <= previous_scroll_top:
            stalled_scrolls += 1
        else:
            stalled_scrolls = 0
            previous_scroll_top = scroll_top
        logger.info(
            "Scroll: %d/%d (near bottom=%s), selected=%d/%d",
            scroll_top,
            max_scroll,
            near_bottom,
            len(selected),
            target,
        )
        time.sleep(2.0 if near_bottom or progress else 0.8)
        if stalled_scrolls >= _MAX_STALLED_SCROLLS:
            logger.info("Scroll made no progress; no more rendered cards are available.")
            break

    return selected


def _unlike_selection(driver, selected, summary, batch_number):
    """Run the existing count-checked toolbar and confirmation flow."""
    reported = get_selected_count(driver)
    if reported != len(selected):
        summary["errors"].append(
            f"Batch #{batch_number}: count mismatch "
            f"(Instagram={reported}, script={len(selected)})."
        )
        logger.error("HARD STOP — Instagram reports %d, expected %d.", reported, len(selected))
        return driver, False

    unlike = find_unlike_toolbar_button(driver)
    if not unlike:
        summary["errors"].append(f"Batch #{batch_number}: Unlike button missing.")
        return driver, False
    unlike.click()
    confirm = find_confirm_unlike_button(driver, timeout=8.0)
    if not confirm:
        summary["errors"].append(f"Batch #{batch_number}: Confirmation dialog missing.")
        return driver, False
    confirm.click()
    dialog_closed = wait_for_dialog_to_close(driver, timeout=10.0)
    time.sleep(2.0)

    after = get_selected_count(driver)
    recovered = wait_for_normal_mode(
        driver,
        dialog_closed=dialog_closed,
        selected_count_after_unlike=after,
    )
    if recovered is None:
        summary["errors"].append(f"Batch #{batch_number}: Normal mode recovery failed safely.")
        return driver, False
    return recovered, True


def run_batch_unliker_v2(batch_size: int = 80, max_batches: int = 1) -> dict:
    """Unlike batches while incrementally loading cards in selection mode."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    setup_logging(timestamp)
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
    unliked_arias = set()
    try:
        driver = create_driver()
        driver.get(selectors.LIKES_PAGE_URL)
        time.sleep(3)
        if is_login_required(driver):
            if not wait_for_manual_login(driver, timeout=300):
                summary["errors"].append("Login timed out.")
                return summary
            driver.get(selectors.LIKES_PAGE_URL)
            time.sleep(4)
        if wait_for_likes_container(driver, timeout=25) is None:
            summary["errors"].append("Likes container not found.")
            return summary

        batch_number = 0
        while max_batches is None or batch_number < max_batches:
            batch_number += 1
            if not ensure_selection_mode(driver):
                summary["errors"].append(f"Batch #{batch_number}: selection mode failed.")
                break
            selected = _select_rendered_cards(driver, None, batch_size, unliked_arias)
            if not selected:
                break
            driver, completed = _unlike_selection(driver, selected, summary, batch_number)
            if not completed:
                break
            unliked_arias.update(item["aria"] for item in selected)
            summary["unliked_items"].extend(selected)
            summary["batches_completed"] += 1
            summary["total_unliked_count"] += len(selected)
            logger.info(
                ">>> V2 BATCH #%d COMPLETE: Successfully unliked %d Reels. "
                "Batches completed: %d/%s. Likes unliked: %d in this batch, "
                "%d total this session.",
                batch_number,
                len(selected),
                summary["batches_completed"],
                max_batches if max_batches is not None else "unlimited",
                len(selected),
                summary["total_unliked_count"],
            )
            if len(selected) < batch_size:
                break
    except KeyboardInterrupt:
        logger.info("V2 batch unliker interrupted by user.")
    except Exception:
        logger.exception("Unexpected error in V2 batch unliker.")
        summary["errors"].append("Unexpected error; see log.")
    finally:
        if driver is not None:
            driver.quit()
    return summary
