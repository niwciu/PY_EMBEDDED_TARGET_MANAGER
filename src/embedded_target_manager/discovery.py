from __future__ import annotations

import os
from typing import Dict, Iterable, List


def resolve_module_paths(module_paths: Iterable[str], config_path: str) -> List[str]:
    base_dir = os.path.dirname(os.path.abspath(config_path))
    resolved = []
    for module_path in module_paths:
        expanded = os.path.expanduser(module_path)
        if os.path.isabs(expanded):
            resolved.append(os.path.abspath(expanded))
        else:
            resolved.append(os.path.abspath(os.path.join(base_dir, expanded)))
    return resolved


def discover_modules(module_paths: Iterable[str], verbose: bool = False) -> List[Dict[str, str]]:
    modules: List[Dict[str, str]] = []
    seen_names = set()

    for base_path in module_paths:
        if not os.path.isdir(base_path):
            raise ValueError(f"Module path does not exist or is not a directory: {base_path}")

        entries = sorted(os.listdir(base_path))
        for entry in entries:
            module_dir = os.path.join(base_path, entry)
            if not os.path.isdir(module_dir):
                continue

            cmake_file = os.path.join(module_dir, "CMakeLists.txt")
            if not os.path.isfile(cmake_file):
                continue

            if entry in seen_names:
                raise ValueError(f"Duplicate module name detected: '{entry}' in {base_path}")

            seen_names.add(entry)
            modules.append({"name": entry, "path": module_dir})

    if not modules:
        raise ValueError("No modules found. Ensure module paths contain subfolders with CMakeLists.txt.")

    if verbose:
        print(f"Discovered {len(modules)} module(s) from module_paths.")

    return modules
