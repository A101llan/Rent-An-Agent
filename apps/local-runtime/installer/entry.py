"""PyInstaller entry script."""
import multiprocessing
import sys

from app.service import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
