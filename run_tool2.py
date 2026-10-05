"""PyInstaller entry point for the Tool 2 executable."""

import argparse

from src.tool2.service import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tool 2: brand-mention detection service")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="write results (and a placeholder row for segments with no mentions) to the test database instead of production",
    )
    args = parser.parse_args()
    run(debug=args.debug)
