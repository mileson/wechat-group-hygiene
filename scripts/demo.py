#!/usr/bin/env python3
"""Generate a local review page from exclusively fictional bundled data."""
from pathlib import Path
from render_review_workbench import render_html
import json

root = Path(__file__).resolve().parents[1]
payload = json.loads((root / "examples/analysis.json").read_text(encoding="utf-8"))
output = root / "examples/demo-workbench.html"
render_html(payload, output, payload["group_name"], "2026-01-01 至 2026-01-31", payload["chatroom_id"])
print(output)
