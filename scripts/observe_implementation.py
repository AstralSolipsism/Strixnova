"""Developer-only read-only implementation-observation diagnostic."""

import argparse
import json
from pathlib import Path
import sys

import yaml

from strixnova.project_implementation_alignment import ProjectImplementationAlignment


def main(arguments: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--observed-ref")
    options = parser.parse_args(arguments)
    project_root = options.project_root.resolve()
    plan_path = (
        options.plan
        if options.plan.is_absolute()
        else project_root / options.plan
    ).resolve()
    value = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(
        value.get("observation_scopes"), list
    ):
        raise ValueError("观察计划必须包含 observation_scopes 数组")
    observed = ProjectImplementationAlignment.observe_normalized_snapshot(
        project_root,
        value["observation_scopes"],
        observed_ref=options.observed_ref,
    )
    print(json.dumps(observed, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
