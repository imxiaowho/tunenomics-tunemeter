"""OMP assistant messages and independent model_usage side calls."""
from .base import ProviderSpec
from .pi import RULES, read_family

SPEC = ProviderSpec("omp", "message-sidecall-jsonl", "per_event", "per_event", RULES, event_kinds=("message", "model_usage"))


def read(path, issues):
    yield from read_family("omp", path, issues)
