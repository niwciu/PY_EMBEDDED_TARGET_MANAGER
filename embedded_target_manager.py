import os
import subprocess
import yaml
import webbrowser
import argparse
import shutil
import sys
import re


ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"
ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_CYAN = "\033[36m"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class TargetExecutionError(Exception):
    def __init__(self, module_path, target, returncode, cmd):
        super().__init__(f"Target '{target}' failed in '{module_path}' (exit={returncode})")
        self.module_path = module_path
        self.target = target
        self.returncode = returncode
        self.cmd = cmd


def supports_ansi():
    if not sys.stdout.isatty():
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return True


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


def colorize(text: str, color: str) -> str:
    if supports_ansi():
        return f"{color}{text}{ANSI_RESET}"
    return text


def bold(text: str) -> str:
    if supports_ansi():
        return f"{ANSI_BOLD}{text}{ANSI_RESET}"
    return text


def dim(text: str) -> str:
    if supports_ansi():
        return f"{ANSI_DIM}{text}{ANSI_RESET}"
    return text


def clear_line():
    if supports_ansi():
        sys.stdout.write("\r\033[2K")
        sys.stdout.flush()


def print_inline_progress(line_text: str):
    if supports_ansi():
        clear_line()
        sys.stdout.write("\r" + line_text)
        sys.stdout.flush()
    else:
        print(line_text)


def exit_with_error(message: str, exit_code: int = 2):
    if supports_ansi():
        print(colorize(bold(message), ANSI_RED))
    else:
        print(message)
    raise SystemExit(exit_code)


class TableProgress:
    """
    Renders a live-updating ASCII table (modules x targets) in the terminal.
    Requires a TTY with ANSI support for live updates and colors.
    """

    def __init__(self, modules, all_targets, config_label, use_color=True, missing_symbol="-"):
        self.modules = modules
        self.targets = all_targets
        self.use_color = use_color and supports_ansi()
        self.config_label = config_label
        self.missing_symbol = missing_symbol

        self.module_col_w = max(len("MODULE"), max((len(m) for m in modules), default=6)) + 2
        self.target_col_w = {t: max(len(t), 4) + 2 for t in all_targets}

        self.status = {(m, t): "" for m in modules for t in all_targets}
        self._module_targets = {m: set() for m in modules}

    def mark_target_set_for_module(self, module, targets_for_module):
        self._module_targets[module] = set(targets_for_module)

    def _cell(self, text, width):
        visible_len = len(strip_ansi(text))
        if visible_len >= width:
            return text
        pad = width - visible_len
        left = pad // 2
        right = pad - left
        return (" " * left) + text + (" " * right)

    def _table_inner_width(self):
        return self.module_col_w + sum(1 + self.target_col_w[t] for t in self.targets)

    def _format_top_title_row(self):
        title = f"config: {self.config_label}"
        return "│" + self._cell(title, self._table_inner_width()) + "│"

    def _format_border_full(self, left, right, fill="─"):
        return left + (fill * self._table_inner_width()) + right

    def _format_border_columns(self, left, mid, right, fill="─"):
        line = left + (fill * self.module_col_w)
        for t in self.targets:
            line += mid + (fill * self.target_col_w[t])
        return line + right

    def _format_header(self):
        line = "│" + self._cell("MODULE", self.module_col_w)
        for t in self.targets:
            line += "│" + self._cell(t, self.target_col_w[t])
        return line + "│"

    def _format_row(self, module):
        line = "│" + module.ljust(self.module_col_w)
        for t in self.targets:
            line += "│" + self._cell(self.status[(module, t)], self.target_col_w[t])
        return line + "│"

    def draw(self):
        for m in self.modules:
            for t in self.targets:
                if t not in self._module_targets.get(m, set()):
                    self.status[(m, t)] = self.missing_symbol

        print(self._format_border_full("┌", "┐"))
        print(self._format_top_title_row())
        print(self._format_border_columns("├", "┬", "┤"))
        print(self._format_header())
        print(self._format_border_columns("├", "┼", "┤"))

        for m in self.modules:
            print(self._format_row(m))

        print(self._format_border_columns("└", "┴", "┘"))

    def update(self, module, target, state):
        if state == "running":
            sym = "▶"
            if self.use_color:
                sym = colorize(sym, ANSI_YELLOW)
        elif state == "ok":
            sym = "✔"
            if self.use_color:
                sym = colorize(sym, ANSI_GREEN)
        elif state == "fail":
            sym = "✖"
            if self.use_color:
                sym = colorize(sym, ANSI_RED)
        else:
            sym = str(state)

        self.status[(module, target)] = sym

        if not supports_ansi():
            return

        row_index = self.modules.index(module)
        lines_up = 1 + (len(self.modules) - row_index)

        sys.stdout.write("\0337")
        sys.stdout.write(f"\033[{lines_up}A")
        sys.stdout.write("\r\033[2K")
        sys.stdout.write(self._format_row(module))
        sys.stdout.write("\0338")
        sys.stdout.flush()


def load_config(yaml_file):
    with open(yaml_file, "r") as file:
        return yaml.safe_load(file)


def _is_legacy_modules_schema(modules_value):
    return (
        isinstance(modules_value, list)
        and len(modules_value) > 0
        and isinstance(modules_value[0], dict)
        and ("name" in modules_value[0])
    )


def validate_config(config):
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


def _warn(msg: str, verbose: bool):
    if not verbose:
        return
    if supports_ansi():
        print(colorize(f"WARNING: {msg}", ANSI_YELLOW))
    else:
        print(f"WARNING: {msg}")


def normalize_modules_config(config, verbose=False):
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


def create_required_directories(config, verbose=False):
    base_report_path = "../../reports"
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


def run_make_targets(
    module_path,
    targets,
    build_system,
    build_jobs,
    reconfigure=False,
    keep_going=False,
    verbose=False,
    module_display_name=None,
    progress_cb=None,
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

        except subprocess.CalledProcessError as e:
            failed_targets.append(
                {
                    "module_path": module_path,
                    "target": target,
                    "returncode": e.returncode,
                    "cmd": cmd,
                }
            )

            if progress_cb:
                progress_cb(display_name, target, "fail")

            if verbose:
                print(f"[FAIL] {module_path}: target '{target}' exited with code {e.returncode}")

            if not keep_going:
                raise TargetExecutionError(module_path, target, e.returncode, cmd) from None

    return failed_targets


def generate_missing_report_page(report_folder, verbose=False):
    missing_report_path = os.path.join(report_folder, "missing_report.html")

    if not os.path.exists(missing_report_path):
        with open(missing_report_path, "w", encoding="utf-8") as f:
            script_name = os.path.basename(__file__)
            f.write(
                f"""<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
 <head>
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
  <title>Missing Code Complexity Report</title>
  <style>
    body {{
        font-family: Arial, sans-serif;
        text-align: center;
        margin: 0;
        padding: 0;
    }}
    h2 {{
        margin-top: 20px;
    }}
    p {{
        font-size: 16px;
    }}
    footer {{
        margin-top: 20px;
        font-size: 12px;
        color: #555;
    }}
  </style>
 </head>
 <body>
    <h2>Missing Code Complexity Report for This Module</h2>
    <p>
        A Code Complexity Metrics (CCMR) report has not been generated for this module. Please check if the
        <strong>ccmr</strong> target is being executed for this module or if it is properly configured to generate the report.
    </p>
    <footer>
        Generated by {script_name} script configured with config.yaml
    </footer>
 </body>
</html>
"""
            )
        if verbose:
            print(f"Created missing report page: {missing_report_path}")
    else:
        if verbose:
            print(f"Missing report page already exists: {missing_report_path}")


def generate_main_report(report_folder, modules_yaml_file, verbose=False):
    with open(modules_yaml_file, "r") as yaml_file:
        config_data = yaml.safe_load(yaml_file)

    modules = config_data["modules"]
    main_report_path = os.path.join(report_folder, "index.html")

    with open(main_report_path, "w", encoding="utf-8") as f:
        f.write(
            """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
 <head>
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
  <title>Project Code Complexity Reports Main Page</title>
  <style>
    body {
        font-family: Arial, sans-serif;
        text-align: center;
        margin: 0;
        padding: 0;
    }
    h2 {
        margin-top: 20px;
    }
    ul {
        list-style-type: none;
        padding: 0;
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 10px;
        max-width: 80%;
        margin: 0 auto;
    }
    li {
        margin: 10px 0;
    }
    a {
        text-decoration: none;
    }
    .report-button {
        display: inline-block;
        padding: 15px 25px;
        margin: 5px;
        background-color: #007BFF;
        color: white;
        border: none;
        border-radius: 5px;
        cursor: pointer;
        width: 100%;
        text-align: center;
        font-size: 16px;
        box-sizing: border-box;
    }
    .report-button:hover {
        background-color: #0056b3;
    }
    .report-button-missing {
        background-color: #999;
    }
    .report-button-missing:hover {
        background-color: #777;
    }
    footer {
        margin-top: 20px;
        font-size: 12px;
        color: #555;
    }

    @media screen and (max-width: 1000px) {
        ul { grid-template-columns: repeat(3, 1fr); }
    }
    @media screen and (max-width: 600px) {
        ul { grid-template-columns: repeat(2, 1fr); }
    }
    @media screen and (max-width: 400px) {
        ul { grid-template-columns: 1fr; }
    }
  </style>
 </head>
 <body>
    <h2>Project Code Complexity Reports</h2>
    <ul>
"""
        )

        for module in modules:
            module_name = module["name"] if isinstance(module, dict) else str(module)

            report_file = f"{module_name}.html"
            file_path = os.path.join(report_folder, report_file)

            files_in_directory = os.listdir(report_folder)
            matching_files = [fn for fn in files_in_directory if fn.lower() == report_file.lower()]

            if matching_files:
                file_path = os.path.join(report_folder, matching_files[0])
                if verbose:
                    print(f"Found report for module: {module_name} -> {file_path}")
                f.write(
                    f'<li><a href="file://{os.path.abspath(file_path)}"><button class="report-button">{module_name}</button></a></li>\n'
                )
            else:
                if verbose:
                    print(f"Missing report for module: {module_name}")
                missing_report_path = "missing_report.html"
                f.write(
                    f'<li><a href="{missing_report_path}"><button class="report-button report-button-missing">{module_name}</button></a></li>\n'
                )

        script_name = os.path.basename(__file__)
        f.write(
            f"""    </ul>
    <footer>
        Generated by {script_name} script configured with config.yaml
    </footer>
 </body>
</html>
"""
        )

    if verbose:
        print(f"Wrote main report: {main_report_path}")


def open_html_files_in_default_browser(reports):
    for report in reports:
        try:
            webbrowser.open(f"file://{os.path.abspath(report)}", new=2)
        except Exception:
            pass


def main():
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
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (OSError, yaml.YAMLError) as e:
        exit_with_error(f"Configuration error: failed to read/parse '{args.config}'.\n{e}", exit_code=2)

    try:
        validate_config(config)
        config = normalize_modules_config(config, verbose=args.verbose)
    except ValueError as e:
        exit_with_error(f"Configuration error in '{args.config}':\n{e}", exit_code=2)

    build_cfg = config["build"]
    build_system = build_cfg["system"]

    build_jobs = build_cfg.get("jobs")
    if build_system == "make" and build_jobs is None:
        build_jobs = os.cpu_count()
        if args.verbose:
            print(f"Auto-selected make jobs: -j{build_jobs}")

    create_required_directories(config, verbose=args.verbose)

    test_folder = "../"

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
        for m in config["modules"]:
            for t in m.get("targets", []):
                all_known_targets.add(t)

        missing_selected_targets = [t for t in requested_targets if t not in all_known_targets]
        requested_set = set([t for t in requested_targets if t in all_known_targets])

        for m in modules_to_run:
            original = m.get("targets", [])
            m["targets"] = [t for t in original if t in requested_set]

    progress = None
    if not args.verbose and supports_ansi():
        module_names = [m["name"] for m in modules_to_run]
        all_targets = []
        seen = set()
        for m in modules_to_run:
            for t in m["targets"]:
                if t not in seen:
                    seen.add(t)
                    all_targets.append(t)

        progress = TableProgress(
            module_names,
            all_targets,
            config_label=args.config,
            use_color=True,
            missing_symbol="-",
        )

        for m in modules_to_run:
            progress.mark_target_set_for_module(m["name"], m.get("targets", []))

        progress.draw()

    try:
        for module in modules_to_run:
            module_path = os.path.join(test_folder, module["name"])
            if os.path.isdir(module_path):
                if args.verbose:
                    print(f"Module: {module_path}")

                if not module.get("targets"):
                    continue

                failed_targets = run_make_targets(
                    module_path,
                    module["targets"],
                    build_system,
                    build_jobs,
                    reconfigure=args.reconfigure,
                    keep_going=args.keep_going,
                    verbose=args.verbose,
                    module_display_name=module["name"],
                    progress_cb=(progress.update if progress else None),
                )
                all_failed_targets.extend(failed_targets)
            else:
                if args.verbose:
                    print(f"Module directory not found: {module_path}")

    except TargetExecutionError as e:
        msg = (
            "Execution stopped because a target failed and '--keep-going' was not set.\n"
            f"Failed target:\n"
            f"  module : {os.path.basename(e.module_path.rstrip(os.sep))}\n"
            f"  target : {e.target}\n"
            f"  exit   : {e.returncode}"
        )
        exit_with_error(msg, exit_code=(e.returncode if isinstance(e.returncode, int) else 1))

    generate_missing_report_page("../../reports/CCM", verbose=args.verbose)
    generate_main_report("../../reports/CCM", args.config, verbose=args.verbose)

    if (not args.modules) and reports_to_open:
        open_html_files_in_default_browser(reports_to_open)

    if missing_selected_modules:
        for name in missing_selected_modules:
            print(f"Module '{name}' was not found in configuration file '{args.config}'.")

    if missing_selected_targets:
        for t in missing_selected_targets:
            print(f"Target '{t}' was not found in configuration file '{args.config}'.")

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
