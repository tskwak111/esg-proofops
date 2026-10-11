"""Lossless model selection projection; original candidate offsets stay server-side."""

PROFILE = "owned-cell-compact-i3-v1"
GUIDANCE = (
    "I3: parent_context_ids index candidate_contexts. These source-bound literal headers "
    "are interpretation context only; never borrow their numbers or years as claim facts. "
    "Select only the provided sentence_ids; do not create citations or grades."
)
POLICY = dict(
    profile=PROFILE,
    fields=["sentence_id", "text", "candidate_role", "row", "column"],
    parents="deduplicate-identical-literal-context; ordered-indexes; no-text-truncation",
    server="retain-full-candidate-offsets-source-ids-and-binding-metadata",
    model_parent_fields=["role", "text"],
    guidance=GUIDANCE,
)


def compact(data):
    contexts, entries = [], []
    for original in data["source_sentences"]:
        entry = {k: original[k] for k in POLICY["fields"] if k in original}
        parents = []
        for parent in original.get("parent_context", []):
            if parent not in contexts:
                contexts.append(parent)
            parents.append(contexts.index(parent))
        if parents:
            entry["parent_context_ids"] = parents
        entries.append(entry)
    return dict(
        data,
        source_sentences=entries,
        candidate_contexts=[{k: p[k] for k in POLICY["model_parent_fields"]} for p in contexts],
    )
