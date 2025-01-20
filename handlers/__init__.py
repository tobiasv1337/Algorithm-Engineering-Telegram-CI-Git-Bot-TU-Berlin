from .rust_handler import RustHandler
from .cpp_handler import CppHandler

LANGUAGE_HANDLERS = {
    "rust": RustHandler,
    "cpp": CppHandler,
}
