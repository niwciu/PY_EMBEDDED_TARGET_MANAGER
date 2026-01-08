from __future__ import annotations

import os
from typing import Any, Dict

import yaml

from .ui import ANSI_YELLOW, colorize, supports_ansi


def load_config(yaml_file: str) -> Dict[str, Any]:
    with open(yaml_file, "r") as file:
        return yaml.safe_load(file)


def _is_legacy_modules_schema(modules_value: Any) -> bool:
    return (
        isinstance(modules_value, list)
        and len(modules_value) > 0
        and isinstance(modules_value[0], dict)
        and ("name" in modules_value[0])
    )


def validate_config(config: Dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise ValueError("YAML root must be a mapping (dict).")

    if "build" not in config:
        raise ValueError("Missing required 'build' section in YAML.")

    build = config["build"]
    if not isinstance(build, dict):
        raise ValueError("'build' section must be a mapping (dict).")

    if "system" not in build:
        raise ValueError("Missing required 'build.system' (make | ninja).")

    if build["system"] not in ("make", "ninja"):
        raise ValueError("build.system must be either 'make' or 'ninja'.")

    if "jobs" in build and not isinstance(build["jobs"], int):
        raise ValueError("build.jobs must be an integer.")

    if "modules" not in config or not isinstance(config["modules"], list):
        raise ValueError("Missing 'modules' section or it is not a list.")

    modules_val = config["modules"]

    if _is_legacy_modules_schema(modules_val):
        for module in modules_val:
            if "name" not in module:
                raise ValueError("Each module must have a 'name'.")
            if "targets" not in module or not isinstance(module["targets"], list):
                raise ValueError(
                    f"Module {module.get('name', '<unknown>')} must have a list of 'targets'."
                )
        return

    for m in modules_val:
        if not isinstance(m, str) or not m.strip():
            raise ValueError("In the new schema, 'modules' must be a list of non-empty strings.")

    if "common_targets" not in config or not isinstance(config["common_targets"], list):
        raise ValueError("Missing 'common_targets' or it is not a list (new YAML schema).")

    for t in config["common_targets"]:
        if not isinstance(t, str) or not t.strip():
            raise ValueError("All entries in 'common_targets' must be non-empty strings.")

    if "additional_targets" in config and config["additional_targets"] is not None:
        if not isinstance(config["additional_targets"], dict):
            raise ValueError("'additional_targets' must be a mapping: { MODULE: [targets...] }")
        for mod, targets in config["additional_targets"].items():
            if not isinstance(mod, str) or not mod.strip():
                raise ValueError("Keys in 'additional_targets' must be non-empty module names (strings).")
            if not isinstance(targets, list) or any((not isinstance(x, str) or not x.strip()) for x in targets):
                raise ValueError(f"'additional_targets.{mod}' must be a list of non-empty strings.")

    if "excluded_targets" in config and config["excluded_targets"] is not None:
        if not isinstance(config["excluded_targets"], dict):
            raise ValueError("'excluded_targets' must be a mapping: { MODULE: [targets...] }")
        for mod, targets in config["excluded_targets"].items():
            if not isinstance(mod, str) or not mod.strip():
                raise ValueError("Keys in 'excluded_targets' must be non-empty module names (strings).")
            if not isinstance(targets, list) or any((not isinstance(x, str) or not x.strip()) for x in targets):
                raise ValueError(f"'excluded_targets.{mod}' must be a list of non-empty strings.")


def _warn(msg: str, verbose: bool) -> None:
    if not verbose:
        return
    if supports_ansi():
        print(colorize(f"WARNING: {msg}", ANSI_YELLOW))
    else:
        print(f"WARNING: {msg}")


def normalize_modules_config(config: Dict[str, Any], verbose: bool = False) -> Dict[str, Any]:
    modules_val = config.get("modules", [])

    if _is_legacy_modules_schema(modules_val):
        return config

    modules_list = [m.strip() for m in modules_val]
    modules_set = set(modules_list)

    common_targets = [t.strip() for t in config.get("common_targets", [])]
    common_set = set(common_targets)

    additional_targets = config.get("additional_targets") or {}
    excluded_targets = config.get("excluded_targets") or {}

    for mod in additional_targets.keys():
        if mod not in modules_set:
            raise ValueError(
                f"Invalid configuration: 'additional_targets' references module '{mod}' "
                f"which is not present in 'modules'."
            )
    for mod in excluded_targets.keys():
        if mod not in modules_set:
            raise ValueError(
                f"Invalid configuration: 'excluded_targets' references module '{mod}' "
                f"which is not present in 'modules'."
            )

    for mod, tlist in excluded_targets.items():
        for t in tlist:
            if t not in common_set:
                raise ValueError(
                    f"Invalid configuration: module '{mod}' excludes target '{t}', "
                    f"but '{t}' is not present in 'common_targets' (nothing to exclude)."
                )

    for mod in modules_list:
        add_set = set(additional_targets.get(mod, []) or [])
        exc_set = set(excluded_targets.get(mod, []) or [])
        overlap = sorted(add_set.intersection(exc_set))
        if overlap:
            raise ValueError(
                f"Invalid configuration: module '{mod}' has target(s) {overlap} in both "
                f"'additional_targets' and 'excluded_targets'. This is contradictory."
            )

    for mod, tlist in additional_targets.items():
        dup = sorted(set(tlist).intersection(common_set))
        if dup:
            _warn(
                f"Module '{mod}' has additional target(s) already present in common_targets: {dup}",
                verbose=verbose,
            )

    normalized_modules = []
    for mod in modules_list:
        exc = set(excluded_targets.get(mod, []) or [])
        add = list(additional_targets.get(mod, []) or [])

        base = [t for t in common_targets if t not in exc]
        final = base[:]

        seen = set(final)
        for t in add:
            if t not in seen:
                final.append(t)
                seen.add(t)

        normalized_modules.append({"name": mod, "targets": final})

    config["modules"] = normalized_modules
    return config


def create_required_directories(config: Dict[str, Any], verbose: bool = False) -> None:
    base_report_path = os.path.join("..", "..", "reports")
    ccm_path = os.path.join(base_report_path, "CCM")
    ccr_path = os.path.join(base_report_path, "CCR")
    json_all_path = os.path.join(ccr_path, "JSON_ALL")
    ccr_html_out_path = os.path.join(json_all_path, "HTML_OUT")

    os.makedirs(base_report_path, exist_ok=True)
    os.makedirs(ccm_path, exist_ok=True)
    os.makedirs(ccr_path, exist_ok=True)
    os.makedirs(json_all_path, exist_ok=True)
    os.makedirs(ccr_html_out_path, exist_ok=True)

    for module in config.get("modules", []):
        module_name = module["name"] if isinstance(module, dict) else str(module)
        module_path = os.path.join(ccr_path, module_name)
        os.makedirs(module_path, exist_ok=True)

    if verbose:
        print(f"Created/validated report directory structure at: {os.path.abspath(base_report_path)}")
