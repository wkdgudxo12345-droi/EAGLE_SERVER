from __future__ import annotations

from . import today100
from .whv_regions import regional_industry_postcode, remote_tourism_postcode


def main() -> int:
    # Replace the conservative bootstrap ranges with the exact official
    # Home Affairs postcode tables before any row is classified.
    today100._remote_tourism_postcode = remote_tourism_postcode
    today100._regional_industry_postcode = regional_industry_postcode
    return today100.main()


if __name__ == "__main__":
    raise SystemExit(main())
