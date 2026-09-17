import json
from pathlib import Path

from hub.main import app

if __name__ == "__main__":
    target = Path(__file__).resolve().parents[3] / "packages/contracts/openapi.json"
    target.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(target)
