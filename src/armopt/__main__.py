"""``python -m armopt`` launches the interactive menu. The benchmark CLI
and scheduler CLI keep their own entry points (``armopt``, ``armopt-select``,
or ``python -m armopt.cli`` / ``python -m armopt.select``) unchanged."""
from .menu import main

if __name__ == "__main__":
    raise SystemExit(main())
