import json
from pathlib import Path

from hub.main import app

root = Path(__file__).resolve().parents[1]
saved = json.loads((root / "packages/contracts/openapi.json").read_text(encoding="utf-8"))
if saved != app.openapi():
    raise SystemExit("OpenAPI snapshot is stale. Run python -m hub.export_contracts.")
print("OpenAPI contract snapshot matches the running application schema.")
