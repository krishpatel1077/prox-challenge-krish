# Vulcan OmniPro 220 — Technical Expert Agent
## Architecture & System Design

---

## 1. The Problem

The Vulcan OmniPro 220 owner's manual is 48 pages of dense technical content. Critical information — polarity diagrams, weld diagnosis photos, duty cycle charts, wiring schematics — exists **only as images**. A naive text-extraction + RAG pipeline will fail on exactly the questions a real user needs answered most.

The system must:
- Answer deep technical questions accurately, including cross-referencing multiple sections
- Surface the actual manual images when they are the clearest answer
- Generate interactive visual output (calculators, diagrams, flowcharts) when text alone is insufficient
- Feel like a knowledgeable expert standing next to someone in their garage — not a search engine

---

## 2. Source Documents

| File | Pages | Content Type | Extraction Method |
|---|---|---|---|
| `owner-manual.pdf` | 48 | Mixed text + images | Text (specs/troubleshooting) + Vision (diagrams/photos) |
| `quick-start-guide.pdf` | 2 | Primarily images | Vision only |
| `selection-chart.pdf` | 1 | Pure image | Vision only |

**Critical image-only content:**
- Selection chart: 6-question decision tree → 4 welding processes
- Quick start page 2: Polarity diagrams for all 4 processes (Stick, MIG, Flux-Cored, TIG)
- Manual page 35–40: Wire/Stick weld diagnosis photos
- Manual page 45: Wiring schematic
- Manual pages 8–9: Labeled front panel + interior controls diagrams

---

## 3. Order of Operations

### Phase 0: Offline Knowledge Base Initialization
*Runs once. Output committed to repository. Never runs at query time.*

```
PDFs
  ↓
[Text Extraction Pass]
  → pdfplumber over owner manual
  → Extract: specs table (p.7), troubleshooting tables (p.42–44), welding tips text (p.34–40)
  → Output: structured JSON knowledge objects

[Vision Extraction Pass]
  → Rasterize all 8 critical pages at 200 DPI
  → Send each page image to Claude vision with targeted extraction prompt
  → Output: structured JSON + semantic image descriptions

[Knowledge Object Construction]
  → DutyCycleMatrix     (process × voltage × amperage → duty_cycle_percent)
  → PolaritySetup       (process → ground_socket, torch_socket, wire_feed_socket)
  → TroubleshootingEntry(symptom → causes[], solutions[])
  → WeldDiagnosisEntry  (visual_problem → causes[], corrections[], image_ref)
  → SelectionChart      (skill × material × thickness × cleanliness → recommended_process)
  → PartEntry           (part_number → name, description)
  → ImageAsset          (filename → description, tags[], answers_questions[])

[Vector Index Construction]
  → Embed all text chunks + image descriptions
  → Build FAISS index
  → Output: knowledge/index.faiss + knowledge/index.json

[Validation]
  → Run 3 hard test queries against knowledge base (no agent, raw retrieval)
  → Confirm: duty cycle at 200A/240V = 25%, TIG polarity correct, porosity causes correct
  → If any fail: fix extraction before proceeding
```

---

### Phase 1: Input Processing
*Runs at query time. Stateless.*

```
User Input (text or voice)
  ↓
[Input Classifier]
  → Detect question type:
      SPEC_LOOKUP     — "what's the duty cycle at 200A on 240V?"
      PROCESS_SETUP   — "how do I set up for TIG welding?"
      TROUBLESHOOT    — "I'm getting porosity in my flux-cored welds"
      SELECTION       — "what process should I use for thin aluminum?"
      GENERAL         — "how does this welder work?"
  → Detect if clarification needed:
      "I'm having problems welding" → agent should ask: which process? what symptom?

[Query Router]
  → SPEC_LOOKUP    → structured_lookup(DutyCycleMatrix | PolaritySetup)
  → TROUBLESHOOT   → hybrid_retrieval + structured_lookup(TroubleshootingEntry)
  → SELECTION      → structured_lookup(SelectionChart)
  → all types      → semantic_search(FAISS) for supporting context + image refs
```

---

### Phase 2: Agent Reasoning
*The core agentic loop.*

```
Classified Query + Retrieved Context
  ↓
[Claude Agent — System Prompt]
  Core instruction: You are a technical expert for the Vulcan OmniPro 220.
  Always consider: is a visual response clearer than a text response?
  Always cite: page number or section for every fact.
  Tone: knowledgeable neighbor in their garage, not a manual.

[Available Tools]
  search_knowledge(query: str) → chunks[] + image_refs[]
      Hybrid retrieval: FAISS semantic + keyword match
      Returns: text chunks, relevant image filenames, page numbers

  lookup_spec(type: str, params: dict) → exact_value
      Direct lookup against structured knowledge objects
      Examples:
        lookup_spec("duty_cycle", {process: "MIG", voltage: 240, amperage: 200})
        lookup_spec("polarity", {process: "TIG"})
        lookup_spec("troubleshoot", {symptom: "porosity", process: "flux-cored"})

  render_artifact(type: str, data: dict) → artifact_xml
      Instructs frontend to render a visual component
      Types:
        "polarity_diagram"      → SVG cable connection diagram
        "duty_cycle_table"      → Interactive table with process/voltage/amperage
        "settings_calculator"   → Input process+material+thickness → output settings
        "troubleshoot_flowchart"→ Mermaid decision tree for a symptom
        "surface_image"         → Show actual manual page image
        "weld_diagnosis_grid"   → Side-by-side weld photos with labels

[Reasoning Loop]
  1. Classify question type
  2. If SPEC: call lookup_spec first — exact answer before any generation
  3. Call search_knowledge — get supporting context + image refs
  4. Decide: is an artifact needed? (polarity? diagram? calculator?)
  5. If yes: call render_artifact with data from lookup + search
  6. Generate response: text answer + artifact tag(s) + citations
```

---

### Phase 3: Output Rendering
*Frontend parses agent response and renders multimodal output.*

```
Agent Response (streaming text + artifact XML tags)
  ↓
[Response Parser]
  → Split stream: text content vs <antArtifact> blocks
  → Text: render as markdown in chat panel
  → Artifacts: parse type + data → render component

[Artifact Renderer]
  antArtifact type="application/vnd.ant.react"
    → Mount React component inline (calculators, interactive diagrams)

  antArtifact type="image/surface"
    → Display actual manual image with caption + page number

  antArtifact type="application/vnd.ant.mermaid"
    → Render flowchart (troubleshooting decision trees)

  antArtifact type="text/html"
    → Render polarity diagrams as SVG
    → Render weld diagnosis grids

[Layout]
  Left panel:  Rendered artifact(s) — visual answer
  Right panel: Text explanation — the "why" behind the visual
  Below:       Source citations (page numbers, section names)
```

---

## 4. Full System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    OFFLINE (runs once)                           │
│                                                                  │
│  PDFs ──→ [Text Extractor] ──→ Structured JSON objects          │
│       └──→ [Vision Extractor] ──→ Image descriptions + assets   │
│                    ↓                                             │
│             [FAISS Index]  +  [knowledge/ directory]            │
└─────────────────────────────────────────────────────────────────┘
                         ↓ (committed to repo)
┌─────────────────────────────────────────────────────────────────┐
│                    RUNTIME (per query)                           │
│                                                                  │
│  User Input                                                      │
│      ↓                                                           │
│  [FastAPI /chat endpoint]                                        │
│      ↓                                                           │
│  [Input Classifier] ──→ question_type + needs_clarification      │
│      ↓                                                           │
│  [Claude Agent]                                                  │
│      ├── Tool: search_knowledge()  ──→ FAISS + keyword           │
│      ├── Tool: lookup_spec()       ──→ structured JSON objects   │
│      └── Tool: render_artifact()  ──→ artifact XML               │
│      ↓                                                           │
│  [Streaming Response] ──→ text + <antArtifact> tags              │
│      ↓                                                           │
│  [Frontend Parser]                                               │
│      ├── Text panel  ──→ markdown explanation + citations        │
│      └── Visual panel ──→ React | SVG | Mermaid | image          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Knowledge Object Schemas

```python
# Exact structured lookups — no RAG fuzziness for these

DutyCycleMatrix = {
  "MIG": {
    "120V": {"rated_pct": 40, "rated_A": 100, "continuous_pct": 100, "continuous_A": 75},
    "240V": {"rated_pct": 25, "rated_A": 200, "continuous_pct": 100, "continuous_A": 115}
  },
  "TIG": {
    "120V": {"rated_pct": 40, "rated_A": 125, "continuous_pct": 100, "continuous_A": 90},
    "240V": {"rated_pct": 30, "rated_A": 175, "continuous_pct": 100, "continuous_A": 105}
  },
  "Stick": {
    "120V": {"rated_pct": 40, "rated_A": 80,  "continuous_pct": 100, "continuous_A": 60},
    "240V": {"rated_pct": 25, "rated_A": 175, "continuous_pct": 100, "continuous_A": 100}
  }
}

PolaritySetup = {
  "MIG":        {"ground": "negative (-)", "wire_feed_power": "positive (+)", "gas": "required (C25)", "note": "DCEP"},
  "Flux-Cored": {"ground": "positive (+)", "wire_feed_power": "negative (-)", "gas": "not required",   "note": "DCEN"},
  "TIG":        {"ground": "positive (+)", "torch": "negative (-)",           "gas": "100% Argon",      "note": "DCEN, foot pedal inside"},
  "Stick":      {"ground": "negative (-)", "electrode_holder": "positive (+)","gas": "not required",    "note": "DCEP"}
}

TroubleshootingEntry = {
  "porosity_flux_cored": {
    "symptom": "Small cavities or holes in the bead",
    "causes": [
      "Incorrect polarity — should be DCEN for flux-cored",
      "Dirty workpiece or welding wire",
      "Inconsistent travel speed",
      "CTWD too long (keep under 1/2 inch)"
    ],
    "solutions": [...],
    "image_ref": "wire-weld-porosity.png",
    "page": 37
  }
}

ImageAsset = {
  "quick-start-p2-polarity.png": {
    "description": "Cable connection diagrams for all 4 welding processes",
    "tags": ["polarity", "cable", "setup", "MIG", "TIG", "Stick", "Flux-Cored"],
    "answers_questions": [
      "what polarity for TIG",
      "which socket does the ground clamp go in",
      "how do I connect cables for MIG welding"
    ],
    "page": "quick-start-guide p.2"
  }
}
```

---

## 6. Artifact Decision Logic

The agent uses this logic to decide when to render a visual vs. answer in text:

```
IF question involves cable connections or polarity
  → render_artifact("polarity_diagram")
  → surface_image(quick-start-p2-polarity.png)

IF question asks "what settings for [process] + [material] + [thickness]"
  → render_artifact("settings_calculator")

IF question is about a weld defect (porosity, spatter, burn-through, etc.)
  → surface_image(relevant weld diagnosis photo)
  → render_artifact("troubleshoot_flowchart")

IF question is about duty cycle
  → render_artifact("duty_cycle_table") with all values highlighted

IF question is about which process to use
  → render_artifact("selection_guide") walking through the 6 questions

IF question is about front panel controls or interior components
  → surface_image(manual-p8-front-panel.png or manual-p9-interior.png)

ELSE
  → Text answer with page citations
  → Surface image only if directly referenced
```

---

## 7. Frontend Structure

```
index.html  (single file)
│
├── Header: "Vulcan OmniPro 220 — Technical Expert"
│
├── Interactive Product Explorer (home state)
│   ├── product-inside.webp as base image
│   ├── Clickable hotspots on key components:
│   │     [Front Panel] [Wire Feed] [Power Sockets] [Gas Inlet] [LCD]
│   └── Clicking a hotspot → fires query → populates answer panels
│
├── Chat Interface
│   ├── Text input + voice toggle (Web Speech API)
│   └── Suggested questions (quick-access buttons)
│
├── Answer Layout (split view)
│   ├── Left:  Visual panel — artifact renders here
│   └── Right: Text panel — explanation + citations
│
└── Knowledge Status Bar
    └── Shows which documents are loaded, version, source page citations
```

---

## 8. What We Are NOT Building

- No user authentication
- No persistent conversation history (stateless per session is fine for a weekend)
- No voice output (text responses only, voice input optional)
- No fine-tuning (all intelligence from Claude + knowledge base)
- No external API calls beyond Anthropic

---

## 9. Validation Criteria

Before any frontend work begins, the knowledge base + agent must answer these correctly:

| Test Question | Expected Answer | Source |
|---|---|---|
| "Duty cycle MIG at 200A on 240V?" | 25% (2.5 min on, 7.5 min rest) | Manual p.7, p.19 |
| "TIG polarity — which socket for ground clamp?" | Positive (+) socket | QSG p.2, Manual p.24 |
| "Porosity in flux-cored welds — what to check?" | 6 causes incl. DCEN polarity, dirty wire, CTWD | Manual p.37, p.43 |
| "What process for thin aluminum sheet metal?" | MIG (with optional spool gun) | Selection chart |
| "Wire feed tension setting for flux-cored?" | 2–3 (less than solid wire to avoid crushing) | Manual p.15 |

All 5 must pass before the frontend is built.