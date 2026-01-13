import os
import re
import shutil
import subprocess
from typing import Callable, List, Optional

from .exceptions import TargetExecutionError


ProgressCallback = Callable[[str, str, str], None]


def configure_module(
    module_path: str,
    build_system: str,
    reconfigure: bool = False,
    verbose: bool = False,
) -> str:
    out_path = os.path.join(module_path, "out")

    if reconfigure and os.path.isdir(out_path):
        if verbose:
            print(f"[reconfigure] Removing existing 'out' directory in: {module_path}")
        shutil.rmtree(out_path)

    if not os.path.isdir(out_path):
        if verbose:
            print(f"Running CMake for module: {module_path}")

        if build_system == "ninja":
            generator = "Ninja"
        elif build_system == "make":
            generator = "Unix Makefiles"
        else:
            raise ValueError(f"Unknown build system: {build_system}")

        command = ["cmake", "-S", "./", "-B", "out", "-G", generator]

        if verbose:
            subprocess.run(command, cwd=module_path, check=True)
        else:
            subprocess.run(
                command,
                cwd=module_path,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )

    return out_path


def _extract_target_name(line: str) -> Optional[str]:
    stripped = line.strip()
    if not stripped:
        return None

    lowered = stripped.lower()
    if lowered.startswith(("the following", "built with", "targets:", "all primary")):
        return None

    for prefix in ("*", "-", "+"):
        if stripped.startswith(prefix):
            stripped = stripped[1:].lstrip()

    for sep in (":", " ("):
        if sep in stripped:
            stripped = stripped.split(sep, 1)[0].strip()

    token = stripped.split()[0] if stripped else ""
    if not token:
        return None

    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.+/\\-]*$", token):
        return None

    return token


def discover_targets(
    module_path: str,
    build_system: str,
    reconfigure: bool = False,
    verbose: bool = False,
) -> List[str]:
    out_path = configure_module(
        module_path,
        build_system,
        reconfigure=reconfigure,
        verbose=verbose,
    )

    command = ["cmake", "--build", out_path, "--target", "help"]
    result = subprocess.run(command, cwd=module_path, capture_output=True, text=True, check=False)
    output = (result.stdout or "") + (result.stderr or "")

    if result.returncode != 0:
        raise ValueError(f"Failed to discover targets for {module_path}.\n{output}")

    targets = []
    seen = set()
    for line in output.splitlines():
        target = _extract_target_name(line)
        if target and target not in seen:
            seen.add(target)
            targets.append(target)

    return targets


def run_make_targets(
    module_path: str,
    targets: List[str],
    build_system: str,
    build_jobs: Optional[int],
    reconfigure: bool = False,
    keep_going: bool = False,
    verbose: bool = False,
    module_display_name: Optional[str] = None,
    progress_cb: Optional[ProgressCallback] = None,
):
    out_path = configure_module(
        module_path,
        build_system,
        reconfigure=reconfigure,
        verbose=verbose,
    )

    failed_targets = []
    display_name = module_display_name if module_display_name else module_path

    for target in targets:
        if build_system == "make":
            cmd = ["make"]
            if build_jobs:
                cmd.append(f"-j{build_jobs}")
            cmd.append(target)
        elif build_system == "ninja":
            cmd = ["ninja", target]
        else:
            raise ValueError(f"Unknown build system: {build_system}")

        if progress_cb:
            progress_cb(display_name, target, "running")

        try:
            if verbose:
                subprocess.run(cmd, cwd=out_path, check=True)
            else:
                subprocess.run(
                    cmd,
                    cwd=out_path,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                )

            if progress_cb:
                progress_cb(display_name, target, "ok")

        except subprocess.CalledProcessError as exc:
            failed_targets.append(
                {
                    "module_path": module_path,
                    "target": target,
                    "returncode": exc.returncode,
                    "cmd": cmd,
                }
            )

            if progress_cb:
                progress_cb(display_name, target, "fail")

            if verbose:
                print(f"[FAIL] {module_path}: target '{target}' exited with code {exc.returncode}")

            if not keep_going:
                raise TargetExecutionError(module_path, target, exc.returncode, cmd) from None

    return failed_targets
