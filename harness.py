"""Compatibility entry point. Prefer python -m comparison.runner."""
from comparison.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
