"""Compatibility entry point. Prefer python -m comparison.statistics."""
from comparison.statistics import main

if __name__ == "__main__":
    raise SystemExit(main())
