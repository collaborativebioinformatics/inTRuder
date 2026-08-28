"""Read a VCF and print the report, for checking this package against a real file.

    uv run python -m app.util.vcf ../data/sv_output/sniffles/raw/HG00290.raw.sniffles.vcf
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.util.vcf.scan import scan_vcf

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    target = Path(sys.argv[1]).resolve()
    print(json.dumps(scan_vcf(target, root=target.parent), indent=2, default=str))
