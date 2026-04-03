"""
extract.py — Offline Knowledge Base Initialization
====================================================
Runs once. Processes all PDFs in files/ directory.
Outputs:
  - knowledge/vulcan.db       (SQLite — all structured data)
  - knowledge/images/         (PNG rasters of every page)
  - knowledge/index.faiss     (vector index for semantic search)
  - knowledge/index_map.json  (maps FAISS vector IDs → SQLite row IDs)

Usage:
  python extract.py
  python extract.py --docs files/owner-manual.pdf   # single doc
  python extract.py --verify-only                   # run validation only
"""

import os
import sys
import json
import sqlite3
import base64
import hashlib
import argparse
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import anthropic
import pdfplumber
import fitz  # pymupdf
import numpy as np
from PIL import Image
from tqdm import tqdm
from tenacity import retry, stop_after_attempt, wait_exponential
import faiss

# ─── Configuration ────────────────────────────────────────────────────────────

DOCS_DIR        = Path("files")
KNOWLEDGE_DIR   = Path("knowledge")
IMAGES_DIR      = KNOWLEDGE_DIR / "images"
DB_PATH         = KNOWLEDGE_DIR / "vulcan.db"
FAISS_PATH      = KNOWLEDGE_DIR / "index.faiss"
INDEX_MAP_PATH  = KNOWLEDGE_DIR / "index_map.json"

RASTER_DPI      = 200        # resolution for page rasterization
VISION_MODEL    = "claude-opus-4-6"   # use Opus for extraction quality
EMBED_MODEL     = "voyage-3-lite"  # Anthropic/Voyage via API
TEXT_MIN_CHARS  = 100        # minimum chars to consider pdfplumber output useful

# Documents to process (relative to DOCS_DIR)
DEFAULT_DOCS = [
    "selection-chart.pdf",
    "quick-start-guide.pdf",
    "owner-manual.pdf",
]

# ─── Validation test cases ─────────────────────────────────────────────────────
# These must pass before the script exits successfully.

VALIDATION_QUERIES = [
    {
        "id": "duty_cycle_mig_240v_200a",
        "description": "MIG duty cycle at 200A on 240V",
        "check": lambda db: _check_duty_cycle(db, "MIG", 240, 200, 25),
    },
    {
        "id": "tig_polarity_ground_socket",
        "description": "TIG polarity — ground clamp goes to positive socket",
        "check": lambda db: _check_polarity(db, "TIG", "positive"),
    },
    {
        "id": "porosity_flux_cored_causes",
        "description": "Porosity in flux-cored welds has at least 3 causes",
        "check": lambda db: _check_troubleshooting(db, "porosity", 3),
    },
    {
        "id": "wire_feed_tension_flux_cored",
        "description": "Flux-cored wire feed tension is 2-3",
        "check": lambda db: _check_text_contains(db, "tension", "flux-cored"),
    },
]


# ─── Database setup ────────────────────────────────────────────────────────────

def init_db(db_path: Path) -> sqlite3.Connection:
    """Create SQLite database with full schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        -- Core page records: both passes stored side by side
        CREATE TABLE IF NOT EXISTS pages (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_name            TEXT NOT NULL,
            page_number         INTEGER NOT NULL,
            image_path          TEXT,
            vision_json         TEXT,       -- full vision extraction as JSON
            vision_summary      TEXT,       -- short summary for FTS
            text_content        TEXT,       -- raw pdfplumber output
            questions_answered  TEXT,       -- JSON array from vision
            tags                TEXT,       -- JSON array from vision
            verification_status TEXT DEFAULT 'pending',
            numeric_conflicts   TEXT,       -- JSON array of {field, vision_val, text_val}
            confidence          REAL DEFAULT 1.0,
            created_at          TEXT,
            UNIQUE(doc_name, page_number)
        );

        -- Full-text search across all page content
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            doc_name,
            text_content,
            vision_summary,
            questions_answered,
            content='pages',
            content_rowid='id'
        );

        -- Triggers to keep FTS in sync
        CREATE TRIGGER IF NOT EXISTS pages_fts_insert
        AFTER INSERT ON pages BEGIN
            INSERT INTO pages_fts(rowid, doc_name, text_content, vision_summary, questions_answered)
            VALUES (new.id, new.doc_name, new.text_content, new.vision_summary, new.questions_answered);
        END;

        CREATE TRIGGER IF NOT EXISTS pages_fts_update
        AFTER UPDATE ON pages BEGIN
            UPDATE pages_fts
            SET doc_name=new.doc_name,
                text_content=new.text_content,
                vision_summary=new.vision_summary,
                questions_answered=new.questions_answered
            WHERE rowid=new.id;
        END;

        -- Structured knowledge: duty cycle
        CREATE TABLE IF NOT EXISTS duty_cycle (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            process         TEXT NOT NULL,
            voltage         INTEGER NOT NULL,
            rated_pct       INTEGER,
            rated_amps      INTEGER,
            continuous_pct  INTEGER,
            continuous_amps INTEGER,
            source_page     INTEGER,
            source_doc      TEXT,
            verified        INTEGER DEFAULT 0,
            UNIQUE(process, voltage)
        );

        -- Structured knowledge: polarity setup
        CREATE TABLE IF NOT EXISTS polarity_setup (
            process             TEXT PRIMARY KEY,
            ground_socket       TEXT,
            torch_socket        TEXT,
            wire_feed_socket    TEXT,
            gas_required        TEXT,
            gas_type            TEXT,
            polarity_type       TEXT,
            notes               TEXT,
            source_page         INTEGER,
            source_doc          TEXT,
            image_path          TEXT
        );

        -- Structured knowledge: troubleshooting
        CREATE TABLE IF NOT EXISTS troubleshooting (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symptom     TEXT NOT NULL,
            process     TEXT,
            causes      TEXT,       -- JSON array
            solutions   TEXT,       -- JSON array
            image_path  TEXT,
            source_page INTEGER,
            source_doc  TEXT
        );

        -- Image assets catalog
        CREATE TABLE IF NOT EXISTS image_assets (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            filename            TEXT UNIQUE,
            doc_name            TEXT,
            page_number         INTEGER,
            description         TEXT,
            tags                TEXT,   -- JSON array
            answers_questions   TEXT    -- JSON array
        );

        -- Selection chart data
        CREATE TABLE IF NOT EXISTS selection_chart (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_level     TEXT,
            material        TEXT,
            thickness_range TEXT,
            cleanliness     TEXT,
            recommended_process TEXT,
            gas_required    TEXT,
            notes           TEXT,
            source_page     INTEGER
        );

        -- Extraction run metadata
        CREATE TABLE IF NOT EXISTS extraction_runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at  TEXT,
            finished_at TEXT,
            doc_count   INTEGER,
            page_count  INTEGER,
            status      TEXT,
            notes       TEXT
        );
    """)
    conn.commit()
    print(f"  Database initialized: {db_path}")
    return conn


# ─── PDF rasterization ─────────────────────────────────────────────────────────

def rasterize_pdf(pdf_path: Path, dpi: int = RASTER_DPI) -> list[bytes]:
    """
    Rasterize every page of a PDF to PNG bytes.
    Returns list of PNG bytes, one per page.
    """
    doc = fitz.open(pdf_path)
    pages = []
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    for page in doc:
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        pages.append(pix.tobytes("png"))
    doc.close()
    return pages


def save_page_image(png_bytes: bytes, doc_name: str, page_number: int) -> Path:
    """Save PNG bytes to knowledge/images/<doc_name>/page_<N>.png"""
    doc_images_dir = IMAGES_DIR / doc_name
    doc_images_dir.mkdir(parents=True, exist_ok=True)
    image_path = doc_images_dir / f"page_{page_number:03d}.png"
    with open(image_path, "wb") as f:
        f.write(png_bytes)
    return image_path


# ─── Vision extraction ─────────────────────────────────────────────────────────

VISION_PROMPT = """You are extracting structured knowledge from a page of a technical product manual for the Vulcan OmniPro 220 multiprocess welder.

Analyze this page image carefully and return ONLY a valid JSON object with this exact schema. No preamble, no markdown, no explanation outside the JSON.

{
  "page_type": "<one of: cover, safety, specifications, controls, setup, operation, welding_tips, troubleshooting, maintenance, parts_diagram, wiring_schematic, selection_chart, warranty, other>",
  "summary": "<2-3 sentence description of what this page contains>",
  "text_content": "<all readable text on this page, preserving structure>",
  "tables": [
    {
      "title": "<table title or description>",
      "headers": ["<col1>", "<col2>", "..."],
      "rows": [["<val>", "<val>"], ["<val>", "<val>"]]
    }
  ],
  "diagrams": [
    {
      "description": "<detailed description of diagram, schematic, or photo>",
      "type": "<one of: wiring, polarity, setup, weld_diagnosis, parts, controls, safety, process_flow>",
      "key_elements": ["<element1>", "<element2>"]
    }
  ],
  "structured_facts": {
    "duty_cycles": [
      {"process": "", "voltage": 0, "rated_pct": 0, "rated_amps": 0, "continuous_pct": 0, "continuous_amps": 0}
    ],
    "polarity_setups": [
      {"process": "", "ground_socket": "", "torch_socket": "", "wire_feed_socket": "", "gas_type": "", "polarity_type": ""}
    ],
    "troubleshooting_entries": [
      {"symptom": "", "process": "", "causes": [], "solutions": []}
    ],
    "selection_chart_entries": [
      {"skill_level": "", "material": "", "thickness_range": "", "cleanliness": "", "recommended_process": "", "gas_required": ""}
    ]
  },
  "questions_answered": [
    "<plain-language question this page answers>",
    "<another question>"
  ],
  "tags": ["<keyword>", "<keyword>"]
}

Rules:
- For empty arrays/objects, use [] or {}
- For duty_cycles: only include if numeric values are visible on this page
- For polarity_setups: be precise — ground_socket and torch_socket must be exact (e.g. "positive (+)" or "negative (-)")
- For troubleshooting_entries: list ALL causes and solutions as separate array items
- questions_answered: phrase as natural user questions, 3-8 questions minimum if content is substantial
- tags: short keywords useful for search (e.g. "MIG", "duty cycle", "porosity", "wire feed")"""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def extract_via_vision(client: anthropic.Anthropic, png_bytes: bytes, doc_name: str, page_num: int) -> dict:
    """Send a page image to Claude vision and return structured JSON."""
    b64_image = base64.standard_b64encode(png_bytes).decode("utf-8")

    response = client.messages.create(
        model=VISION_MODEL,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": b64_image,
                    },
                },
                {
                    "type": "text",
                    "text": VISION_PROMPT,
                }
            ],
        }],
    )

    raw = response.content[0].text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"    [WARN] Vision JSON parse error on {doc_name} p.{page_num}: {e}")
        return {
            "page_type": "other",
            "summary": f"Parse error on {doc_name} page {page_num}",
            "text_content": raw[:2000],
            "tables": [], "diagrams": [], "structured_facts": {},
            "questions_answered": [], "tags": []
        }


# ─── Text extraction ───────────────────────────────────────────────────────────

def extract_via_pdfplumber(pdf_path: Path, page_index: int) -> str:
    """Extract raw text from a single page using pdfplumber. Returns empty string on failure."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_index >= len(pdf.pages):
                return ""
            page = pdf.pages[page_index]
            text = page.extract_text() or ""
            return text.strip()
    except Exception as e:
        print(f"    [WARN] pdfplumber failed on page {page_index}: {e}")
        return ""


# ─── Reconciliation ────────────────────────────────────────────────────────────

def reconcile(vision_result: dict, text_content: str) -> dict:
    """
    Compare vision and text outputs.
    - If text is sparse: mark vision-only, confidence 1.0
    - If text is substantial: cross-check numeric values
    - Flag conflicts rather than silently resolving them
    Returns enriched record with verification_status and numeric_conflicts.
    """
    conflicts = []
    is_text_rich = len(text_content.strip()) >= TEXT_MIN_CHARS

    if not is_text_rich:
        return {
            "verification_status": "vision-only",
            "numeric_conflicts": [],
            "confidence": 1.0,
        }

    # Extract numbers from vision text_content
    vision_text = vision_result.get("text_content", "")

    # Check duty cycle values specifically — these are safety-critical
    duty_cycles = vision_result.get("structured_facts", {}).get("duty_cycles", [])
    for dc in duty_cycles:
        for field in ["rated_pct", "rated_amps", "continuous_pct", "continuous_amps"]:
            val = dc.get(field)
            if val and str(val) not in text_content:
                conflicts.append({
                    "field": f"duty_cycle.{dc.get('process')}.{dc.get('voltage')}V.{field}",
                    "vision_value": val,
                    "note": "value not found in pdfplumber text — verify manually"
                })

    if conflicts:
        status = "discrepancy-flagged"
        confidence = 0.85
    else:
        status = "text-verified"
        confidence = 1.0

    return {
        "verification_status": status,
        "numeric_conflicts": conflicts,
        "confidence": confidence,
    }


# ─── Database writers ──────────────────────────────────────────────────────────

def upsert_page(conn: sqlite3.Connection, doc_name: str, page_number: int,
                image_path: Path, vision_result: dict, text_content: str,
                reconciliation: dict) -> int:
    """Insert or replace a page record. Returns the row ID."""
    cursor = conn.execute("""
        INSERT OR REPLACE INTO pages
        (doc_name, page_number, image_path, vision_json, vision_summary,
         text_content, questions_answered, tags,
         verification_status, numeric_conflicts, confidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        doc_name,
        page_number,
        str(image_path),
        json.dumps(vision_result),
        vision_result.get("summary", ""),
        text_content,
        json.dumps(vision_result.get("questions_answered", [])),
        json.dumps(vision_result.get("tags", [])),
        reconciliation["verification_status"],
        json.dumps(reconciliation["numeric_conflicts"]),
        reconciliation["confidence"],
        datetime.utcnow().isoformat(),
    ))
    conn.commit()
    return cursor.lastrowid


def write_structured_facts(conn: sqlite3.Connection, vision_result: dict,
                            doc_name: str, page_number: int):
    """Extract and write structured knowledge objects from vision output."""
    facts = vision_result.get("structured_facts", {})

    # Duty cycles
    for dc in facts.get("duty_cycles", []):
        if dc.get("process") and dc.get("voltage"):
            conn.execute("""
                INSERT OR REPLACE INTO duty_cycle
                (process, voltage, rated_pct, rated_amps, continuous_pct,
                 continuous_amps, source_page, source_doc, verified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                dc.get("process"), dc.get("voltage"),
                dc.get("rated_pct"), dc.get("rated_amps"),
                dc.get("continuous_pct"), dc.get("continuous_amps"),
                page_number, doc_name, 0
            ))

    # Polarity setups
    for ps in facts.get("polarity_setups", []):
        if ps.get("process"):
            conn.execute("""
                INSERT OR REPLACE INTO polarity_setup
                (process, ground_socket, torch_socket, wire_feed_socket,
                 gas_type, polarity_type, source_page, source_doc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ps.get("process"), ps.get("ground_socket"), ps.get("torch_socket"),
                ps.get("wire_feed_socket"), ps.get("gas_type"), ps.get("polarity_type"),
                page_number, doc_name
            ))

    # Troubleshooting entries
    for te in facts.get("troubleshooting_entries", []):
        if te.get("symptom"):
            conn.execute("""
                INSERT INTO troubleshooting
                (symptom, process, causes, solutions, source_page, source_doc)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                te.get("symptom"), te.get("process"),
                json.dumps(te.get("causes", [])),
                json.dumps(te.get("solutions", [])),
                page_number, doc_name
            ))

    # Selection chart entries
    for sc in facts.get("selection_chart_entries", []):
        if sc.get("recommended_process"):
            conn.execute("""
                INSERT INTO selection_chart
                (skill_level, material, thickness_range, cleanliness,
                 recommended_process, gas_required, source_page)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                sc.get("skill_level"), sc.get("material"),
                sc.get("thickness_range"), sc.get("cleanliness"),
                sc.get("recommended_process"), sc.get("gas_required"),
                page_number
            ))

    conn.commit()


def write_image_asset(conn: sqlite3.Connection, image_path: Path,
                      doc_name: str, page_number: int, vision_result: dict):
    """Catalog this page's image if it contains diagrams."""
    diagrams = vision_result.get("diagrams", [])
    if not diagrams:
        return

    description = "; ".join(d.get("description", "") for d in diagrams)
    tags = vision_result.get("tags", [])
    questions = vision_result.get("questions_answered", [])

    conn.execute("""
        INSERT OR REPLACE INTO image_assets
        (filename, doc_name, page_number, description, tags, answers_questions)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        image_path.name, doc_name, page_number,
        description,
        json.dumps(tags),
        json.dumps(questions)
    ))
    conn.commit()


# ─── FAISS index ───────────────────────────────────────────────────────────────

def build_faiss_index(conn: sqlite3.Connection, embed_client):
    """
    Build FAISS index from all page records.
    Embeds: vision_summary + questions_answered + text_content (truncated)
    Saves: knowledge/index.faiss + knowledge/index_map.json
    """
    print("\nBuilding FAISS vector index...")

    rows = conn.execute("""
        SELECT id, doc_name, page_number, vision_summary,
               questions_answered, text_content
        FROM pages
        ORDER BY id
    """).fetchall()

    if not rows:
        print("  No pages found — skipping FAISS build")
        return

    texts = []
    id_map = []  # maps FAISS index position → SQLite row id

    for row in rows:
        questions = json.loads(row["questions_answered"] or "[]")
        questions_text = " ".join(questions)
        text_snippet = (row["text_content"] or "")[:500]

        combined = f"{row['vision_summary']} {questions_text} {text_snippet}".strip()
        texts.append(combined)
        id_map.append(row["id"])

    print(f"  Embedding {len(texts)} pages via Voyage API...")
    all_embeddings = []
    batch_size = 10  # Voyage API batch limit
    for i in tqdm(range(0, len(texts), batch_size), desc="  Embedding batches"):
        batch = texts[i:i+batch_size]
        response = embed_client.embeddings.create(model=EMBED_MODEL, input=batch)
        for emb in response.embeddings:
            all_embeddings.append(emb.embedding)
    embeddings = np.array(all_embeddings, dtype=np.float32)
    # Normalize for cosine similarity
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / np.where(norms == 0, 1, norms)

    # Inner product index (works with normalized vectors = cosine similarity)
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(FAISS_PATH))

    with open(INDEX_MAP_PATH, "w") as f:
        json.dump(id_map, f)

    print(f"  FAISS index saved: {FAISS_PATH} ({len(texts)} vectors, dim={dim})")


# ─── Validation ────────────────────────────────────────────────────────────────

def _check_duty_cycle(conn, process, voltage, amps, expected_pct) -> tuple[bool, str]:
    row = conn.execute("""
        SELECT rated_pct FROM duty_cycle
        WHERE process=? AND voltage=? AND rated_amps=?
    """, (process, voltage, amps)).fetchone()
    if not row:
        return False, f"No duty cycle entry for {process} {voltage}V {amps}A"
    if row["rated_pct"] != expected_pct:
        return False, f"Expected {expected_pct}% but got {row['rated_pct']}%"
    return True, f"{process} {voltage}V {amps}A → {row['rated_pct']}% ✓"


def _check_polarity(conn, process, expected_socket_keyword) -> tuple[bool, str]:
    row = conn.execute("""
        SELECT ground_socket FROM polarity_setup WHERE process=?
    """, (process,)).fetchone()
    if not row:
        return False, f"No polarity entry for {process}"
    if expected_socket_keyword.lower() not in (row["ground_socket"] or "").lower():
        return False, f"{process} ground socket is '{row['ground_socket']}', expected '{expected_socket_keyword}'"
    return True, f"{process} ground → {row['ground_socket']} ✓"


def _check_troubleshooting(conn, symptom_keyword, min_causes) -> tuple[bool, str]:
    rows = conn.execute("""
        SELECT causes FROM troubleshooting
        WHERE symptom LIKE ?
    """, (f"%{symptom_keyword}%",)).fetchall()
    if not rows:
        return False, f"No troubleshooting entry matching '{symptom_keyword}'"
    total_causes = sum(len(json.loads(r["causes"] or "[]")) for r in rows)
    if total_causes < min_causes:
        return False, f"Only {total_causes} causes found for '{symptom_keyword}', expected {min_causes}+"
    return True, f"'{symptom_keyword}' → {total_causes} causes across {len(rows)} entries ✓"


def _check_text_contains(conn, keyword1, keyword2) -> tuple[bool, str]:
    row = conn.execute("""
        SELECT 1 FROM pages
        WHERE text_content LIKE ? AND text_content LIKE ?
        LIMIT 1
    """, (f"%{keyword1}%", f"%{keyword2}%")).fetchone()
    if row:
        return True, f"Found pages containing '{keyword1}' and '{keyword2}' ✓"
    return False, f"No page found containing both '{keyword1}' and '{keyword2}'"


def run_validation(conn: sqlite3.Connection) -> bool:
    print("\n" + "="*60)
    print("VALIDATION — 5 Hard Test Cases")
    print("="*60)

    all_passed = True
    for test in VALIDATION_QUERIES:
        passed, msg = test["check"](conn)
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  [{status}] {test['description']}")
        print(f"           {msg}")
        if not passed:
            all_passed = False

    print("="*60)
    if all_passed:
        print("All validation tests passed. Knowledge base is ready.")
    else:
        print("Some validation tests failed. Review extraction output above.")
    return all_passed


# ─── Main pipeline ─────────────────────────────────────────────────────────────

def process_document(pdf_path: Path, conn: sqlite3.Connection,
                     client: anthropic.Anthropic) -> int:
    """
    Full pipeline for one PDF:
      rasterize → vision pass → pdfplumber pass → reconcile → store
    Returns number of pages processed.
    """
    doc_name = pdf_path.stem  # e.g. "owner-manual"
    print(f"\nProcessing: {pdf_path.name}")

    print(f"  Rasterizing at {RASTER_DPI} DPI...")
    page_images = rasterize_pdf(pdf_path)
    print(f"  {len(page_images)} pages found")

    for i, png_bytes in enumerate(tqdm(page_images, desc=f"  {doc_name}", unit="page")):
        page_number = i + 1

        # Save image
        image_path = save_page_image(png_bytes, doc_name, page_number)

        # Pass 1: Vision
        vision_result = extract_via_vision(client, png_bytes, doc_name, page_number)
        time.sleep(0.5)  # gentle rate limiting

        # Pass 2: pdfplumber
        text_content = extract_via_pdfplumber(pdf_path, i)

        # Pass 3: Reconcile
        reconciliation = reconcile(vision_result, text_content)

        if reconciliation["numeric_conflicts"]:
            print(f"\n    [CONFLICT] {doc_name} p.{page_number}: {reconciliation['numeric_conflicts']}")

        # Write to DB
        row_id = upsert_page(conn, doc_name, page_number, image_path,
                             vision_result, text_content, reconciliation)

        write_structured_facts(conn, vision_result, doc_name, page_number)
        write_image_asset(conn, image_path, doc_name, page_number, vision_result)

    return len(page_images)


def main():
    parser = argparse.ArgumentParser(description="Build Vulcan OmniPro 220 knowledge base")
    parser.add_argument("--docs", nargs="+", help="Specific PDF paths to process")
    parser.add_argument("--verify-only", action="store_true", help="Skip extraction, run validation only")
    parser.add_argument("--skip-faiss", action="store_true", help="Skip FAISS index build")
    args = parser.parse_args()

    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and not args.verify_only:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)

    # Init
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    conn = init_db(DB_PATH)

    if args.verify_only:
        run_validation(conn)
        conn.close()
        return

    client = anthropic.Anthropic(api_key=api_key)

    # Determine which docs to process
    if args.docs:
        doc_paths = [Path(p) for p in args.docs]
    else:
        doc_paths = [DOCS_DIR / name for name in DEFAULT_DOCS]

    doc_paths = [p for p in doc_paths if p.exists()]
    if not doc_paths:
        print(f"No PDFs found in {DOCS_DIR}/")
        sys.exit(1)

    print(f"\nVulcan OmniPro 220 — Knowledge Base Extraction")
    print(f"Documents: {[p.name for p in doc_paths]}")
    print(f"Output:    {DB_PATH}")

    # Record run start
    run_id = conn.execute("""
        INSERT INTO extraction_runs (started_at, doc_count, status)
        VALUES (?, ?, ?)
    """, (datetime.utcnow().isoformat(), len(doc_paths), "running")).lastrowid
    conn.commit()

    total_pages = 0
    start_time = time.time()

    try:
        for pdf_path in doc_paths:
            pages = process_document(pdf_path, conn, client)
            total_pages += pages

        # Build FAISS index
        if not args.skip_faiss:
            print("\nInitializing embedding client...")
            embed_client = anthropic.Anthropic()
            build_faiss_index(conn, embed_client)

        # Update run record
        elapsed = time.time() - start_time
        conn.execute("""
            UPDATE extraction_runs
            SET finished_at=?, page_count=?, status=?, notes=?
            WHERE id=?
        """, (
            datetime.utcnow().isoformat(), total_pages, "complete",
            f"Completed in {elapsed:.1f}s", run_id
        ))
        conn.commit()

        print(f"\nExtraction complete: {total_pages} pages in {elapsed:.1f}s")

        # Validation
        passed = run_validation(conn)
        if not passed:
            print("\nWarning: Some validation tests failed. Check structured_facts extraction.")

    except KeyboardInterrupt:
        print("\nExtraction interrupted.")
        conn.execute("UPDATE extraction_runs SET status='interrupted' WHERE id=?", (run_id,))
        conn.commit()
    except Exception as e:
        print(f"\nExtraction failed: {e}")
        conn.execute("UPDATE extraction_runs SET status='failed', notes=? WHERE id=?",
                     (str(e), run_id))
        conn.commit()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()