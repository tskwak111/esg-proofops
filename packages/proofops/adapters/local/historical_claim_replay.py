"""Isolated R24 replay with the byte-pinned validator before 934cf5f.

Current publication modules and their globals stay untouched. Re-execute the
unchanged wrapper bytes privately, then bind their historical dependencies as
in frozen_native_replay. The caller still checks the complete stored policy.
"""

from hashlib import sha256
from pathlib import Path

from proofops.adapters.local.frozen_native_replay import _exec_private

_ROOT = Path(__file__).parent
_PINNED = (
    (
        "_frozen_verifiers/claims_pre_continuations.py",
        "0cfaad53677b2f4b2b3687eb68ac1f162f6500027ca49ab21f96098adc5653e4",
    ),
    (
        "claim_source_verification.py",
        "8b95383c73d76b2bf838e51f208448c8b1995271a6639e5726df659e7cef2a61",
    ),
    (
        "claim_span_render_resolution.py",
        "48f24a69ec1061c4329510a993fd5c8a7a363489c74286df1ef4596614eb321b",
    ),
    (
        "claim_span_bullet_alignment.py",
        "b82a2023b0a42d3868fd21868fb3494c27a14f774a0479a3e20da6b1a1e4185d",
    ),
    (
        "_frozen_verifiers/claim_span_typography_v1.py",
        "58086038813acfca0e5d40108f7bf49863b11ecf5ceff56c91ca4989a82b98de",
    ),
)


def historical_typography_reader():
    for name, digest in _PINNED:
        path = _ROOT / name
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("CLAIM_SOURCE_POLICY_UNKNOWN")
    from proofops.adapters.local import claim_source_verification as current_base
    from proofops.adapters.local import claim_span_bullet_alignment as current_bullet
    from proofops.adapters.local._frozen_verifiers import claims_pre_continuations

    def load(name):
        return _exec_private(
            _ROOT, name + ".py", "proofops.adapters.local._historical." + Path(name).name
        )

    base = load("claim_source_verification")
    base.claim_validation = claims_pre_continuations
    # Preserve the established reader injection surface, including offline tests.
    base._rendered_text = current_base._rendered_text
    render = load("claim_span_render_resolution")
    render.base = base
    bullet = load("claim_span_bullet_alignment")
    bullet.base, bullet.baseline = base, render
    bullet._rendered_text = current_bullet._rendered_text
    typography = load("_frozen_verifiers/claim_span_typography_v1")
    typography.base, typography.baseline = base, bullet
    return typography
