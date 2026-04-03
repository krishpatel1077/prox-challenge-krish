"""
agent.py — Vulcan OmniPro 220 Technical Expert Agent
======================================================
Uses the Claude Agent SDK with two custom in-process MCP tools:
  - search_knowledge: hybrid semantic + FTS retrieval
  - lookup_spec: direct structured lookups (duty cycle, polarity, etc.)

The agent generates <antArtifact> XML tags in its responses which
the frontend parses and renders as interactive visual components.

Usage:
  from agent import run_agent
  async for chunk in run_agent("what polarity for TIG welding?"):
      print(chunk, end="", flush=True)
"""

import json
import asyncio
from typing import AsyncIterator, Any

from claude_agent_sdk import (
    tool,
    create_sdk_mcp_server,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    AssistantMessage,
    TextBlock,
)
from dotenv import load_dotenv

from retrieval import init_retrieval, tool_search_knowledge, tool_lookup_spec

load_dotenv()

# ─── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the technical expert for the Vulcan OmniPro 220 multiprocess welder.
You have deep knowledge of this specific machine: its MIG, Flux-Cored, TIG, and Stick welding processes, duty cycles, polarity setups, wire feed mechanisms, troubleshooting, and weld diagnosis.

Your user just bought this welder and is standing in their garage. They are not a professional welder but they are not an idiot. Be direct, practical, and precise. Never be vague when you have exact data.

TOOLS:
- search_knowledge: use for broad questions, setup instructions, welding tips, maintenance
- lookup_spec: use for exact values — duty cycles, polarity setups, troubleshooting entries, process selection

ALWAYS use a tool before answering. Never answer from memory alone — always ground your answer in retrieved knowledge.

MULTIMODAL OUTPUT — CRITICAL:
When your answer involves any of the following, you MUST generate an artifact:
- Cable connections or polarity setup → generate a polarity diagram
- Duty cycle information → generate an interactive duty cycle table
- Troubleshooting a weld defect → surface the weld diagnosis image AND generate a flowchart
- Choosing a welding process → generate a process selector widget
- Settings for a specific process/material/thickness → generate a settings calculator
- Any front panel or control question → surface the relevant manual page image

Generate artifacts using this exact XML format (the frontend will render them):

For a React interactive component:
<antArtifact identifier="unique-id" type="application/vnd.ant.react" title="Component Title">
// React component code here
</antArtifact>

For an SVG diagram:
<antArtifact identifier="unique-id" type="image/svg+xml" title="Diagram Title">
<svg>...</svg>
</antArtifact>

For surfacing a manual image:
<antArtifact identifier="unique-id" type="image/surface" title="Image Title" src="/knowledge/images/DOCNAME/page_NNN.png">
</antArtifact>

For a Mermaid flowchart:
<antArtifact identifier="unique-id" type="application/vnd.ant.mermaid" title="Flowchart Title">
flowchart TD...
</antArtifact>

RULES:
- Always cite the manual page number for every fact you state
- For duty cycle questions: use lookup_spec("duty_cycle", ...) and generate a table artifact
- For polarity questions: use lookup_spec("polarity", ...) AND surface the quick-start-guide page 2 image
- For troubleshooting: use lookup_spec("troubleshooting", ...) and list ALL causes
- Keep text concise — the visual artifact carries the explanation
- Never say "I don't know" — if the tool returns nothing, say what you do know and suggest consulting the manual
"""

# ─── Tool definitions ───────────────────────────────────────────────────────────

@tool(
    "search_knowledge",
    "Search the Vulcan OmniPro 220 manual knowledge base using semantic and keyword search. "
    "Use for setup instructions, welding tips, operational procedures, maintenance, and general questions.",
    {"query": str}
)
async def _search_knowledge(args: dict[str, Any]) -> dict[str, Any]:
    query = args.get("query", "")
    try:
        result = tool_search_knowledge(query)
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Search error: {str(e)}"}], "is_error": True}


@tool(
    "lookup_spec",
    "Direct structured lookup for exact specifications. Use for duty cycles, polarity setup, "
    "troubleshooting entries, process selection, and image assets. "
    "spec_type must be one of: duty_cycle, polarity, troubleshooting, selection, images. "
    "params examples: "
    "{spec_type: 'duty_cycle', params: {process: 'MIG', voltage: 240}} "
    "{spec_type: 'polarity', params: {process: 'TIG'}} "
    "{spec_type: 'troubleshooting', params: {symptom: 'porosity', process: 'Flux-Cored'}} "
    "{spec_type: 'selection', params: {material: 'aluminum', skill_level: 'moderate'}} "
    "{spec_type: 'images', params: {tags: ['polarity'], doc_name: 'quick-start-guide'}}",
    {"spec_type": str, "params": dict}
)
async def _lookup_spec(args: dict[str, Any]) -> dict[str, Any]:
    spec_type = args.get("spec_type", "")
    params = args.get("params", {})
    try:
        result = tool_lookup_spec(spec_type, params)
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Lookup error: {str(e)}"}], "is_error": True}


# ─── MCP server (built once at module load) ────────────────────────────────────

_mcp_server = create_sdk_mcp_server(
    name="vulcan-kb",
    version="1.0.0",
    tools=[_search_knowledge, _lookup_spec],
)

_ALLOWED_TOOLS = [
    "mcp__vulcan-kb__search_knowledge",
    "mcp__vulcan-kb__lookup_spec",
]

# ─── Agent options factory ─────────────────────────────────────────────────────

def _make_options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"vulcan-kb": _mcp_server},
        allowed_tools=_ALLOWED_TOOLS,
        permission_mode="bypassPermissions",
        max_turns=8,
    )


# ─── Public interface ──────────────────────────────────────────────────────────

async def run_agent(question: str) -> AsyncIterator[str]:
    """
    Run the agent for a single question and stream the text response.

    Yields text chunks as they arrive. The full response will contain
    both plain text and <antArtifact> XML tags for the frontend to render.

    Args:
        question: the user's natural language question

    Yields:
        str: text chunks of the agent's response
    """
    options = _make_options()
    full_response = []

    async with ClaudeSDKClient(options=options) as client:
        await client.query(question)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text:
                        full_response.append(block.text)
                        yield block.text


async def run_agent_full(question: str) -> str:
    """
    Run the agent and return the complete response as a single string.
    Convenience wrapper around run_agent() for non-streaming contexts.
    """
    chunks = []
    async for chunk in run_agent(question):
        chunks.append(chunk)
    return "".join(chunks)


# ─── Startup initialization ────────────────────────────────────────────────────

def init_agent():
    """
    Initialize the retrieval layer. Call once at server startup.
    Safe to call multiple times — subsequent calls are no-ops.
    """
    init_retrieval()


# ─── CLI test harness ──────────────────────────────────────────────────────────

async def _test():
    print("Initializing knowledge base...")
    init_agent()

    test_questions = [
        "What's the duty cycle for MIG welding at 200A on 240V?",
        "How do I set up TIG welding — which cable goes where?",
        "I'm getting porosity in my flux-cored welds. What should I check?",
    ]

    for question in test_questions:
        print(f"\n{'='*60}")
        print(f"Q: {question}")
        print(f"{'='*60}")
        async for chunk in run_agent(question):
            print(chunk, end="", flush=True)
        print("\n")


if __name__ == "__main__":
    asyncio.run(_test())