"""
server.py — FastAPI Server
===========================
Exposes the agent as a single streaming SSE endpoint.
Serves knowledge/images/ as static files for the frontend.

Endpoints:
  POST /chat          — stream agent response as SSE
  GET  /health        — health check
  GET  /knowledge/*   — static file serving for manual images

Deploy on Railway:
  railway up

Local dev:
  uvicorn server:app --reload --port 8000
"""

import json
import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from agent import init_agent, run_agent

load_dotenv()

# ─── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Vulcan OmniPro 220 — Technical Expert API",
    description="Multimodal agent for the Vulcan OmniPro 220 welder",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # tighten to your Vercel URL in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve manual page images so the frontend can render them
KNOWLEDGE_DIR = Path("knowledge")
if (KNOWLEDGE_DIR / "images").exists():
    app.mount(
        "/knowledge/images",
        StaticFiles(directory=str(KNOWLEDGE_DIR / "images")),
        name="knowledge-images",
    )


# ─── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_agent()
    print("Agent ready.")


# ─── Request / response models ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "product": "Vulcan OmniPro 220"}


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    Stream the agent response as Server-Sent Events.

    Each SSE event has the form:
      data: {"chunk": "<text or artifact XML>"}

    The final event is:
      data: [DONE]

    The frontend accumulates chunks, splits on <antArtifact> tags,
    and renders text and visual components side by side.
    """
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="question is required")

    async def event_stream():
        try:
            async for chunk in run_agent(req.question.strip()):
                if chunk:
                    payload = json.dumps({"chunk": chunk})
                    yield f"data: {payload}\n\n"
                    await asyncio.sleep(0)   # yield control to the event loop
        except Exception as e:
            error_payload = json.dumps({"error": str(e)})
            yield f"data: {error_payload}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",    # disables Nginx buffering on Railway
        },
    )