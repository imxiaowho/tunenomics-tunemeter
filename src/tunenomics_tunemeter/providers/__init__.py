"""Only registered provider modules can be loaded; never user module paths."""
from importlib import import_module

NAMES = ("codex", "claude", "pi", "omp", "gemini", "openclaw", "opencode", "qwen", "workbuddy")


def get(name):
    if name not in NAMES:
        raise ValueError("Unimplemented provider")
    return import_module(f"{__name__}.{name}")
