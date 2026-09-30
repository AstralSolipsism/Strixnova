"""Project the one source dependency lock into the packaged runtime contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "strixnova" / "src"))

from strixnova.storage_formats import ACTIVITY_FORMAT, AUTHORITY_FORMAT, EVIDENCE_FORMAT


def expected_bytes(root: Path = ROOT) -> bytes:
    content = (root / "strixnova" / "requirements-lock-win-py312.txt").read_text(encoding="utf-8").encode("utf-8")
    value = {
        "schema_version": "strixnova.runtime-compatibility.v1", "python": "3.12",
        "formats": {"authority": AUTHORITY_FORMAT, "delivery_activities": ACTIVITY_FORMAT, "evidence": EVIDENCE_FORMAT},
        "dependency_lock": {"sha256": hashlib.sha256(content).hexdigest(), "requirements": content.decode("utf-8")},
    }
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = ROOT / "strixnova/src/strixnova/resources/runtime-compatibility-v1.json"
    expected = expected_bytes()
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            print("runtime compatibility projection is stale", file=sys.stderr)
            return 1
    else:
        target.write_bytes(expected)
    print("runtime compatibility projection matches the source lock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
