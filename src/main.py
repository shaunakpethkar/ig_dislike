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
    elif command == "select":
        from src.selection_probe import run_selection_probe
        run_selection_probe()
    elif command in ("load", "loading"):
        from src.loading_probe import run_loading_probe
        run_loading_probe()
    elif command in ("detect", "reel"):
        from src.reel_detection_probe import run_reel_detection_probe
        run_reel_detection_probe()
    elif command in ("test_select", "test-select", "test"):
        from src.selection_test import run_selection_test
        run_selection_test()
    elif command in ("unlike", "batch"):
        import argparse
        parser = argparse.ArgumentParser(prog=f"python -m src.main {command}", description="Instagram Reel Batch Unliker")
        parser.add_argument("--batch-size", type=int, default=18, help="Reels per batch (default: 18)")
        parser.add_argument("--max-batches", type=int, default=1, help="Max batches to run (default: 1)")
        parsed_args = parser.parse_args(sys.argv[2:])
        from src.batch_unliker import run_batch_unliker
        run_batch_unliker(batch_size=parsed_args.batch_size, max_batches=parsed_args.max_batches)
    elif command == "unlike-v2":
        import argparse
        parser = argparse.ArgumentParser(
            prog="python -m src.main unlike-v2",
            description="Instagram multi-load batch unliker",
        )
        parser.add_argument("--batch-size", type=int, default=80, help="Items per batch (default: 80)")
        parser.add_argument("--max-batches", type=int, default=1, help="Max batches to run (default: 1)")
        parsed_args = parser.parse_args(sys.argv[2:])
        from src.batch_unliker_v2 import run_batch_unliker_v2
        run_batch_unliker_v2(
            batch_size=parsed_args.batch_size,
            max_batches=parsed_args.max_batches,
        )
    elif command == "unlike-v3":
        import argparse
        parser = argparse.ArgumentParser(
            prog="python -m src.main unlike-v3",
            description="Instagram faster multi-load batch unliker",
        )
        parser.add_argument("--batch-size", type=int, default=80, help="Items per batch (default: 80)")
        parser.add_argument("--max-batches", type=int, default=1, help="Max batches to run (default: 1)")
        parsed_args = parser.parse_args(sys.argv[2:])
        from src.batch_unliker_v3 import run_batch_unliker_v3
        run_batch_unliker_v3(
            batch_size=parsed_args.batch_size,
            max_batches=parsed_args.max_batches,
        )
    elif command == "unlike-v4":
        import argparse
        parser = argparse.ArgumentParser(
            prog="python -m src.main unlike-v4",
            description="Instagram V2 workflow with faster selection",
        )
        parser.add_argument("--batch-size", type=int, default=80, help="Items per batch (default: 80)")
        parser.add_argument("--max-batches", type=int, default=1, help="Max batches to run (default: 1)")
        parsed_args = parser.parse_args(sys.argv[2:])
        from src.batch_unliker_v4 import run_batch_unliker_v4
        run_batch_unliker_v4(
            batch_size=parsed_args.batch_size,
            max_batches=parsed_args.max_batches,
        )
    elif command == "unlike-portable":
        import argparse
        parser = argparse.ArgumentParser(
            prog="python -m src.main unlike-portable",
            description="Portable V4 Instagram batch unliker",
        )
        parser.add_argument("--batch-size", type=int, default=80, help="Items per batch (default: 80)")
        parser.add_argument("--max-batches", type=int, default=1, help="Max batches to run (default: 1)")
        parsed_args = parser.parse_args(sys.argv[2:])
        from src.batch_unliker_portable import run_batch_unliker_portable
        run_batch_unliker_portable(
            batch_size=parsed_args.batch_size,
            max_batches=parsed_args.max_batches,
        )
    else:
        print(f"Unknown command: {command}")
        print_help()
        sys.exit(1)


def print_help() -> None:
    print("""
ig_dislike – Instagram Reel Unlike Automation
==============================================

Usage:  python -m src.main <command> [options]

Commands:
  test_select  Run single non-destructive selection test (safe, 0 unlikes)
               Verifies Video card -> Toggle checkbox mapping and selection.

  unlike       Run batch unliker for Instagram Reels (default: 1 batch of 18)
               Options: --batch-size N (default 18), --max-batches M (default 1)

  batch        Alias for unlike (batch loop)
               Options: --batch-size N (default 18), --max-batches M (default 1)

  unlike-v2    Multi-load unliker; keeps selection mode active while scrolling
               Options: --batch-size N (default 80), --max-batches M (default 1)

  unlike-v3    Faster multi-load unliker with condition-based waits
               Options: --batch-size N (default 80), --max-batches M (default 1)

  unlike-v4    V2 workflow with faster selection timing
               Options: --batch-size N (default 80), --max-batches M (default 1)

  unlike-portable
               Portable V4 runner; auto-detects Firefox and creates a local profile
               Options: --batch-size N (default 80), --max-batches M (default 1)

  probe        Phase 1  – DOM discovery (read-only, safe)
  select       Phase 1b – Selection-mode probe (read-only, safe)
  load         Phase 1c – Pagination/loading probe (read-only, safe)
  detect       Phase 1d – Reel detection probe (read-only, safe)
""")


if __name__ == "__main__":
    main()
