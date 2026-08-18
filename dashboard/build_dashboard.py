"""Builds dashboard/dashboard.html by inlining the real data_snapshot.json into the
dashboard template. Run after scripts/export_dashboard_data.py. Keeps the HTML file itself
free of hand-typed numbers -- everything comes from the real snapshot on disk.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    snapshot_path = HERE / "data_snapshot.json"
    template_path = HERE / "dashboard_template.html"
    out_path = HERE / "dashboard.html"

    snapshot_json = snapshot_path.read_text(encoding="utf-8")
    template = template_path.read_text(encoding="utf-8")

    if "__PULSE_DATA_SNAPSHOT__" not in template:
        sys.exit("template is missing the __PULSE_DATA_SNAPSHOT__ placeholder")

    out = template.replace("__PULSE_DATA_SNAPSHOT__", snapshot_json)
    out_path.write_text(out, encoding="utf-8")
    print(f"Wrote {out_path} ({len(out):,} bytes)")


if __name__ == "__main__":
    main()
