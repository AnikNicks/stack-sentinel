"""Vector search over the policy corpus, using real chromadb (confirmed working in this
environment with its default local ONNX embedding model — no external API key needed;
PROGRESS.md documents this so the TF-IDF fallback described in the plan is not in use).

The policy corpus itself is fixed and versioned in policy/monitoring_escalation_policy.md —
nothing in the running system ever writes to it. Re-ingesting a real policy update would be a
deliberate, reviewed step (rerun ingest_policy_corpus explicitly), never a live
auto-updating index — the vector store integrity guardrail from the spec.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import chromadb

from pulse.paths import CHROMA_DIR, POLICY_DIR, POLICY_DOC_PATH

_COLLECTION_NAME = "monitoring_escalation_policy"
_client = None

COMPANY_POLICY_DIR = POLICY_DIR / "companies"


def _company_collection_name(company_id: str) -> str:
    return f"policy_{company_id}"


def company_policy_path(company_id: str) -> Path:
    return COMPANY_POLICY_DIR / f"{company_id}.md"


def _get_client():
    global _client
    if _client is None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _client


def _chunk_markdown(text: str) -> list[dict[str, str]]:
    """Chunk by section (## headers), one chunk per section — small enough corpus that
    section-level granularity is the right unit for a policy clause lookup."""
    sections = re.split(r"\n(?=## )", text.strip())
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        header_match = re.match(r"##\s*(.+)", section)
        title = header_match.group(1).strip() if header_match else "Preamble"
        chunks.append({"title": title, "text": section})
    return chunks


def ingest_policy_corpus(doc_path=None) -> int:
    """(Re-)ingest the fixed policy document into the collection. Idempotent: clears and
    re-adds every call, since the corpus is small and this is only ever run deliberately."""
    doc_path = doc_path or POLICY_DOC_PATH
    text = doc_path.read_text(encoding="utf-8")
    chunks = _chunk_markdown(text)

    client = _get_client()
    try:
        client.delete_collection(_COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(_COLLECTION_NAME)

    collection.add(
        documents=[c["text"] for c in chunks],
        metadatas=[{"title": c["title"]} for c in chunks],
        ids=[f"clause-{i}" for i in range(len(chunks))],
    )
    return len(chunks)


def search_policy(query: str, k: int = 3) -> list[dict[str, Any]]:
    """Semantic search over the shared, portfolio-wide policy corpus. Returns up to k matches
    with their clause title, text, and distance (lower = more relevant)."""
    client = _get_client()
    try:
        collection = client.get_collection(_COLLECTION_NAME)
    except Exception:
        ingest_policy_corpus()
        collection = client.get_collection(_COLLECTION_NAME)

    result = collection.query(query_texts=[query], n_results=k)
    matches = []
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    dists = result.get("distances", [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        matches.append({"title": meta.get("title"), "text": doc, "distance": dist})
    return matches


def ingest_company_policy_corpus(company_id: str, doc_path: Path | None = None) -> int:
    """(Re-)ingest one company's own policy document into its own collection — kept separate
    from the shared corpus (not metadata-filtered within it) so `search_company_policy` can
    never accidentally surface a clause written for a different company. Same idempotent
    clear-and-re-add contract as ingest_policy_corpus."""
    doc_path = doc_path or company_policy_path(company_id)
    text = doc_path.read_text(encoding="utf-8")
    chunks = _chunk_markdown(text)

    client = _get_client()
    collection_name = _company_collection_name(company_id)
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.create_collection(collection_name)

    collection.add(
        documents=[c["text"] for c in chunks],
        metadatas=[{"title": c["title"], "company_id": company_id} for c in chunks],
        ids=[f"clause-{i}" for i in range(len(chunks))],
    )
    return len(chunks)


def search_company_policy(company_id: str, query: str, k: int = 3) -> list[dict[str, Any]]:
    """Semantic search scoped to ONE company's own policy document — the monitoring system
    checking a company's own rules, the same discipline as goal-drift-tracker checking that
    company's own charter boundaries, just for policy text instead of behavior_incidents."""
    client = _get_client()
    collection_name = _company_collection_name(company_id)
    try:
        collection = client.get_collection(collection_name)
    except Exception:
        ingest_company_policy_corpus(company_id)
        collection = client.get_collection(collection_name)

    result = collection.query(query_texts=[query], n_results=k)
    matches = []
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    dists = result.get("distances", [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        matches.append({"title": meta.get("title"), "text": doc, "distance": dist})
    return matches
