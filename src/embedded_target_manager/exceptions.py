class TargetExecutionError(Exception):
    def __init__(self, module_path, target, returncode, cmd):
        super().__init__(f"Target '{target}' failed in '{module_path}' (exit={returncode})")
        self.module_path = module_path
        self.target = target
        self.returncode = returncode
        self.cmd = cmd
