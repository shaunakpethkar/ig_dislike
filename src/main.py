"""
main.py – Entry point dispatcher for ig_dislike.

Usage:
    python -m src.main probe      Run Phase 1 DOM discovery (read-only)
    python -m src.main --help     Show available commands

Future phases will be added here as subcommands once proven reliable.
"""

import sys


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h"):
        print_help()
        return

    command = sys.argv[1].lower()

    if command == "probe":
        from src.dom_probe import run_probe
        run_probe()
    else:
        print(f"Unknown command: {command}")
        print_help()
        sys.exit(1)


def print_help() -> None:
    print("""
ig_dislike – Instagram Reel Unlike Automation
==============================================

Usage:  python -m src.main <command>

Commands:
  probe     Phase 1 – DOM discovery (read-only, safe)
              Inspects the Likes page, enumerates cards, identifies
              scrollable containers, and saves diagnostic reports.

Future commands (not yet implemented):
  identify  Phase 2 – Reel identification analysis
  select    Phase 3 – Selection proof (select only, no unlike)
  unlike    Phase 4 – Unlike proof (single batch)
  batch     Phase 5 – Batch unlike loop

Safety:
  Only 'probe' is currently implemented. It is strictly read-only.
  No items will be selected, unliked, or modified.
""")


if __name__ == "__main__":
    main()
