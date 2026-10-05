"""
selectors.py – Central registry of all CSS selectors and XPath expressions.

Every selector used anywhere in the project is defined here. This ensures:
  - One place to update when Instagram changes its DOM.
  - No magic strings scattered across modules.
  - Easy auditing of what the project depends on.

Each selector has a comment explaining what it targets and when it was last
verified to work.
"""

# ---------------------------------------------------------------------------
# Likes page – main container
# ---------------------------------------------------------------------------

# The non-empty state wrapper that holds the liked-items grid.
# Verified: exists when user has liked items and is on the Likes page.
LIKES_CONTAINER = '[data-testid="liked_container_non_empty_state"]'

# ---------------------------------------------------------------------------
# Likes page – toolbar / selection mode
# ---------------------------------------------------------------------------

# The "Select" button that enters multi-select mode.
# Typically a role="button" inside the page header area.
SELECT_BUTTON = '[role="button"]:has-text("Select")'  # Placeholder – needs DOM probe validation

# The "Unlike" toolbar button (visible only in select mode with items selected).
UNLIKE_TOOLBAR = '[role="button"][aria-label="Unlike"]'

# ---------------------------------------------------------------------------
# Confirmation dialog
# ---------------------------------------------------------------------------

# The modal confirmation dialog that appears after clicking "Unlike".
CONFIRM_DIALOG = '[role="dialog"][aria-modal="true"]'

# The actual native <button> inside the confirmation dialog.
# MUST be clicked with Selenium WebDriver interaction, NOT JavaScript.
# XPath version for find_element(By.XPATH, ...).
CONFIRM_UNLIKE_XPATH = './/button[normalize-space()="Unlike"]'

# ---------------------------------------------------------------------------
# Media cards
# ---------------------------------------------------------------------------

# Generic media card selector – role="button" elements within the grid.
# These represent individual liked items (photos, reels, carousels).
MEDIA_CARD = '[role="button"]'

# Aria-label prefixes observed for different media types.
# WARNING: These are NOT confirmed reliable for Reel identification.
# dom_probe.py will test whether these hold across scroll positions.
ARIA_PREFIX_PHOTO = "Photo,"
ARIA_PREFIX_CAROUSEL = "Carousel with"
ARIA_PREFIX_VIDEO = "Video,"

# ---------------------------------------------------------------------------
# Login detection
# ---------------------------------------------------------------------------

# If the current URL contains any of these paths, the user is not logged in
# or has been redirected away from the Likes page.
LOGIN_URL_FRAGMENTS = [
    "/accounts/login",
    "/accounts/emailsignup",
]

# The expected URL path for the Likes page.
LIKES_PAGE_PATH = "/your_activity/interactions/likes"
LIKES_PAGE_URL = "https://www.instagram.com/your_activity/interactions/likes"
