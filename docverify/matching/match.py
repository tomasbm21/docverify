"""Shipment Matcher — clusters CanonicalDoc records into shipment groups.

OWNER: Agent 03 (Matching)
FROZEN signatures per CONTRACTS.md §5.

Algorithm:
  1. Normalize identifiers via utils.normalize_identifier (uppercase, strip separators).
  2. Build edges: two docs share an edge if they have the same normalized value
     in ANY of: bl_no, order_no, container_no, reference.
  3. Union-Find to compute connected components (= raw clusters).
  4. Fuzzy fallback: singleton docs get attracted to the most similar existing
     cluster via rapidfuzz on identifier strings (Levenshtein distance <= 2).
  5. Majority-vote grouping_key: most common normalized value per identifier field.
  6. Per-doc match_certainty: 1.0 if >= 2 strong identifiers match consensus,
     0.7 if exactly 1, 0.4 if fuzzy-only, 0.2 if singleton.
  7. Deterministic group_id: sort groups by consensus bl_no then order_no,
     assign G01..Gnn.
"""

from __future__ import annotations

from collections import Counter

from rapidfuzz import fuzz

from docverify.schemas.models import CanonicalDoc, ShipmentGroup
from docverify.utils import get_logger, normalize_identifier

logger = get_logger(__name__)

# Identifier fields to consider, in priority order.
_ID_FIELDS: tuple[str, ...] = ("bl_no", "order_no", "container_no", "reference")

# Fuzzy-match threshold (token_set_ratio, 0-100).  85 ~= Levenshtein <= 2 on
# typical identifier lengths.
_FUZZY_THRESHOLD = 85


# ── Union-Find ────────────────────────────────────────────────────────────────


class _UnionFind:
    """Weighted quick-union with path compression."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))
        self._rank = [0] * n

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_normalized_ids(doc: CanonicalDoc) -> dict[str, str]:
    """Return {field: normalized_value} for non-None identifier fields."""
    ids: dict[str, str] = {}
    for field in _ID_FIELDS:
        raw = getattr(doc.identifiers, field, None)
        norm = normalize_identifier(raw)
        if norm:
            ids[field] = norm
    return ids


def _majority_vote(
    docs: list[CanonicalDoc],
) -> dict[str, str]:
    """Return the most common normalized value for each identifier field."""
    counters: dict[str, Counter[str]] = {f: Counter() for f in _ID_FIELDS}
    for doc in docs:
        for field, norm in _extract_normalized_ids(doc).items():
            counters[field][norm] += 1
    result: dict[str, str] = {}
    for field, ctr in counters.items():
        if ctr:
            result[field] = ctr.most_common(1)[0][0]
    return result


def _certainty_for_doc(
    doc: CanonicalDoc,
    consensus: dict[str, str],
    cluster_size: int,
) -> float:
    """Score how well a doc matches the cluster consensus identifiers.

    A singleton cluster (no siblings to corroborate) always gets low certainty.
    """
    if cluster_size <= 1:
        return 0.2
    doc_ids = _extract_normalized_ids(doc)
    if not doc_ids:
        return 0.2
    matches = sum(
        1
        for f, v in doc_ids.items()
        if f in consensus and v == consensus[f]
    )
    if matches >= 2:
        return 1.0
    if matches == 1:
        return 0.7
    return 0.4  # fuzzy-only


def _sort_key_for_group(consensus: dict[str, str]) -> tuple[str, str]:
    """Deterministic sort key: bl_no first, then order_no."""
    return (consensus.get("bl_no", ""), consensus.get("order_no", ""))


# ── Core ──────────────────────────────────────────────────────────────────────


def match(docs: list[CanonicalDoc]) -> list[ShipmentGroup]:
    """Cluster documents into shipment groups using identifier overlap.

    Uses union-find on exact normalized identifier matches (bl_no, order_no,
    container_no, reference) as the primary signal, with rapidfuzz as a
    secondary fallback for singletons.
    """
    if not docs:
        return []

    n = len(docs)
    uf = _UnionFind(n)

    # ── Phase 1: exact-match edges ────────────────────────────────────────
    # For each identifier field, bucket docs by normalized value; union all
    # docs in the same bucket.
    for field in _ID_FIELDS:
        buckets: dict[str, list[int]] = {}
        for idx, doc in enumerate(docs):
            raw = getattr(doc.identifiers, field, None)
            norm = normalize_identifier(raw)
            if norm:
                buckets.setdefault(norm, []).append(idx)
        for indices in buckets.values():
            for i in range(1, len(indices)):
                uf.union(indices[0], indices[i])

    # ── Phase 2: collect raw clusters ─────────────────────────────────────
    cluster_map: dict[int, list[int]] = {}
    for idx in range(n):
        root = uf.find(idx)
        cluster_map.setdefault(root, []).append(idx)

    clusters: list[list[int]] = list(cluster_map.values())

    # ── Phase 3: fuzzy fallback for singletons ────────────────────────────
    # A singleton is a cluster of size 1 whose doc has NO exact-match edge.
    # Try to attract it to the most similar multi-doc cluster.
    multi_clusters = [c for c in clusters if len(c) > 1]
    singleton_clusters = [c for c in clusters if len(c) == 1]

    absorbed: set[int] = set()  # indices of singletons absorbed into a multi-cluster

    if multi_clusters and singleton_clusters:
        # Pre-compute all consensus identifiers for multi-clusters.
        mc_consensuses = [
            _majority_vote([docs[i] for i in mc]) for mc in multi_clusters
        ]

        for s_cluster in singleton_clusters:
            s_idx = s_cluster[0]
            s_ids = _extract_normalized_ids(docs[s_idx])
            if not s_ids:
                continue  # no identifiers at all → stays singleton

            best_score = 0.0
            best_mc_idx = -1

            for mc_idx, mc_consensus in enumerate(mc_consensuses):
                # Check if there's a near-miss on any identifier.
                for field, s_val in s_ids.items():
                    c_val = mc_consensus.get(field)
                    if c_val is None:
                        continue
                    score = fuzz.ratio(s_val, c_val) / 100.0
                    if score > best_score:
                        best_score = score
                        best_mc_idx = mc_idx

            if best_mc_idx >= 0 and best_score * 100 >= _FUZZY_THRESHOLD:
                target_root = multi_clusters[best_mc_idx][0]
                uf.union(s_idx, target_root)
                absorbed.add(s_idx)

    # ── Phase 4: re-collect clusters after fuzzy merging ───────────────────
    cluster_map2: dict[int, list[int]] = {}
    for idx in range(n):
        root = uf.find(idx)
        cluster_map2.setdefault(root, []).append(idx)

    final_clusters: list[list[int]] = list(cluster_map2.values())

    # ── Phase 5: build ShipmentGroups ─────────────────────────────────────
    groups_raw: list[tuple[dict[str, str], list[int]]] = []
    for cluster in final_clusters:
        cluster_docs = [docs[i] for i in cluster]
        consensus = _majority_vote(cluster_docs)
        groups_raw.append((consensus, cluster))

    # Sort deterministically by consensus identifiers.
    groups_raw.sort(key=lambda g: _sort_key_for_group(g[0]))

    result: list[ShipmentGroup] = []
    for rank, (consensus, indices) in enumerate(groups_raw, start=1):
        group_id = f"G{rank:02d}"
        doc_ids = [docs[i].doc_id for i in indices]
        certainty: dict[str, float] = {}
        for i in indices:
            doc = docs[i]
            cert = _certainty_for_doc(doc, consensus, len(indices))
            # If this doc was fuzzy-absorbed, cap certainty at 0.4.
            if i in absorbed:
                cert = min(cert, 0.4)
            certainty[doc.doc_id] = cert

        result.append(
            ShipmentGroup(
                group_id=group_id,
                doc_ids=doc_ids,
                grouping_key=consensus,
                match_certainty=certainty,
            )
        )

    return result


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Shipment matching stage")
    parser.add_argument(
        "--in-dir", default="data/out",
        help="Input directory containing canonical_docs.json (default: data/out)",
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help="Output JSON path (default: <in-dir>/groups.json)",
    )
    args = parser.parse_args()

    base = Path(args.in_dir)
    canonical_path = base / "canonical_docs.json"
    if not canonical_path.exists():
        print(f"Error: {canonical_path} not found. Run extraction first.", file=sys.stderr)
        sys.exit(1)

    raw = json.loads(canonical_path.read_text(encoding="utf-8"))
    docs_list = [CanonicalDoc.model_validate(item) for item in raw]
    groups = match(docs_list)

    out_path = Path(args.output) if args.output else base / "groups.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([g.model_dump(mode="json") for g in groups], indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(groups)} shipment groups to {out_path}")
