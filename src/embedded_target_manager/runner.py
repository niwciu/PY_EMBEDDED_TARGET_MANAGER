import os
import shutil
import subprocess
from typing import Callable, List, Optional

from .exceptions import TargetExecutionError


ProgressCallback = Callable[[str, str, str], None]


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
