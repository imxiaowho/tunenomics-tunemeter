"""Aggregate metadata derived from the existing validated counter engine."""
from .engine import analysis_metadata


def aggregate(batch):
    return analysis_metadata(batch)
