"""PyInstaller entry point for the Tool 2 executable."""

import sys

from src.tool2.service import run

if __name__ == "__main__":
    run(sys.argv[1:])
