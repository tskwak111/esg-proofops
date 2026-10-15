"""RB2 opt-in report-heading detection; native locators remain inspection-only."""

import json
import re
from pathlib import Path

from evaluation.reporting_period import ANCHOR, detect_reporting_period

PROFILE = "rb2-native-period-v1"
REPORT_ANCHOR = re.compile(
    r"보고서\s*기간(?:과\s*범위)?(?!\s*(?:동안|중|내|외))|" + ANCHOR.pattern,
    re.I,
)


def detect(texts, page_count, source_sha256):
    return detect_reporting_period(
        texts, page_count, source_sha256, _anchor=REPORT_ANCHOR, _version=PROFILE
    )


def configured_profile(config_path):
    """Scope inspection precedes a run; resolve its registered operator policy."""
    if not config_path:
        return None
    try:
        config = json.loads(Path(config_path).read_text())
    except (OSError, ValueError):
        return None
    pin = config.get("analysis_policy_sha256")
    from proofops.application.analysis_profile import V2_PROFILE, policy_for

    selected = policy_for(config.get("analysis_profile", V2_PROFILE), pinned_hash=pin)
    return selected.get("reporting_period_policy")
