from __future__ import annotations

import os
from typing import Any, Dict

import yaml

def load_config(yaml_file: str) -> Dict[str, Any]:
    with open(yaml_file, "r") as file:
        return yaml.safe_load(file)


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

    if "module_paths" not in config or not isinstance(config["module_paths"], list):
        raise ValueError("Missing 'module_paths' section or it is not a list.")

    for module_path in config["module_paths"]:
        if not isinstance(module_path, str) or not module_path.strip():
            raise ValueError("All entries in 'module_paths' must be non-empty strings.")

    if "common_targets" not in config or not isinstance(config["common_targets"], list):
        raise ValueError("Missing 'common_targets' or it is not a list.")

    for target in config["common_targets"]:
        if not isinstance(target, str) or not target.strip():
            raise ValueError("All entries in 'common_targets' must be non-empty strings.")

    if "additional_targets" in config and config["additional_targets"] is not None:
        if not isinstance(config["additional_targets"], dict):
            raise ValueError("'additional_targets' must be a mapping: { MODULE: [targets...] }")
        for module_name, targets in config["additional_targets"].items():
            if not isinstance(module_name, str) or not module_name.strip():
                raise ValueError("Keys in 'additional_targets' must be non-empty module names (strings).")
            if not isinstance(targets, list) or any((not isinstance(x, str) or not x.strip()) for x in targets):
                raise ValueError(f"'additional_targets.{module_name}' must be a list of non-empty strings.")

    if "excluded_targets" in config and config["excluded_targets"] is not None:
        if not isinstance(config["excluded_targets"], dict):
            raise ValueError("'excluded_targets' must be a mapping: { MODULE: [targets...] }")
        for module_name, targets in config["excluded_targets"].items():
            if not isinstance(module_name, str) or not module_name.strip():
                raise ValueError("Keys in 'excluded_targets' must be non-empty module names (strings).")
            if not isinstance(targets, list) or any((not isinstance(x, str) or not x.strip()) for x in targets):
                raise ValueError(f"'excluded_targets.{module_name}' must be a list of non-empty strings.")


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
