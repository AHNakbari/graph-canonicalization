"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import Config, ConfigError
from .jsonio import InputError

DEFAULT_CONFIG = Path("config/default.toml")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graphcanon",
        description="Canonicalize extracted entity occurrences and facts into a graph.",
    )
    parser.add_argument("--version", action="version", version=f"graphcanon {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG, help="TOML config file"
    )
    common.add_argument("--input-dir", type=Path, help="directory holding the four input files")

    run_parser = subparsers.add_parser(
        "run", parents=[common], help="full canonicalization run"
    )
    run_parser.add_argument("--output-dir", type=Path, help="where the six artifacts are written")
    run_parser.add_argument(
        "--possible-duplicate-pair-budget",
        type=int,
        help="cap on pairwise unresolved-duplicate rows (omit for full enumeration)",
    )
    run_parser.add_argument(
        "--merge-on-alias",
        action="store_true",
        default=None,
        help="honour alias assertions as merge evidence (measured to breach the "
        "hard-merge precision floor; for comparison runs only)",
    )
    run_parser.add_argument(
        "--labels",
        type=Path,
        default=Path("data/reference/public_labeled_pairs.jsonl"),
        help="labeled pairs to self-score against; skipped when absent. "
        "tools/score_public_pairs.py remains authoritative.",
    )
    run_parser.add_argument(
        "--no-labels",
        action="store_true",
        help="skip the in-run identity-quality diagnostic",
    )

    subparsers.add_parser("profile", parents=[common], help="summarise the input package")

    verify_parser = subparsers.add_parser(
        "verify",
        parents=[common],
        help="run the acceptance assertions (same checks as "
        "tools/validate_submission.py, without its per-row rescan)",
    )
    verify_parser.add_argument("--output-dir", type=Path, help="submission directory")

    config_parser = subparsers.add_parser(
        "config", parents=[common], help="show the resolved configuration"
    )
    config_parser.add_argument("--show", action="store_true", default=True)
    return parser


def _load_config(args: argparse.Namespace) -> Config:
    overrides = {
        key: getattr(args, key, None)
        for key in (
            "input_dir",
            "output_dir",
            "possible_duplicate_pair_budget",
            "merge_on_alias",
        )
    }
    if args.config.is_file():
        return Config.from_toml(args.config, **overrides)
    return Config(**{k: v for k, v in overrides.items() if v is not None})


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        config = _load_config(args)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.command == "config":
            print(json.dumps(config.describe(), indent=2, sort_keys=True))
            return 0

        if args.command == "profile":
            from .profiling import profile_input

            print(json.dumps(profile_input(config), indent=2, sort_keys=True))
            return 0

        if args.command == "verify":
            from .verify import VerificationError, verify

            try:
                result = verify(config.input_dir, config.output_dir)
            except VerificationError as exc:
                print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
                return 1
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0

        if args.command == "run":
            from .pipeline import run

            labels = None if args.no_labels else args.labels
            result = run(config, labels_path=labels)
            summary = {
                "status": "OK" if not result.violations else "INVARIANT_VIOLATIONS",
                "output_dir": str(result.output_dir),
                "counts": result.counts,
                "runtime": result.runtime,
                "output_sha256": result.hashes,
                "configuration_fingerprint": config.fingerprint(),
                "invariant_violations": result.violations,
            }
            if result.identity_quality:
                summary["identity_quality"] = {
                    "macro_f1": result.identity_quality["macro_f1"],
                    "hard_merge_precision": result.identity_quality[
                        "hard_merge_precision"
                    ],
                    "pass": result.identity_quality["pass"],
                }
            print(json.dumps(summary, indent=2, sort_keys=True))
            # Artifacts are still written for inspection, but a run that broke
            # an invariant must never exit 0 - `make accept` chains on it.
            return 0 if not result.violations else 5
    except InputError as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 3

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
