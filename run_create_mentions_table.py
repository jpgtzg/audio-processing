"""PyInstaller entry point for the MENCIONES_COMERCIALES create/migrate executable."""

from scripts.create_mentions_table import main

if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")
