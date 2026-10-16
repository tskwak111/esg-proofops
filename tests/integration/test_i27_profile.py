"""V27 integration preserves standalone pins and one source execution path."""

from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


def test_v27_composition_and_historical_pins():
    current = profiles.policy_for(
        profiles.V2_PROFILE,
        pinned_hash="fcd788f4c89034141c8767913f1c1acabdaefa1c8f543cdc5231903f05fa1804",
    )
    assert current == profiles.FINALS_I27_POLICY
    assert current == profiles.S5_LIVE_POLICY | dict(
        integration_profile="finals-20261016-v27",
        rb3_deadline=profiles.RB3_POLICY["rb3_deadline"],
        rb1_input_isolation=profiles.RB1_POLICY["rb1_input_isolation"],
        rb1_input_isolation_sha256=profiles.RB1_POLICY["rb1_input_isolation_sha256"],
        i27_sc1_optional_transient=profiles.I27_INVENTORY_POLICY,
        parser_output_policy="rb2-output-v1",
        reporting_period_policy="rb2-native-period-v1",
    )
    assert current["source"] == "s5_claim_source_v1"
    for policy, digest in (
        (
            profiles.FINALS_I27_PRE_RB2_POLICY,
            "708418f03dfe8a852b667790639029e3da9a1dabd218390b82a0a3d99b770d67",
        ),
        (
            profiles.RB2_POLICY,
            "96a26526bdd10b4cc4cd4d24b3d85f2ce83dfe4ceebf63b1bf8e2d3bc20de070",
        ),
        (
            profiles.FINALS_I26_POLICY,
            "ac9eb6466f3bdbc2653b140507a2ae2447ce008b4ec1dbb4de78cfb4e7d746fe",
        ),
        (
            profiles.S5_LIVE_POLICY,
            "26ab1a20cba362eb85d2031f2d44290f2dbc98fa0376e9eaa08890912d99ecd9",
        ),
        (profiles.RB3_POLICY, "609d137ce45a2613a6f4a3d3639cbe450d0de5aa231faa7e7bbd7de7cf3f5513"),
        (profiles.RB1_POLICY, "45d33f408ce854d18b78fe04ce415c8e7cd37b8fe9d305ddeab881b065fdd4c0"),
    ):
        assert canonical_hash(policy) == digest
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=digest) == policy
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=digest) == policy


def test_shared_dag_results_and_historical_reader_bytes():
    from pathlib import Path

    from proofops.adapters.local import (
        fxh_claim_source,
        rb3_policy_evaluation,
        s5_policy_evaluation,
    )

    # Both historical algorithms are identical; v27 selects only the S5 reader.
    assert (
        Path(rb3_policy_evaluation.__file__).read_bytes()
        == Path(s5_policy_evaluation.__file__).read_bytes()
    )
    assert (
        s5_policy_evaluation.evaluate(fxh_claim_source.claim_source_policy)
        == fxh_claim_source.claim_source_policy()
    )
