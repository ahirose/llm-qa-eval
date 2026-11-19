"""Compatibility entry point. Prefer python -m answering.batch."""
from answering.batch import main

if __name__ == "__main__":
    raise SystemExit(main())
