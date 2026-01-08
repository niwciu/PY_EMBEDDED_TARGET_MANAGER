import os
import re
import sys


ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"
ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_CYAN = "\033[36m"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def supports_ansi() -> bool:
    if not sys.stdout.isatty():
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return True


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


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


def clear_line() -> None:
    if supports_ansi():
        sys.stdout.write("\r\033[2K")
        sys.stdout.flush()


def print_inline_progress(line_text: str) -> None:
    if supports_ansi():
        clear_line()
        sys.stdout.write("\r" + line_text)
        sys.stdout.flush()
    else:
        print(line_text)


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
