"""PyInstaller entry point for the smoke-test executable."""

from scripts.smoke_test import main

if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")
