# ig_dislike

Automated tool to unlike Instagram Reels from your Liked items, built with diagnostic-first development.

## Purpose

Remove Reels from your ~48,000 liked Instagram items at:
`https://www.instagram.com/your_activity/interactions/likes`

This project takes a phased approach — proving each step is reliable before moving to the next.

## Environment

| Component             | Version / Path                                        |
|-----------------------|-------------------------------------------------------|
| OS                    | Windows                                               |
| Shell                 | PowerShell                                            |
| Python                | 3.14.5                                                |
| Selenium              | 4.50.0                                                |
| Firefox               | 157                                                   |
| Firefox executable    | `C:\Program Files\Mozilla Firefox\firefox.exe`        |
| Selenium profile      | `C:\Users\Shaunak\ig_selenium_profile`                |

The Selenium profile already contains the Instagram login session and is reused across runs.

## Setup

```powershell
# 1. Navigate to the project
cd C:\Users\Shaunak\Documents\ig_dislike

# 2. Create virtual environment (if not already created)
python -m venv .venv

# 3. Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r requirements.txt
```

## Usage

### Phase 1 – DOM Discovery (current)

```powershell
python -m src.dom_probe
```

This runs a **read-only** probe that:
- Launches Firefox with the existing profile
- Navigates to the Likes page
- Detects login state (URL-based)
- Locates the likes container and internal scrollable element
- Enumerates currently rendered media cards
- Scrolls through several positions and records card attributes
- Saves diagnostic files into `diagnostics/`

**No items are selected, unliked, or modified.**

### Alternative entry point

```powershell
python -m src.main probe
```

## Development Phases

| Phase | Name                | Status      | Description                                              |
|-------|---------------------|-------------|----------------------------------------------------------|
| 1     | DOM Discovery       | ✅ Built    | Read-only probe of the Likes page DOM                    |
| 2     | Reel Identification | ⬜ Pending  | Determine reliable Reel vs Photo vs Carousel markers     |
| 3     | Selection Proof     | ⬜ Pending  | Select Reels only, verify count, do not unlike           |
| 4     | Unlike Proof        | ⬜ Pending  | Single small batch unlike with verification              |
| 5     | Batch Loop          | ⬜ Pending  | Repeated batches with reload and re-detection            |

Each phase is only implemented after the previous phase is proven reliable.

## Known Instagram DOM Behavior

1. **Virtualised grid**: The Likes page does NOT render all ~48,000 items. Cards are recycled as the user scrolls. The DOM at any moment contains only a subset.

2. **Internal scrollable container**: There is a scrollable `<div>` inside the page — `window.scrollTo()` alone does NOT scroll the likes grid.

3. **Card identification**: Cards appear as `role="button"` elements with `aria-label` prefixes like `"Photo, ..."`, `"Carousel with ..."`. Video/Reel labels (`"Video, ..."`) are **not confirmed reliable** for Reel identification — this is what Phase 2 will determine.

4. **Selection mode**: The page has a "Select" button that enters multi-select mode. Selected items show a toolbar with an "Unlike" action.

5. **Confirmation dialog**: Clicking "Unlike" shows a `role="dialog"` confirmation modal with a native `<button>Unlike</button>`. This button **must** be clicked using Selenium WebDriver interaction, not JavaScript `.click()`.

6. **Post-unlike recovery**: After confirming unlike, the grid needs time to rebuild. The automation must wait, reload the page, and re-detect before starting the next batch.

7. **Stale elements**: After any scroll or page change, previously queried DOM elements are stale and must be re-queried.

## Architecture

```
ig_dislike/
├── src/
│   ├── __init__.py       Package init
│   ├── main.py           Entry point dispatcher
│   ├── browser.py        Firefox/Selenium lifecycle, wait helpers, screenshots
│   ├── instagram.py      Instagram page helpers (navigation, login, cards, scrolling)
│   ├── selectors.py      Central registry of all CSS/XPath selectors
│   └── dom_probe.py      Phase 1 read-only DOM discovery
├── diagnostics/          Generated reports (JSON, TXT, PNG) — gitignored
├── logs/                 Runtime logs — gitignored
└── tests/                Future test files
```

## Safety Notes

- **Phase 1 is strictly read-only.** Nothing is clicked, selected, or deleted.
- The project will not mass-unlike until diagnostic phases prove reliability.
- Destructive actions (unlike) always use Selenium WebDriver clicks, never JavaScript.
- Elements are re-queried after any DOM change to avoid stale references.
- No progress counters are trusted until the operation is verified end-to-end.
- Disappearance of a card from the virtualised DOM does NOT prove it was unliked.
