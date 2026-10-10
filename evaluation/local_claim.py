"""Authenticated loopback text analysis using the shared OpenAI budget ledger."""

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

from proofops.adapters.parsing.openai_vision import MODEL, OpenAIVisionProbe


def run_local_claim(payload, *, key):
    path = Path(__file__).resolve().parents[1] / "api/live-claim.py"
    spec = importlib.util.spec_from_file_location("local_claim_engine", path)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    probe = OpenAIVisionProbe()
    probe.preflight(calls=4, input_tokens=12000)

    def model(system, user, max_tokens):
        # Independent requests must not collapse into a single cached tagging vote.
        result = probe.request(
            dict(
                model=MODEL,
                store=False,
                service_tier="default",
                max_output_tokens=max_tokens,
                reasoning={"effort": "none"},
                input=[
                    dict(
                        role="system",
                        content=system
                        + " Return a JSON object. "
                        + "Independent annotation id: "
                        + uuid4().hex,
                    ),
                    dict(role="user", content=json.dumps(user, ensure_ascii=False)),
                ],
                text={"format": {"type": "json_object"}},
            ),
            key,
        )
        usage = result["usage"]
        return dict(
            choices=[dict(message=dict(content=json.dumps(result["document"])))],
            usage=dict(
                prompt_tokens=usage["input_tokens"],
                completion_tokens=usage["output_tokens"],
                cost=float(usage["cost"]),
            ),
        )

    result = engine.run_claim(
        payload, access_code="loopback-authenticated", call_model=model, local_authorized=True
    )
    for step in result["steps"]:
        if "model" in step:
            step["model"] = MODEL
    return result
