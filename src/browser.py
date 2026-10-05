"""
browser.py – Firefox/Selenium lifecycle management.

Responsibilities:
  - Launch Firefox with the existing Selenium profile.
  - Provide a configured WebDriver instance.
  - Provide helper utilities for waits, screenshots, and safe element queries.

This module does NOT know anything about Instagram's UI.
"""

import logging
import os
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FIREFOX_BINARY = r"C:\Program Files\Mozilla Firefox\firefox.exe"
PROFILE_PATH = r"C:\Users\Shaunak\ig_selenium_profile"

# Default explicit-wait timeout (seconds).
DEFAULT_WAIT = 15


# ---------------------------------------------------------------------------
# Browser launch
# ---------------------------------------------------------------------------

def create_driver(
    *,
    headless: bool = False,
    profile_path: str = PROFILE_PATH,
    firefox_binary: str = FIREFOX_BINARY,
) -> WebDriver:
    """
    Create and return a Firefox WebDriver using the existing Selenium profile.

    The profile at *profile_path* already contains the Instagram session/cookies,
    so no login automation is needed under normal circumstances.
    """
    logger.info("Launching Firefox with profile: %s", profile_path)

    options = Options()
    options.binary_location = firefox_binary

    # Use the existing profile directory.
    options.add_argument("-profile")
    options.add_argument(profile_path)

    if headless:
        options.add_argument("--headless")

    # Disable notifications popup.
    options.set_preference("dom.webnotifications.enabled", False)

    driver = webdriver.Firefox(options=options)

    # Start maximised so the viewport is large enough for Instagram's grid.
    driver.maximize_window()

    logger.info("Firefox launched.  Window size: %s", driver.get_window_size())
    return driver


# ---------------------------------------------------------------------------
# Wait helpers
# ---------------------------------------------------------------------------

def wait_for_element(
    driver: WebDriver,
    by: By,
    value: str,
    timeout: float = DEFAULT_WAIT,
    *,
    parent: WebElement | None = None,
) -> WebElement:
    """Wait until a single element is present and return it."""
    root = parent or driver
    return WebDriverWait(root, timeout).until(
        EC.presence_of_element_located((by, value))
    )


def wait_for_elements(
    driver: WebDriver,
    by: By,
    value: str,
    timeout: float = DEFAULT_WAIT,
) -> list[WebElement]:
    """Wait until at least one element matching *value* is present."""
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_all_elements_located((by, value))
    )


def wait_for_clickable(
    driver: WebDriver,
    by: By,
    value: str,
    timeout: float = DEFAULT_WAIT,
) -> WebElement:
    """Wait until an element is visible and clickable."""
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, value))
    )


def wait_for_url_contains(
    driver: WebDriver,
    fragment: str,
    timeout: float = DEFAULT_WAIT,
) -> bool:
    """Wait until the current URL contains *fragment*."""
    return WebDriverWait(driver, timeout).until(
        EC.url_contains(fragment)
    )


# ---------------------------------------------------------------------------
# Safe element queries (no exceptions on miss)
# ---------------------------------------------------------------------------

def find_element_safe(
    root: WebDriver | WebElement,
    by: By,
    value: str,
) -> WebElement | None:
    """Return element or None if not found (no exception)."""
    try:
        return root.find_element(by, value)
    except NoSuchElementException:
        return None


def find_elements_safe(
    root: WebDriver | WebElement,
    by: By,
    value: str,
) -> list[WebElement]:
    """Return list of elements (empty list if none found)."""
    try:
        return root.find_elements(by, value)
    except NoSuchElementException:
        return []


# ---------------------------------------------------------------------------
# Screenshot helper
# ---------------------------------------------------------------------------

def save_screenshot(driver: WebDriver, directory: str, prefix: str = "screenshot") -> str:
    """
    Save a full-page screenshot into *directory* with a timestamped filename.
    Returns the absolute path of the saved file.
    """
    os.makedirs(directory, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(directory, f"{prefix}_{ts}.png")
    driver.save_screenshot(filepath)
    logger.info("Screenshot saved: %s", filepath)
    return filepath


# ---------------------------------------------------------------------------
# Attribute extraction helpers
# ---------------------------------------------------------------------------

def get_attribute_safe(element: WebElement, attr: str) -> str | None:
    """Get an attribute value, returning None on stale-element errors."""
    try:
        return element.get_attribute(attr)
    except StaleElementReferenceException:
        logger.warning("Stale element when reading attribute '%s'", attr)
        return None


def get_element_info(element: WebElement) -> dict:
    """
    Extract a dictionary of useful attributes from a WebElement.
    Safe against stale-element errors (returns what it can).
    """
    info: dict = {}
    try:
        info["tag"] = element.tag_name
        info["role"] = element.get_attribute("role")
        info["aria-label"] = element.get_attribute("aria-label")
        info["href"] = element.get_attribute("href")
        info["data-testid"] = element.get_attribute("data-testid")
        info["class"] = element.get_attribute("class")
        info["text"] = element.text.strip() if element.text else ""

        # Dimensions
        rect = element.rect
        info["x"] = rect.get("x")
        info["y"] = rect.get("y")
        info["width"] = rect.get("width")
        info["height"] = rect.get("height")

    except StaleElementReferenceException:
        info["_stale"] = True
        logger.warning("Element went stale during info extraction")

    return info
