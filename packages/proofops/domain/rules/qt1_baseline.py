"""DEC-93/AP-03's named scope; only trusted, verified maintenance-link facts use it."""

SOURCE_SCOPE = "qt1_maintenance_baseline_v1"
FACTS = frozenset(("target_metric", "baseline_year", "baseline_value"))
ENGINE_VERSION = "qt1-maintenance-baseline-dec93-v1"


def approved_fact(track, fact):
    return track == "goal" and fact.name in FACTS and fact.source_scope == SOURCE_SCOPE
