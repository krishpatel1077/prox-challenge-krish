"""
retrieval.py — Query-time Knowledge Base Interface
====================================================
Wraps three retrieval paths against vulcan.db + index.faiss:
  1. semantic_search()    — FAISS vector search → page records
  2. fulltext_search()    — SQLite FTS5 keyword search → page records
  3. lookup_spec()        — Direct structured lookup → exact values

Used by agent.py as the implementation behind the agent's tools.
Call init_retrieval() once at server startup to load indexes into memory.
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional

import faiss
import numpy as np
import anthropic as _anthropic_embed

# ─── Paths ────────────────────────────────────────────────────────────────────

KNOWLEDGE_DIR  = Path("knowledge")
DB_PATH        = KNOWLEDGE_DIR / "vulcan.db"
FAISS_PATH     = KNOWLEDGE_DIR / "index.faiss"
INDEX_MAP_PATH = KNOWLEDGE_DIR / "index_map.json"
IMAGES_DIR     = KNOWLEDGE_DIR / "images"
EMBED_MODEL    = "voyage-3-lite"  # Anthropic/Voyage embedding model

# ─── Module-level singletons (loaded once at startup) ─────────────────────────

_db: Optional[sqlite3.Connection] = None
_faiss_index: Optional[faiss.Index] = None
_index_map: Optional[list[int]] = None
_embed_client: Optional[_anthropic_embed.Anthropic] = None


def init_retrieval():
    """
    Load all indexes into memory. Call once at server startup.
    Subsequent calls are no-ops.
    """
    global _db, _faiss_index, _index_map, _embedder

    if _db is not None:
        return  # already initialized

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Knowledge base not found at {DB_PATH}. "
            "Run extract.py first to build the knowledge base."
        )

    # SQLite
    _db = sqlite3.connect(DB_PATH, check_same_thread=False)
    _db.row_factory = sqlite3.Row

    # FAISS
    _faiss_index = faiss.read_index(str(FAISS_PATH))

    # ID map
    with open(INDEX_MAP_PATH) as f:
        _index_map = json.load(f)

    # Embedding client (Anthropic API)
    _embed_client = _anthropic_embed.Anthropic()

    print(f"Retrieval initialized: {_faiss_index.ntotal} vectors, {DB_PATH}")


def _get_db() -> sqlite3.Connection:
    if _db is None:
        raise RuntimeError("Call init_retrieval() before querying.")
    return _db


# ─── Result helpers ────────────────────────────────────────────────────────────

def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a SQLite Row to a clean dict, parsing JSON fields."""
    d = dict(row)
    for field in ("vision_json", "questions_answered", "tags", "numeric_conflicts"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def _image_url(image_path: str) -> str:
    """
    Convert a local image path to a URL path the frontend can load.
    e.g. knowledge/images/owner-manual/page_002.png
      -> /images/owner-manual/page_002.png
    """
    if not image_path:
        return ""
    p = Path(image_path)
    try:
        # Return path relative to knowledge/
        rel = p.relative_to(KNOWLEDGE_DIR)
        return f"/knowledge/{rel}"
    except ValueError:
        return image_path


# ─── 1. Semantic search ────────────────────────────────────────────────────────

def semantic_search(query: str, top_k: int = 5) -> list[dict]:
    """
    Embed the query and find the most semantically similar pages.

    Returns top_k page records from SQLite, ranked by cosine similarity.
    Each record includes the image URL and a similarity score.

    Use for: broad natural language questions where you don't know
    which specific page or section is relevant.
    """
    if _embed_client is None or _faiss_index is None:
        raise RuntimeError("Call init_retrieval() before querying.")

    # Embed using Anthropic/Voyage API
    response = _embed_client.embeddings.create(
        model=EMBED_MODEL,
        input=[query],
    )
    raw = np.array([response.embeddings[0].embedding], dtype=np.float32)
    # Normalize for cosine similarity
    norm = np.linalg.norm(raw, axis=1, keepdims=True)
    vec = raw / np.where(norm == 0, 1, norm)

    # Search — returns distances and positions in the FAISS index
    scores, positions = _faiss_index.search(vec, min(top_k, _faiss_index.ntotal))

    results = []
    db = _get_db()

    for score, pos in zip(scores[0], positions[0]):
        if pos < 0:
            continue  # FAISS returns -1 for empty slots

        row_id = _index_map[pos]
        row = db.execute(
            "SELECT * FROM pages WHERE id = ?", (row_id,)
        ).fetchone()

        if row:
            record = _row_to_dict(row)
            record["similarity_score"] = float(score)
            record["image_url"] = _image_url(record.get("image_path", ""))
            results.append(record)

    return results


# ─── 2. Full-text search ───────────────────────────────────────────────────────

def fulltext_search(query: str, top_k: int = 5) -> list[dict]:
    """
    Keyword search across all page content using SQLite FTS5.

    Returns top_k page records ranked by BM25 relevance.
    Faster than semantic search for specific terms, part numbers,
    technical jargon (e.g. "CTWD", "DCEN", "flux-cored porosity").

    Use for: specific technical terms, exact phrases, error codes.
    """
    db = _get_db()

    rows = db.execute("""
        SELECT p.*, rank
        FROM pages_fts
        JOIN pages p ON pages_fts.rowid = p.id
        WHERE pages_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """, (query, top_k)).fetchall()

    results = []
    for row in rows:
        record = _row_to_dict(row)
        record["image_url"] = _image_url(record.get("image_path", ""))
        results.append(record)

    return results


# ─── 3. Structured lookups ─────────────────────────────────────────────────────

def lookup_duty_cycle(process: str, voltage: Optional[int] = None) -> list[dict]:
    """
    Look up exact duty cycle specifications.

    Args:
        process: "MIG", "TIG", "Stick", or "Flux-Cored"
        voltage: 120 or 240 (optional — returns all voltages if omitted)

    Returns list of duty cycle records with rated and continuous values.

    Example:
        lookup_duty_cycle("MIG", 240)
        → [{"process": "MIG", "voltage": 240, "rated_pct": 25,
            "rated_amps": 200, "continuous_pct": 100, "continuous_amps": 115}]
    """
    db = _get_db()

    if voltage:
        rows = db.execute("""
            SELECT * FROM duty_cycle
            WHERE UPPER(process) = UPPER(?) AND voltage = ?
            ORDER BY voltage
        """, (process, voltage)).fetchall()
    else:
        rows = db.execute("""
            SELECT * FROM duty_cycle
            WHERE UPPER(process) = UPPER(?)
            ORDER BY voltage
        """, (process,)).fetchall()

    return [dict(r) for r in rows]


def lookup_polarity(process: str) -> Optional[dict]:
    """
    Look up exact cable polarity setup for a welding process.

    Args:
        process: "MIG", "TIG", "Stick", or "Flux-Cored"

    Returns polarity record with ground_socket, torch_socket,
    gas requirements, and the image path of the polarity diagram.

    Example:
        lookup_polarity("TIG")
        → {"process": "TIG", "ground_socket": "positive (+)",
           "torch_socket": "negative (-)", "gas_type": "100% Argon", ...}
    """
    db = _get_db()

    # Normalize common variants
    process_map = {
        "flux cored": "Flux-Cored",
        "flux-cored": "Flux-Cored",
        "fcaw": "Flux-Cored",
        "mig": "MIG",
        "gmaw": "MIG",
        "tig": "TIG",
        "gtaw": "TIG",
        "stick": "Stick",
        "smaw": "Stick",
    }
    normalized = process_map.get(process.lower(), process)

    row = db.execute("""
        SELECT ps.*, ia.filename as diagram_filename
        FROM polarity_setup ps
        LEFT JOIN image_assets ia ON ia.doc_name = 'quick-start-guide'
            AND ia.tags LIKE '%polarity%'
        WHERE UPPER(ps.process) = UPPER(?)
        LIMIT 1
    """, (normalized,)).fetchone()

    if not row:
        return None

    result = dict(row)
    # Attach the polarity diagram image URL
    if result.get("image_path"):
        result["image_url"] = _image_url(result["image_path"])
    else:
        # Fall back to QSG page 2 which has all polarity diagrams
        qsg_p2 = db.execute("""
            SELECT image_path FROM pages
            WHERE doc_name = 'quick-start-guide' AND page_number = 2
        """).fetchone()
        if qsg_p2:
            result["image_url"] = _image_url(qsg_p2["image_path"])

    return result


def lookup_troubleshooting(symptom: str, process: Optional[str] = None) -> list[dict]:
    """
    Look up troubleshooting entries by symptom description.

    Args:
        symptom: symptom keyword (e.g. "porosity", "spatter", "burn-through")
        process: optional process filter (e.g. "MIG", "Flux-Cored")

    Returns list of troubleshooting records with causes and solutions
    as parsed lists.

    Example:
        lookup_troubleshooting("porosity", "Flux-Cored")
        → [{"symptom": "Porosity in the Weld Metal",
            "causes": ["Incorrect polarity...", "Insufficient gas..."],
            "solutions": [...], "source_page": 37}]
    """
    db = _get_db()

    if process:
        rows = db.execute("""
            SELECT * FROM troubleshooting
            WHERE symptom LIKE ? AND (process LIKE ? OR process IS NULL)
            ORDER BY source_page
        """, (f"%{symptom}%", f"%{process}%")).fetchall()
    else:
        rows = db.execute("""
            SELECT * FROM troubleshooting
            WHERE symptom LIKE ?
            ORDER BY source_page
        """, (f"%{symptom}%",)).fetchall()

    results = []
    for row in rows:
        r = dict(row)
        r["causes"] = json.loads(r.get("causes") or "[]")
        r["solutions"] = json.loads(r.get("solutions") or "[]")
        # Attach weld diagnosis image if available
        if r.get("image_path"):
            r["image_url"] = _image_url(r["image_path"])
        results.append(r)

    return results


def lookup_selection(
    skill_level: Optional[str] = None,
    material: Optional[str] = None,
    thickness: Optional[str] = None,
    cleanliness: Optional[str] = None,
) -> list[dict]:
    """
    Look up recommended welding process from the selection chart.

    Args:
        skill_level: "low", "moderate", or "high"
        material: e.g. "steel", "aluminum", "stainless"
        thickness: e.g. "thin", "18 gauge", "1/4 inch"
        cleanliness: e.g. "clean", "rusty", "dirty"

    Returns matching selection chart entries with recommended process.

    Example:
        lookup_selection(material="aluminum", skill_level="moderate")
        → [{"recommended_process": "MIG", "gas_required": "Yes", ...}]
    """
    db = _get_db()

    conditions = []
    params = []

    if skill_level:
        conditions.append("LOWER(skill_level) LIKE ?")
        params.append(f"%{skill_level.lower()}%")
    if material:
        conditions.append("LOWER(material) LIKE ?")
        params.append(f"%{material.lower()}%")
    if thickness:
        conditions.append("LOWER(thickness_range) LIKE ?")
        params.append(f"%{thickness.lower()}%")
    if cleanliness:
        conditions.append("LOWER(cleanliness) LIKE ?")
        params.append(f"%{cleanliness.lower()}%")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = db.execute(
        f"SELECT * FROM selection_chart {where} ORDER BY id",
        params
    ).fetchall()

    return [dict(r) for r in rows]


def get_image_assets(tags: Optional[list[str]] = None, doc_name: Optional[str] = None) -> list[dict]:
    """
    Look up image assets by tag or document.

    Args:
        tags: list of tag keywords to match (e.g. ["polarity", "TIG"])
        doc_name: filter by document ("owner-manual", "quick-start-guide")

    Returns matching image asset records with URLs.

    Example:
        get_image_assets(tags=["polarity"])
        → [{"filename": "page_002.png", "doc_name": "quick-start-guide",
            "description": "...", "image_url": "/knowledge/images/..."}]
    """
    db = _get_db()

    conditions = []
    params = []

    if doc_name:
        conditions.append("doc_name = ?")
        params.append(doc_name)

    if tags:
        for tag in tags:
            conditions.append("tags LIKE ?")
            params.append(f"%{tag}%")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = db.execute(
        f"SELECT * FROM image_assets {where} ORDER BY page_number",
        params
    ).fetchall()

    results = []
    for row in rows:
        r = dict(row)
        r["tags"] = json.loads(r.get("tags") or "[]")
        r["answers_questions"] = json.loads(r.get("answers_questions") or "[]")
        # Build image URL from doc_name + filename
        img_path = IMAGES_DIR / r["doc_name"] / r["filename"]
        r["image_url"] = _image_url(str(img_path))
        results.append(r)

    return results


# ─── Hybrid search (combines semantic + fulltext) ──────────────────────────────

def hybrid_search(query: str, top_k: int = 5) -> list[dict]:
    """
    Combines semantic and full-text search, deduplicates, and re-ranks.

    Semantic search finds conceptually related pages even without
    exact keyword matches. Full-text search catches specific terms
    that semantic search might miss. Together they cover both cases.

    Returns top_k unique page records ranked by combined relevance.
    """
    semantic_results = semantic_search(query, top_k=top_k)
    fts_results = fulltext_search(query, top_k=top_k)

    # Deduplicate by page id, preferring semantic results
    seen_ids = set()
    combined = []

    for r in semantic_results:
        if r["id"] not in seen_ids:
            r["retrieval_method"] = "semantic"
            combined.append(r)
            seen_ids.add(r["id"])

    for r in fts_results:
        if r["id"] not in seen_ids:
            r["retrieval_method"] = "fulltext"
            combined.append(r)
            seen_ids.add(r["id"])

    return combined[:top_k]


# ─── Agent tool interface ──────────────────────────────────────────────────────
# These are the three functions the agent calls as tools.
# They wrap the lower-level functions above into clean,
# self-contained interfaces that return everything the agent needs
# to generate a response — text content, structured facts, and image URLs.

def tool_search_knowledge(query: str) -> dict:
    """
    Agent tool: search the knowledge base for relevant content.

    Runs hybrid search and returns page content, image references,
    and source citations ready for the agent to reason over.

    Args:
        query: natural language question or keyword search

    Returns dict with:
        - pages: list of relevant page records
        - images: list of relevant image assets
        - summary: brief description of what was found
    """
    pages = hybrid_search(query, top_k=4)

    # Also check image assets for visual content
    # Extract meaningful keywords from query for tag matching
    keywords = [w for w in query.lower().split()
                if len(w) > 3 and w not in ("what", "does", "how", "the", "for", "with")]
    images = get_image_assets(tags=keywords[:3]) if keywords else []

    return {
        "pages": pages,
        "images": images[:3],
        "summary": f"Found {len(pages)} relevant pages and {len(images)} images for: '{query}'"
    }


def tool_lookup_spec(spec_type: str, params: dict) -> dict:
    """
    Agent tool: direct structured lookup — no RAG, exact values.

    Args:
        spec_type: one of "duty_cycle", "polarity", "troubleshooting",
                   "selection", "images"
        params: lookup parameters specific to spec_type:
            duty_cycle:      {"process": "MIG", "voltage": 240}
            polarity:        {"process": "TIG"}
            troubleshooting: {"symptom": "porosity", "process": "Flux-Cored"}
            selection:       {"material": "aluminum", "skill_level": "moderate"}
            images:          {"tags": ["polarity"], "doc_name": "quick-start-guide"}

    Returns dict with "result" (the data) and "found" (bool).
    """
    spec_type = spec_type.lower().replace("-", "_").replace(" ", "_")

    if spec_type == "duty_cycle":
        result = lookup_duty_cycle(
            params.get("process", ""),
            params.get("voltage")
        )
        return {
            "found": bool(result),
            "result": result,
            "spec_type": "duty_cycle"
        }

    elif spec_type == "polarity":
        result = lookup_polarity(params.get("process", ""))
        return {
            "found": result is not None,
            "result": result,
            "spec_type": "polarity"
        }

    elif spec_type == "troubleshooting":
        result = lookup_troubleshooting(
            params.get("symptom", ""),
            params.get("process")
        )
        return {
            "found": bool(result),
            "result": result,
            "spec_type": "troubleshooting"
        }

    elif spec_type == "selection":
        result = lookup_selection(
            skill_level=params.get("skill_level"),
            material=params.get("material"),
            thickness=params.get("thickness"),
            cleanliness=params.get("cleanliness"),
        )
        return {
            "found": bool(result),
            "result": result,
            "spec_type": "selection"
        }

    elif spec_type == "images":
        result = get_image_assets(
            tags=params.get("tags"),
            doc_name=params.get("doc_name")
        )
        return {
            "found": bool(result),
            "result": result,
            "spec_type": "images"
        }

    else:
        return {
            "found": False,
            "result": None,
            "error": f"Unknown spec_type: {spec_type}. Use: duty_cycle, polarity, troubleshooting, selection, images"
        }


# ─── Quick test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("Initializing retrieval...")
    init_retrieval()

    print("\n--- Test 1: Duty cycle lookup ---")
    result = tool_lookup_spec("duty_cycle", {"process": "MIG", "voltage": 240})
    print(json.dumps(result, indent=2))

    print("\n--- Test 2: TIG polarity lookup ---")
    result = tool_lookup_spec("polarity", {"process": "TIG"})
    print(json.dumps(result, indent=2))

    print("\n--- Test 3: Troubleshooting porosity ---")
    result = tool_lookup_spec("troubleshooting", {"symptom": "porosity"})
    causes = result["result"][0]["causes"] if result["found"] else []
    print(f"Found: {result['found']}, Causes: {len(causes)}")
    for c in causes[:3]:
        print(f"  - {c}")

    print("\n--- Test 4: Semantic search ---")
    results = semantic_search("how do I set up TIG welding", top_k=3)
    for r in results:
        print(f"  p.{r['page_number']} ({r['doc_name']}) — score {r['similarity_score']:.3f}: {r['vision_summary'][:80]}")

    print("\n--- Test 5: Selection chart ---")
    result = tool_lookup_spec("selection", {"material": "aluminum"})
    print(json.dumps(result, indent=2))

    print("\nAll tests complete.")