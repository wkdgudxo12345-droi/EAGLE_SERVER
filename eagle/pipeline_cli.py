from __future__ import annotations

import sys

from . import pipeline_loop


def main() -> int:
    """Run the Final DB loop with an explicit stderr dependency.

    Keeping the CLI boundary separate makes error reporting testable and prevents
    missing-token or missing-file paths from masking the real operational error.
    """

    pipeline_loop.sys = sys
    return pipeline_loop.run()


if __name__ == "__main__":
    raise SystemExit(main())
