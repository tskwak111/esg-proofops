"""Bounded local BM25 evidence search over one immutable same-document graph.

Promoted from evaluation/section_pipeline.py without importing evaluation.
Lexical hits are candidate routes only; retrieval still rechecks sources,
quality, citation and binding. No grades, labels, or quality upgrades here.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from hashlib import sha256
from math import log1p

from proofops.application.evidence.retrieval import SearchHit, SearchResult, SearchScope
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.application.ingest.gri import _validate_graph

__all__ = ["LocalEvidenceSearch", "search_terms"]


def search_terms(text: str) -> list[str]:
    """Korean bigrams and whole Latin/numeric tokens, for routing only."""
    terms: list[str] = []
    for word in re.findall(r"[가-힣]+|[a-z]+|\d+(?:[.,]\d+)*", text.casefold()):
        if re.fullmatch(r"[가-힣]+", word):
            terms.extend(word[i : i + 2] for i in range(len(word) - 1))
        else:
            terms.append(word)
    return terms


class LocalEvidenceSearch:
    """Existing EvidenceSearchPort over one immutable same-document graph.

    Lexical hits are candidate routes only; retrieve_evidence still checks sources,
    quality, citation and binding. Empty pages are explicit zero coverage.
    """

    def __init__(
        self,
        graph: CanonicalDocumentGraph,
        *,
        tenant_id: str,
        pages: Iterable[int],
        index_generation: str,
    ) -> None:
        _validate_graph(graph, tenant_id)
        blocks = tuple(graph.blocks)
        if len({b.source_id for b in blocks}) != len(blocks):
            raise ValueError("duplicate canonical source_id")
        if isinstance(pages, str | bytes):
            raise ValueError("pages must be an iterable of positive integers")
        items = tuple(pages)
        for page in items:
            if type(page) is not int or page < 1:
                raise ValueError("pages must be positive integers")
        available = {b.page_num for b in blocks}
        if any(page not in available for page in items):
            raise ValueError("pages must occur in graph")
        self.graph = graph
        self.synthetic = any(batch.synthetic for batch in graph.candidates)
        self.scope = SearchScope(
            tenant_id,
            graph.document_version_id,
            graph.parse_manifest_id,
            index_generation,
        )
        self.pages = frozenset(items)
        self.documents = [
            (block, Counter(search_terms(block.normalized_text)))
            for block in blocks
            if block.page_num in self.pages and block.normalized_text.strip()
        ]
        self.frequencies = Counter(term for _, terms in self.documents for term in terms)
        self.average_length = sum(sum(c.values()) for _, c in self.documents) / max(
            1, len(self.documents)
        )

    def search(
        self, scope: SearchScope, query: str, *, vector: tuple[float, ...] | None = None
    ) -> SearchResult:
        if scope != self.scope:
            raise ValueError("local evidence search scope mismatch")
        if vector is not None:
            return SearchResult(status="not_run")
        terms = set(search_terms(query))
        # ponytail: local BM25 scan; Korean bigrams route candidates, not semantic bindings.
        ranked = []
        for block, counts in self.documents:
            length = sum(counts.values())
            score = sum(
                log1p(
                    (len(self.documents) - self.frequencies[t] + 0.5) / (self.frequencies[t] + 0.5)
                )
                * counts[t]
                * 2.2
                / (counts[t] + 1.2 * (0.25 + 0.75 * length / self.average_length))
                for t in sorted(terms & counts.keys())
            )
            if score:
                ranked.append((-score, block.source_id, block))
        ranked.sort(key=lambda item: item[:2])
        return SearchResult(
            tuple(
                SearchHit(scope, block.source_id, sha256(block.raw_text.encode()).hexdigest())
                for _, _, block in ranked[:20]
            ),
            "bounded",
        )
