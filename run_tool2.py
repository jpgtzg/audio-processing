"""PyInstaller entry point for the Tool 2 executable."""

import sys

from src.tool2 import main

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: tool2.exe <id_testigo_min>\n"
            "SEGMENTO_SARA is 100M+ rows -- a lower bound on ID_TESTIGO is required."
        )
    main(id_testigo_min=int(sys.argv[1]))
