"""
instagram.py – Instagram page interaction helpers.

Responsibilities:
  - Navigate to Instagram pages.
  - Detect login state.
  - Wait for the Likes page to be ready.
  - Locate the internal scrollable container.
  - Enumerate currently-rendered media cards.
  - Classify cards by media type (when identification is proven).

This module uses selectors from selectors.py and browser helpers from browser.py.
It does NOT perform destructive actions (unlike, delete, etc.) — those belong
in a separate phase module.
"""

import logging
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)

from . import selectors
from .browser import (
    find_element_safe,
    find_elements_safe,
    get_attribute_safe,
    get_element_info,
    wait_for_element,
    wait_for_url_contains,
    DEFAULT_WAIT,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def navigate_to_likes(driver: WebDriver) -> None:
    """Navigate to the Instagram Likes page."""
    logger.info("Navigating to Likes page: %s", selectors.LIKES_PAGE_URL)
    driver.get(selectors.LIKES_PAGE_URL)
    # Small stabilisation delay for Instagram's SPA routing.
    time.sleep(2)


# ---------------------------------------------------------------------------
# Login detection
# ---------------------------------------------------------------------------

def is_login_required(driver: WebDriver) -> bool:
    """
    Determine whether Instagram has redirected to a login page.

    Detection is URL-based, NOT content-based:
      - If the URL contains /accounts/login or /accounts/emailsignup,
        login is required.
      - If the URL still contains the expected Likes path, we're logged in.
    """
    current_url = driver.current_url
    logger.info("Current URL: %s", current_url)

    for fragment in selectors.LOGIN_URL_FRAGMENTS:
        if fragment in current_url:
            logger.warning("Login required – URL contains '%s'", fragment)
            return True

    return False


def wait_for_manual_login(driver: WebDriver, timeout: float = 300) -> bool:
    """
    Wait up to *timeout* seconds for the user to manually log in.

    Returns True if the Likes page URL is detected, False on timeout.
    """
    logger.info(
        "Waiting up to %ds for manual login.  "
        "Please log in via the browser window.", timeout
    )
    try:
        wait_for_url_contains(driver, selectors.LIKES_PAGE_PATH, timeout=timeout)
        logger.info("Login detected – now on Likes page.")
        return True
    except TimeoutException:
        logger.error("Timed out waiting for manual login.")
        return False


# ---------------------------------------------------------------------------
# Likes page readiness
# ---------------------------------------------------------------------------

def wait_for_likes_container(
    driver: WebDriver, timeout: float = DEFAULT_WAIT
) -> WebElement | None:
    """
    Wait for the main Likes container to be present in the DOM.
    Returns the container element, or None on timeout.
    """
    try:
        container = wait_for_element(
            driver, By.CSS_SELECTOR, selectors.LIKES_CONTAINER, timeout=timeout
        )
        logger.info("Likes container found.")
        return container
    except TimeoutException:
        logger.error(
            "Likes container '%s' not found within %ds.",
            selectors.LIKES_CONTAINER, timeout,
        )
        return None


# ---------------------------------------------------------------------------
# Internal scrollable container discovery
# ---------------------------------------------------------------------------

def find_scrollable_container(driver: WebDriver) -> dict:
    """
    Attempt to identify the internal scrollable element within the Likes grid.

    Instagram virtualises the likes list inside a scrollable <div> that is NOT
    the main window. This function walks the DOM starting from the likes
    container to find elements whose scrollHeight > clientHeight.

    Returns a dict with:
      - "element":  the WebElement (or None)
      - "method":   how it was found
      - "candidates": list of candidate info dicts for diagnostics
    """
    result = {
        "element": None,
        "method": None,
        "candidates": [],
    }

    # Strategy: use JavaScript to find all elements with overflow scroll/auto
    # whose scrollHeight > clientHeight.
    js_find_scrollables = """
    const container = document.querySelector(arguments[0]);
    if (!container) return [];

    const results = [];
    const walker = document.createTreeWalker(
        container,
        NodeFilter.SHOW_ELEMENT,
        null,
        false
    );

    let node = walker.nextNode();
    while (node) {
        const style = window.getComputedStyle(node);
        const overflowY = style.overflowY;
        if (
            (overflowY === 'scroll' || overflowY === 'auto') &&
            node.scrollHeight > node.clientHeight
        ) {
            results.push({
                tag: node.tagName.toLowerCase(),
                id: node.id || null,
                className: node.className || null,
                role: node.getAttribute('role'),
                dataTestid: node.getAttribute('data-testid'),
                scrollTop: node.scrollTop,
                scrollHeight: node.scrollHeight,
                clientHeight: node.clientHeight,
                overflowY: overflowY,
                childCount: node.children.length,
            });
        }
        node = walker.nextNode();
    }
    return results;
    """

    try:
        candidates = driver.execute_script(js_find_scrollables, selectors.LIKES_CONTAINER)
        result["candidates"] = candidates or []

        if candidates:
            logger.info("Found %d scrollable candidate(s) inside likes container.", len(candidates))
            for i, c in enumerate(candidates):
                logger.info(
                    "  Candidate %d: <%s> scrollHeight=%s clientHeight=%s children=%s",
                    i, c.get("tag"), c.get("scrollHeight"), c.get("clientHeight"),
                    c.get("childCount"),
                )
        else:
            logger.warning("No scrollable containers found inside likes container.")

    except Exception:
        logger.exception("Error running scrollable-container discovery JS.")

    return result


# ---------------------------------------------------------------------------
# Card enumeration
# ---------------------------------------------------------------------------

def get_rendered_cards(driver: WebDriver) -> list[WebElement]:
    """
    Return a list of currently-rendered media card elements within the
    likes container.

    These are role="button" elements inside the likes container.
    The list may change after scrolling due to virtualisation.
    """
    container = find_element_safe(driver, By.CSS_SELECTOR, selectors.LIKES_CONTAINER)
    if container is None:
        logger.warning("Likes container not found – cannot enumerate cards.")
        return []

    cards = find_elements_safe(container, By.CSS_SELECTOR, selectors.MEDIA_CARD)
    logger.info("Found %d rendered card(s) in current viewport.", len(cards))
    return cards


def collect_card_diagnostics(element: WebElement) -> dict:
    """
    Collect comprehensive diagnostic information about a single media card.

    This gathers everything we might need to distinguish Reels from Photos
    and Carousels, WITHOUT clicking or modifying anything.
    """
    info = get_element_info(element)

    try:
        # ---- Descendant images ----
        imgs = element.find_elements(By.TAG_NAME, "img")
        img_data = []
        for img in imgs:
            img_data.append({
                "src": get_attribute_safe(img, "src"),
                "alt": get_attribute_safe(img, "alt"),
                "class": get_attribute_safe(img, "class"),
                "width": get_attribute_safe(img, "width"),
                "height": get_attribute_safe(img, "height"),
            })
        info["descendant_imgs"] = img_data

        # ---- Descendant videos ----
        videos = element.find_elements(By.TAG_NAME, "video")
        video_data = []
        for vid in videos:
            video_data.append({
                "src": get_attribute_safe(vid, "src"),
                "poster": get_attribute_safe(vid, "poster"),
                "class": get_attribute_safe(vid, "class"),
            })
        info["descendant_videos"] = video_data

        # ---- Descendant links ----
        links = element.find_elements(By.TAG_NAME, "a")
        link_data = []
        for a_tag in links:
            link_data.append({
                "href": get_attribute_safe(a_tag, "href"),
                "aria-label": get_attribute_safe(a_tag, "aria-label"),
                "text": a_tag.text.strip() if a_tag.text else "",
            })
        info["descendant_links"] = link_data

        # ---- Descendant SVGs (reel icon indicators) ----
        svgs = element.find_elements(By.TAG_NAME, "svg")
        svg_data = []
        for svg in svgs:
            svg_data.append({
                "aria-label": get_attribute_safe(svg, "aria-label"),
                "class": get_attribute_safe(svg, "class"),
                "role": get_attribute_safe(svg, "role"),
                "viewBox": get_attribute_safe(svg, "viewBox"),
            })
        info["descendant_svgs"] = svg_data

        # ---- Descendant spans (text labels) ----
        spans = element.find_elements(By.TAG_NAME, "span")
        span_texts = []
        for span in spans:
            text = span.text.strip() if span.text else ""
            if text:
                span_texts.append(text)
        info["descendant_span_texts"] = span_texts

        # ---- Descendant elements with role attributes ----
        role_elements = element.find_elements(By.CSS_SELECTOR, "[role]")
        role_data = []
        for el in role_elements:
            role_data.append({
                "tag": el.tag_name,
                "role": get_attribute_safe(el, "role"),
                "aria-label": get_attribute_safe(el, "aria-label"),
            })
        info["descendant_roles"] = role_data

        # ---- Descendant data-testid elements ----
        testid_elements = element.find_elements(By.CSS_SELECTOR, "[data-testid]")
        testid_data = []
        for el in testid_elements:
            testid_data.append({
                "tag": el.tag_name,
                "data-testid": get_attribute_safe(el, "data-testid"),
            })
        info["descendant_testids"] = testid_data

        # ---- Card's own outerHTML (first 2000 chars for structure analysis) ----
        outer_html = get_attribute_safe(element, "outerHTML")
        if outer_html:
            info["outerHTML_preview"] = outer_html[:2000]

    except StaleElementReferenceException:
        info["_stale"] = True
        logger.warning("Card element went stale during diagnostic collection.")

    return info


# ---------------------------------------------------------------------------
# Scroll helpers (READ-ONLY — scroll only, no interaction)
# ---------------------------------------------------------------------------

def get_scroll_metrics(driver: WebDriver, scrollable_css_path: str | None = None) -> dict:
    """
    Read the scroll metrics of the internal scrollable container.

    If scrollable_css_path is None, attempts to find the scrollable
    container automatically and reads its metrics.

    Returns a dict with scrollTop, scrollHeight, clientHeight.
    """
    js = """
    let el;
    if (arguments[0]) {
        el = document.querySelector(arguments[0]);
    } else {
        // Fallback: find the first scrollable child of the likes container.
        const container = document.querySelector(arguments[1]);
        if (!container) return null;
        const all = container.querySelectorAll('*');
        for (const node of all) {
            const style = window.getComputedStyle(node);
            if (
                (style.overflowY === 'scroll' || style.overflowY === 'auto') &&
                node.scrollHeight > node.clientHeight
            ) {
                el = node;
                break;
            }
        }
    }
    if (!el) return null;
    return {
        scrollTop: el.scrollTop,
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
    };
    """
    try:
        return driver.execute_script(js, scrollable_css_path, selectors.LIKES_CONTAINER)
    except Exception:
        logger.exception("Error reading scroll metrics.")
        return None


def scroll_internal_container(
    driver: WebDriver,
    delta_pixels: int,
    scrollable_css_path: str | None = None,
) -> dict | None:
    """
    Scroll the internal scrollable container by *delta_pixels*.

    Positive = scroll down, negative = scroll up.

    Returns the new scroll metrics after scrolling, or None on error.
    """
    js = """
    let el;
    if (arguments[0]) {
        el = document.querySelector(arguments[0]);
    } else {
        const container = document.querySelector(arguments[2]);
        if (!container) return null;
        const all = container.querySelectorAll('*');
        for (const node of all) {
            const style = window.getComputedStyle(node);
            if (
                (style.overflowY === 'scroll' || style.overflowY === 'auto') &&
                node.scrollHeight > node.clientHeight
            ) {
                el = node;
                break;
            }
        }
    }
    if (!el) return null;
    el.scrollTop += arguments[1];
    return {
        scrollTop: el.scrollTop,
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
    };
    """
    try:
        result = driver.execute_script(
            js, scrollable_css_path, delta_pixels, selectors.LIKES_CONTAINER
        )
        if result:
            logger.info(
                "Scrolled by %dpx → scrollTop=%d, scrollHeight=%d, clientHeight=%d",
                delta_pixels,
                result.get("scrollTop", -1),
                result.get("scrollHeight", -1),
                result.get("clientHeight", -1),
            )
        return result
    except Exception:
        logger.exception("Error scrolling internal container.")
        return None
