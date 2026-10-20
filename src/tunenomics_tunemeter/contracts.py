"""Versioned, JSON-compatible contracts and bounded selected-file reads."""
from pathlib import Path
import json
from .engine import safe_path

LOCAL_SCHEMA = "tunemeter-usage/1.0.0"
SUBMISSION_SCHEMA = "tunemeter-submission/1.0.0"
ResultEnvelope = dict
MeasurementBatch = dict
ProbeResult = dict


def selected_file(path):
    path = Path(path).expanduser().absolute()
    if not all(safe_path(p) for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("Select an ordinary file; linked paths are not allowed")
    return path


def read_json(path, maximum=128 * 1024 * 1024):
    path = selected_file(path)
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Selected JSON exceeds the read limit")
    return json.loads(data.decode("utf-8-sig"))
