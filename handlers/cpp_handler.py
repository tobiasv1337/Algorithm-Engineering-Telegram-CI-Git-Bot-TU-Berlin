import subprocess
import os
from .base_handler import LanguageHandler, CompilationError, CompilationResult


class CppHandler(LanguageHandler):
    @staticmethod
    def compile(temp_dir):
        cmake_file = os.path.join(temp_dir, "CMakeLists.txt")
        if not os.path.isfile(cmake_file):
            raise CompilationError("CMakeLists.txt not found in the project directory.")

        # Step 1: Create a separate build directory for out-of-source builds
        build_dir = os.path.join(temp_dir, "build")
        os.makedirs(build_dir, exist_ok=True)

        # Step 2: Configure the build using CMake
        configure_cmd = ["cmake", ".."]
        configure_result = subprocess.run(
            configure_cmd, cwd=build_dir, capture_output=True, text=True
        )

        if configure_result.returncode != 0:
            raise CompilationError(f"CMake configuration failed:\n{configure_result.stderr}")

        # Step 3: Compile the project using CMake's build system
        compile_cmd = ["cmake", "--build", "."]
        compile_result = subprocess.run(
            compile_cmd, cwd=build_dir, capture_output=True, text=True
        )

        warnings = []
        if "warning" in compile_result.stderr.lower():
            warnings.append(compile_result.stderr)

        if compile_result.returncode != 0:
            raise CompilationError(f"Compilation failed:\n{compile_result.stderr}")

        return CompilationResult(warnings=warnings)
