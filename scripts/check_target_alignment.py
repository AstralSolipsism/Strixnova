"""Thin command entry for the current implementation-alignment candidate gate."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

from strixnova.project_implementation_alignment import (
    ProjectImplementationAlignment,
    ProjectImplementationAlignmentError,
)
from strixnova.implementation_observation import ExternalObservationProvider
from strixnova.project_authority_consistency import (
    ProjectAuthorityConsistency,
    ProjectAuthorityConsistencyError,
)


RESULT_SCHEMA = "strixnova.architecture-gate-result.v1"


def check_alignment(
    project_root: Path,
    mode: str,
    *,
    external_providers: Sequence[ExternalObservationProvider] = (),
    external_execution_authorized: bool = False,
) -> dict[str, object]:
    """Validate the working-tree candidate against the exact current HEAD."""

    try:
        consistency = ProjectAuthorityConsistency(project_root)
        consistency.load_working_tree_candidate(None)
        return consistency.alignment_drift(
            mode=mode,
            external_providers=external_providers,
            external_execution_authorized=external_execution_authorized,
        )
    except (
        ProjectAuthorityConsistencyError,
        ProjectImplementationAlignmentError,
    ) as error:
        return {
            "schema_version": RESULT_SCHEMA,
            "mode": mode,
            "passed": False,
            "counts": {},
            "failures": error.issues,
            "semantic_content_machine_proven": False,
        }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("daily", "stage"), default="daily")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).parents[1],
    )
    arguments = parser.parse_args()
    result = check_alignment(arguments.project_root, arguments.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
