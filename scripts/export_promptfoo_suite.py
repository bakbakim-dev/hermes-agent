"""Export the Hermes personal-ops promptfoo suite to a chosen directory.

This is intentionally runner-friendly: promptfoo does not need to run on the
Hermes VM. CI/local machines can export the deterministic suite, install
promptfoo on a larger runner, and validate or evaluate from there.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Hermes promptfoo config/cases.")
    parser.add_argument(
        "--out-dir",
        default=".promptfoo",
        help="Directory to receive promptfoo_config.json and promptfoo_eval_cases.json.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    os.environ["HERMES_HOME"] = str(out_dir)

    from plugins.personal_ops.promptfoo_suite import (
        build_promptfoo_config,
        builtin_common_sense_cases,
        dedupe_cases,
        write_promptfoo_suite,
    )

    evals_path = out_dir / "promptfoo_eval_cases.json"
    config_path = out_dir / "promptfoo_config.json"
    cases = dedupe_cases(builtin_common_sense_cases())
    config = build_promptfoo_config(tests=cases, evals_path=evals_path)
    result = write_promptfoo_suite(
        config=config,
        cases=cases,
        config_path=config_path,
        evals_path=evals_path,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
