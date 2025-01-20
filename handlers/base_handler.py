from abc import ABC, abstractmethod


class CompilationResult:
    def __init__(self, warnings=None, errors=None):
        self.warnings = warnings or []
        self.errors = errors or []


class CompilationError(Exception):
    pass


class LanguageHandler(ABC):
    @staticmethod
    @abstractmethod
    def compile(temp_dir):
        """
        Perform a compilation check for the given project.
        Must return a CompilationResult or raise CompilationError.
        """
        pass
