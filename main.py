"""Compatibility entry point for GitHub Actions and local execution."""

from eagle.v4_main import main


if __name__ == "__main__":
    raise SystemExit(main())
