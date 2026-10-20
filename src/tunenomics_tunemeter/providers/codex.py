"""Contract boundary around the retained, undifferenced-again Codex engine."""
from ..codex import collect, doctor, probe
from .base import FieldRule, ProviderSpec
from ..engine import FIELDS

SPEC = ProviderSpec("codex", "rollout-jsonl", "cumulative_total", "increment",
                    tuple(FieldRule(field, (field,)) for field in FIELDS),
                    time_status="observed_intervals_only", service_tier_status="supported", event_kinds=("token_count",))
