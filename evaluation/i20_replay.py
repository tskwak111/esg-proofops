"""V20 offline retained-selection projection; never fresh model votes or publication.

Historical selection IDs are resolved under their original contract first.
Prose selections then nominate intersecting v3 atoms in the new wire. Every atom
is a literal current-graph span. This measures deterministic extraction coverage,
not model response accuracy under the changed prompt.
"""

from dataclasses import asdict

from proofops.application.analysis_profile import FINALS_I20_POLICY
from proofops_agent.upstage_extraction import UpstageClaimExtractor as BaseExtractor


class SelectedReplay(BaseExtractor):
    def __init__(self, probe, path, **options):
        self._project_v20 = bool(options.get("extraction_located_table_context"))
        legacy = dict(options)
        legacy.pop("extraction_atomic_v3", None)
        legacy.pop("extraction_failure_diagnostics", None)
        self._historical_selector = BaseExtractor(probe, path / "historical-selector", **legacy)
        if self._project_v20:
            options.update(extraction_atomic_v3=True, extraction_failure_diagnostics=True)
        super().__init__(probe, path, **options)

    def _resolve_payload(
        self, payload, text, source_id, display_text=None, *, packet=None, context_graph=None
    ):
        if not self._project_v20 or packet["untrusted_document_data"]["kind"] != "paragraph":
            return super()._resolve_payload(
                payload, text, source_id, display_text, packet=packet, context_graph=context_graph
            )
        previous, _ = self._historical_selector._resolve_payload(
            payload, text, source_id, display_text, packet=packet, context_graph=context_graph
        )
        blocks = self._context_for(packet, context_graph)[0] if self._context else []
        entries = self._row_entries(packet, text, blocks, context_graph=context_graph)
        nominated = [
            f"c{index}" if self._i4_identity else entry["sentence_id"]
            for index, entry in enumerate(entries)
            if any(
                span.char_start < entry["char_end"]
                and entry["char_start"] < span.char_end
                and span.kind == "claim"
                for span in previous
            )
        ]
        spans, diagnostic = super()._resolve_payload(
            dict(sentence_ids=nominated),
            text,
            source_id,
            display_text,
            packet=packet,
            context_graph=context_graph,
        )
        diagnostic["retained_selection_projection"] = [asdict(s) for s in previous]
        return spans, diagnostic


def main():
    from evaluation import h1_replay, i1_replay, i10_replay

    i1_replay.UpstageClaimExtractor = SelectedReplay
    h1_replay.UpstageClaimExtractor = SelectedReplay
    i10_replay.FINALS_I10_POLICY = FINALS_I20_POLICY
    return i10_replay.main()


if __name__ == "__main__":
    main()
