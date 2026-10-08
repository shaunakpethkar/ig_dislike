"""V2 batch unliker with faster, condition-based card selection.

All batch, Unlike, confirmation, recovery, and accounting behavior is reused
from V2. Only the selection timing is changed.
"""

import logging
import time
from datetime import datetime, timezone

from selenium.common.exceptions import StaleElementReferenceException
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

from src import selectors
from src import batch_unliker_v2 as v2
from src.instagram import wait_for_likes_container

logger = logging.getLogger(__name__)

_COUNT_WAIT_TIMEOUT = 2.0
_NEW_CARD_WAIT_TIMEOUT = 2.0
_POLL_INTERVAL = 0.05
_RELOAD_READY_ATTEMPTS = 3
_RELOAD_CONTAINER_TIMEOUT = 30.0
_RELOAD_CARD_TIMEOUT = 15.0


def _visible_media_cards(container):
    cards = []
    for card in container.find_elements(By.CSS_SELECTOR, '[role="button"]'):
        try:
            aria = (card.get_attribute("aria-label") or "").strip()
            rect = card.rect
            if (
                aria.startswith(v2._MEDIA_PREFIXES)
                and rect["width"] >= 50
                and rect["height"] >= 50
            ):
                cards.append(card)
        except (StaleElementReferenceException, KeyError):
            continue
    return cards


def _wait_for_selected_count(driver, expected, timeout=_COUNT_WAIT_TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if v2.get_selected_count(driver) == expected:
            return True
        time.sleep(_POLL_INTERVAL)
    return v2.get_selected_count(driver) == expected


def _wait_for_new_media_cards(driver, known_arias, timeout=_NEW_CARD_WAIT_TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        container = v2.wait_for_container_with_loading_recovery(driver)
        if container is not None:
            for card in _visible_media_cards(container):
                if (card.get_attribute("aria-label") or "").strip() not in known_arias:
                    return True
        time.sleep(_POLL_INTERVAL)
    return False


def _wait_for_any_media_cards(driver, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        container = wait_for_likes_container(driver, timeout=1.0)
        if container is not None and _visible_media_cards(container):
            return True
        time.sleep(_POLL_INTERVAL)
    return False


def _reload_until_grid_ready(driver):
    """Retry same-session reloads until the next likes grid is observable."""
    for attempt in range(1, _RELOAD_READY_ATTEMPTS + 1):
        if attempt > 1:
            logger.info(
                "Likes grid still unavailable. Retrying current-page reload "
                "(attempt %d/%d)...",
                attempt,
                _RELOAD_READY_ATTEMPTS,
            )
            try:
                driver.refresh()
            except WebDriverException as exc:
                logger.warning("Retry reload failed: %s", exc)
                continue

        logger.info(
            "Waiting for likes container and cards (attempt %d/%d)...",
            attempt,
            _RELOAD_READY_ATTEMPTS,
        )
        if wait_for_likes_container(
            driver,
            timeout=_RELOAD_CONTAINER_TIMEOUT,
        ) is None:
            continue
        if _wait_for_any_media_cards(
            driver,
            timeout=_RELOAD_CARD_TIMEOUT,
        ):
            return True
    return False


def _unlike_selection(driver, selected, summary, batch_number):
    """Unlike safely, reload, and wait for the next card set."""
    reported = v2.get_selected_count(driver)
    if reported != len(selected):
        summary["errors"].append(
            f"Batch #{batch_number}: count mismatch "
            f"(Instagram={reported}, script={len(selected)})."
        )
        logger.error(
            "HARD STOP — Instagram reports %d, expected %d.",
            reported,
            len(selected),
        )
        return driver, False

    unlike = v2.find_unlike_toolbar_button(driver)
    if not unlike:
        summary["errors"].append(f"Batch #{batch_number}: Unlike button missing.")
        return driver, False
    unlike.click()
    confirm = v2.find_confirm_unlike_button(driver, timeout=8.0)
    if not confirm:
        summary["errors"].append(f"Batch #{batch_number}: Confirmation dialog missing.")
        return driver, False
    confirm.click()
    dialog_closed = v2.wait_for_dialog_to_close(driver, timeout=10.0)
    after = v2.get_selected_count(driver)
    if not dialog_closed or after != 0:
        summary["errors"].append(
            f"Batch #{batch_number}: unsafe post-confirmation state "
            f"(dialog_closed={dialog_closed}, selected={after})."
        )
        logger.error(
            "V4 recovery blocked: dialog_closed=%s, selected_count=%d.",
            dialog_closed,
            after,
        )
        return driver, False

    logger.info("Unlike confirmed. Reloading page for the next card set...")
    try:
        driver.refresh()
    except WebDriverException as exc:
        logger.warning("Current WebDriver refresh failed: %s", exc)
        recovered = v2.wait_for_normal_mode(
            driver,
            recovery_timeout=0.0,
            dialog_closed=True,
            selected_count_after_unlike=0,
        )
        if recovered is None:
            summary["errors"].append(
                f"Batch #{batch_number}: reload/recovery failed safely."
            )
            return driver, False
        driver = recovered

    logger.info("Reload complete. Waiting for likes container and new cards...")
    if not _reload_until_grid_ready(driver):
        summary["errors"].append(
            f"Batch #{batch_number}: likes grid was not restored after "
            f"{_RELOAD_READY_ATTEMPTS} reload attempts."
        )
        return driver, False

    recovered = v2.wait_for_normal_mode(
        driver,
        recovery_timeout=10.0,
        dialog_closed=True,
        selected_count_after_unlike=0,
    )
    if recovered is None:
        summary["errors"].append(
            f"Batch #{batch_number}: Normal mode recovery failed safely."
        )
        return driver, False
    return recovered, True


def _select_rendered_cards(driver, container, target, already_seen):
    selected = []
    selected_arias = set()
    previous_scroll_top = -1
    stalled_scrolls = 0

    while len(selected) < target:
        container = v2.wait_for_container_with_loading_recovery(driver)
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
                if not v2.is_clickable_outer_card(driver, card):
                    continue
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'nearest',inline:'nearest'});",
                    card,
                )
                expected = len(selected) + 1
                card.click()
                if not _wait_for_selected_count(driver, expected):
                    logger.warning("Selection count did not advance for %r.", aria)
                    continue
                selected_arias.add(aria)
                selected.append(
                    {"aria": aria, "selected_at": datetime.now(timezone.utc).isoformat()}
                )
                progress = True
                logger.info("  [%d/%d] Selected %r", len(selected), target, aria)
            except StaleElementReferenceException as exc:
                logger.warning("Could not select stale rendered card: %s", exc)

        if len(selected) >= target:
            break

        metrics = driver.execute_script(
            v2._JS_SCROLL, selectors.LIKES_CONTAINER, v2._SCROLL_DELTA
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
        known_arias = already_seen | selected_arias
        if not _wait_for_new_media_cards(driver, known_arias):
            stalled_scrolls += 1
        elif progress:
            stalled_scrolls = 0
        if stalled_scrolls >= v2._MAX_STALLED_SCROLLS:
            logger.info("Scroll made no progress; no more rendered cards are available.")
            break

    return selected


def run_batch_unliker_v4(batch_size: int = 80, max_batches: int = 1) -> dict:
    """Run V2's workflow with faster selection and a 10-second watchdog."""
    original_selector = v2._select_rendered_cards
    original_unlike = v2._unlike_selection
    v2._select_rendered_cards = _select_rendered_cards
    v2._unlike_selection = _unlike_selection
    try:
        return v2.run_batch_unliker_v2(batch_size=batch_size, max_batches=max_batches)
    finally:
        v2._select_rendered_cards = original_selector
        v2._unlike_selection = original_unlike
