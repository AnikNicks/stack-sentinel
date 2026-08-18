"""Reads the real data/portfolio_companies.json + data/layer_metrics/*.json (after a real
scripts/simulate_production_run.py run) and writes one JSON fixture per company into
companies/<company>/src/fixtures/cycles.json — the read-only data each company demo app's
"cycle replay" view is driven by. Never hand-authored separately from the real data; re-run
this after any change to the underlying scenario.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pulse.paths import COMPANIES_PATH, LAYER_METRICS_DIR, PROJECT_ROOT

COMPANY_DIRS = {
    "meridian": "meridian-labs",
    "wayfinder": "wayfinder-ai",
    "cascade": "cascade-analytics",
}


def main() -> None:
    with COMPANIES_PATH.open("r", encoding="utf-8") as f:
        companies = {c["company_id"]: c for c in json.load(f)["companies"]}

    for company_id, dir_name in COMPANY_DIRS.items():
        metrics_path = LAYER_METRICS_DIR / f"{company_id}.json"
        with metrics_path.open("r", encoding="utf-8") as f:
            layer_metrics = json.load(f)

        fixture = {
            "company": companies[company_id],
            "cycles": layer_metrics["cycles"],
        }

        out_dir = PROJECT_ROOT / "companies" / dir_name / "src" / "fixtures"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "cycles.json"
        out_path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
        print(f"wrote {out_path.relative_to(PROJECT_ROOT)} ({len(layer_metrics['cycles'])} cycles)")


if __name__ == "__main__":
    main()
