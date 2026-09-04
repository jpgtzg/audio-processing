"""PyInstaller entry point for the Tool 2 read-only dry-run executable."""

from scripts.tool2_test import main

if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")
