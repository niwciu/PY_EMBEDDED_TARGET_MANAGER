import argparse
import os
from typing import List, Optional

import yaml

from .config import create_required_directories, load_config, validate_config
from .discovery import discover_modules, resolve_module_paths
from .exceptions import TargetExecutionError
from .reporting import (
    generate_main_report,
    generate_missing_report_page,
    open_html_files_in_default_browser,
)
from .runner import discover_targets, run_make_targets
from .ui import ANSI_RED, bold, colorize, supports_ansi, TableProgress


def exit_with_error(message: str, exit_code: int = 2) -> None:
    if supports_ansi():
        print(colorize(bold(message), ANSI_RED))
    else:
        print(message)
    raise SystemExit(exit_code)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run module targets from a YAML configuration.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config.yaml",
        metavar="FILE",
        help=(
            "Path to YAML configuration file.\n"
            "(default: config.yaml)"
        ),
    )
    parser.add_argument(
        "-r",
        "--reconfigure",
        action="store_true",
        help="Remove existing 'out' directory and re-run CMake.",
    )
    parser.add_argument(
        "-k",
        "--keep-going",
        action="store_true",
        help="Continue executing remaining targets/modules even if a target fails.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show full command output and verbose informational messages.",
    )
    parser.add_argument(
        "-m",
        "--modules",
        nargs="+",
        metavar="MODULE",
        help=(
            "Run targets only for selected module(s).\n"
            "Provide one or more module names separated by spaces."
        ),
    )
    parser.add_argument(
        "-t",
        "--targets",
        nargs="+",
        metavar="TARGET",
        help=(
            "Run only selected target(s).\n"
            "Provide one or more target names separated by spaces."
        ),
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except (OSError, yaml.YAMLError) as exc:
        exit_with_error(f"Configuration error: failed to read/parse '{args.config}'.\n{exc}", exit_code=2)

    try:
        validate_config(config)
    except ValueError as exc:
        exit_with_error(f"Configuration error in '{args.config}':\n{exc}", exit_code=2)

    build_cfg = config["build"]
    build_system = build_cfg["system"]

    build_jobs = build_cfg.get("jobs")
    if build_system == "make" and build_jobs is None:
        build_jobs = os.cpu_count()
        if args.verbose:
            print(f"Auto-selected make jobs: -j{build_jobs}")

    resolved_paths = resolve_module_paths(config["module_paths"], args.config)
    try:
        modules = discover_modules(resolved_paths, verbose=args.verbose)
    except ValueError as exc:
        exit_with_error(f"Configuration error in '{args.config}':\n{exc}", exit_code=2)

    common_targets = [target.strip() for target in config.get("common_targets", [])]
    additional_targets = config.get("additional_targets") or {}
    excluded_targets = config.get("excluded_targets") or {}

    for module in modules:
        module_targets = discover_targets(
            module["path"],
            build_system,
            reconfigure=args.reconfigure,
            verbose=args.verbose,
        )
        available_set = set(module_targets)
        excluded = set(excluded_targets.get(module["name"], []) or [])
        additional = list(additional_targets.get(module["name"], []) or [])

        expected = [target for target in common_targets if target not in excluded]
        for target in additional:
            if target not in expected:
                expected.append(target)

        module["targets"] = expected
        module["available_targets"] = [target for target in expected if target in available_set]

    config["modules"] = modules

    create_required_directories(config, verbose=args.verbose)

    reports_to_open = []
    reports_to_show = config.get("reports_to_show", [])

    for report in reports_to_show:
        if report.lower() == "ccm":
            reports_to_open.append("../../reports/CCM/index.html")
        elif report.lower() == "ccr":
            reports_to_open.append("../../reports/CCR/JSON_ALL/HTML_OUT/project_coverage.html")
        else:
            if os.path.exists(report):
                reports_to_open.append(report)
            else:
                if args.verbose:
                    print(f"Report path not found: {report}")

    all_failed_targets = []

    modules_by_name = {m["name"]: m for m in config["modules"]}
    missing_selected_modules = []

    if args.modules:
        requested = args.modules
        missing_selected_modules = [name for name in requested if name not in modules_by_name]
        modules_to_run = [modules_by_name[name] for name in requested if name in modules_by_name]
    else:
        modules_to_run = config["modules"]

    missing_selected_targets = []
    if args.targets:
        requested_targets = args.targets

        all_known_targets = set()
        for module in config["modules"]:
            for target in module.get("targets", []):
                all_known_targets.add(target)

        missing_selected_targets = [target for target in requested_targets if target not in all_known_targets]
        requested_set = set([target for target in requested_targets if target in all_known_targets])

        for module in modules_to_run:
            original = module.get("targets", [])
            module["targets"] = [target for target in original if target in requested_set]
            available = module.get("available_targets", [])
            module["available_targets"] = [target for target in available if target in requested_set]

    progress = None
    if not args.verbose and supports_ansi():
        module_names = [module["name"] for module in modules_to_run]
        all_targets = []
        seen = set()
        for module in modules_to_run:
            for target in module["targets"]:
                if target not in seen:
                    seen.add(target)
                    all_targets.append(target)

        progress = TableProgress(
            module_names,
            all_targets,
            config_label=args.config,
            use_color=True,
            missing_symbol="-",
        )

        for module in modules_to_run:
            progress.mark_target_set_for_module(module["name"], module.get("available_targets", []))

        progress.draw()

    try:
        for module in modules_to_run:
            module_path = module["path"]
            if args.verbose:
                print(f"Module: {module_path}")

            if not module.get("available_targets"):
                continue

            failed_targets = run_make_targets(
                module_path,
                module["available_targets"],
                build_system,
                build_jobs,
                reconfigure=args.reconfigure,
                keep_going=args.keep_going,
                verbose=args.verbose,
                module_display_name=module["name"],
                progress_cb=(progress.update if progress else None),
            )
            all_failed_targets.extend(failed_targets)

    except TargetExecutionError as exc:
        msg = (
            "Execution stopped because a target failed and '--keep-going' was not set.\n"
            f"Failed target:\n"
            f"  module : {os.path.basename(exc.module_path.rstrip(os.sep))}\n"
            f"  target : {exc.target}\n"
            f"  exit   : {exc.returncode}"
        )
        exit_with_error(msg, exit_code=(exc.returncode if isinstance(exc.returncode, int) else 1))

    generate_missing_report_page(os.path.join("..", "..", "reports", "CCM"), "embedded-target-manager", verbose=args.verbose)
    generate_main_report(os.path.join("..", "..", "reports", "CCM"), args.config, "embedded-target-manager", verbose=args.verbose)

    if (not args.modules) and reports_to_open:
        open_html_files_in_default_browser(reports_to_open)

    if missing_selected_modules:
        for name in missing_selected_modules:
            print(f"Module '{name}' was not found in configuration file '{args.config}'.")

    if missing_selected_targets:
        for target in missing_selected_targets:
            print(f"Target '{target}' was not found in configuration file '{args.config}'.")

    if args.verbose and all_failed_targets:
        header = f"========== SUMMARY: FAILED TARGETS ({len(all_failed_targets)}) =========="
        print("\n" + colorize(bold(header), ANSI_RED))
        for idx, item in enumerate(all_failed_targets, start=1):
            line = f"{idx:>3}. module: {item['module_path']} | target: {item['target']} | exit: {item['returncode']}"
            print(colorize(line, ANSI_RED))
        print(colorize(bold("======================================================"), ANSI_RED) + "\n")

    if args.keep_going and all_failed_targets:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
