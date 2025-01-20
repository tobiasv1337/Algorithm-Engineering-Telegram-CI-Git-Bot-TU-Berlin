import subprocess
from .base_handler import LanguageHandler, CompilationError, CompilationResult


class RustHandler(LanguageHandler):
    @staticmethod
    def compile(temp_dir):
        cmd = ["cargo", "check"]
        result = subprocess.run(cmd, cwd=temp_dir, capture_output=True, text=True)

        warnings = []
        if "warning" in result.stderr.lower():
            warnings.append(result.stderr)

        if result.returncode != 0:
            raise CompilationError(result.stderr)

        return CompilationResult(warnings=warnings)
