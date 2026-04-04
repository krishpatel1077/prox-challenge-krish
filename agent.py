"""
agent.py — Vulcan OmniPro 220 Technical Expert Agent
======================================================
Uses the standard Anthropic Python client with tool use + streaming.
The Claude Agent SDK requires interactive login and cannot run headlessly
on Railway, so we implement the agent loop directly via the Messages API.
"""

import json
import asyncio
from typing import AsyncIterator

import anthropic
from dotenv import load_dotenv

from retrieval import init_retrieval, tool_search_knowledge, tool_lookup_spec

load_dotenv()

_client = anthropic.Anthropic()
MODEL   = "claude-sonnet-4-6"

TOOLS = [
    {
        "name": "search_knowledge",
        "description": (
            "Search the Vulcan OmniPro 220 manual knowledge base using semantic "
            "and keyword search. Use for setup instructions, welding tips, "
            "operational procedures, maintenance, and general questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "lookup_spec",
        "description": (
            "Direct structured lookup for exact specifications. "
            "spec_type: duty_cycle, polarity, troubleshooting, selection, or images. "
            "Examples: "
            "{spec_type:'duty_cycle', params:{process:'MIG', voltage:240}} "
            "{spec_type:'polarity', params:{process:'TIG'}} "
            "{spec_type:'troubleshooting', params:{symptom:'porosity'}} "
            "{spec_type:'selection', params:{material:'aluminum'}} "
            "{spec_type:'images', params:{tags:['polarity']}}"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "spec_type": {
                    "type": "string",
                    "enum": ["duty_cycle", "polarity", "troubleshooting", "selection", "images"]
                },
                "params": {"type": "object"}
            },
            "required": ["spec_type", "params"]
        }
    }
]

SYSTEM_PROMPT = """You are the technical expert for the Vulcan OmniPro 220 multiprocess welder.
You have deep knowledge of MIG, Flux-Cored, TIG, and Stick processes, duty cycles, polarity setups, wire feed, troubleshooting, and weld diagnosis.

Your user is in their garage with this welder. Be direct, practical, precise. Never vague when you have exact data.

ALWAYS call a tool before answering. Never answer from memory alone.

MULTIMODAL OUTPUT — you MUST generate artifacts for:
- Polarity/cable connections → SVG polarity diagram + surface quick-start-guide page 2 image
- Duty cycle questions → React interactive table
- Troubleshooting weld defects → Mermaid flowchart
- Process selection → React selector widget
- Settings for process/material/thickness → React calculator

Artifact format:

React component (use for tables, calculators, interactive widgets):
<ANTARTIFACTLINK identifier="unique-id" type="application/vnd.ant.react" title="Title" isClosed=“true” />

SVG diagram (use for polarity wiring diagrams):
<ANTARTIFACTLINK identifier="unique-id" type="image/svg+xml" title="Title" isClosed=“true” />

Manual page image (use to surface actual manual pages):
<ANTARTIFACTLINK identifier="unique-id" type="image/surface" title="Title" src="/knowledge/images/DOCNAME/page_NNN.png" isClosed=“true” />

Mermaid flowchart (use for troubleshooting decision trees):
<ANTARTIFACTLINK identifier="unique-id" type="application/vnd.ant.mermaid" title="Title" isClosed=“true” />

CRITICAL Mermaid rules - violations cause syntax errors:
- Use ONLY plain ASCII text in node labels - NO emoji, NO unicode, NO special characters
- Node IDs must be short alphanumeric only: A, B, C1, FIX1
- Use square brackets for rectangles: A[Label text]
- Use curly braces for diamonds: B{Question text}
- Use round brackets for rounded: C(Label)
- Arrow labels use -- text --> format
- Never use quotes inside node labels

Always cite manual page numbers. Keep text concise — the artifact carries the explanation."""

def _execute_tool(name: str, tool_input: dict) -> str:
    try:
        if name == "search_knowledge":
            result = tool_search_knowledge(tool_input.get("query", ""))
        elif name == "lookup_spec":
            result = tool_lookup_spec(
                tool_input.get("spec_type", ""),
                tool_input.get("params", {})
            )
        else:
            result = {"error": f"Unknown tool: {name}"}
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


async def run_agent(question: str) -> AsyncIterator[str]:
    """Run agent and stream text response including artifact XML."""
    messages = [{"role": "user", "content": question}]

    # Tool loop — up to 5 turns
    for _ in range(5):
        response = _client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        tool_uses = [b for b in response.content if b.type == "tool_use"]

        if not tool_uses:
            # No more tools — stream final answer
            messages.append({"role": "assistant", "content": response.content})
            with _client.messages.stream(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages[:-1],
            ) as stream:
                for text in stream.text_stream:
                    yield text
            return

        # Execute tools and continue
        tool_results = []
        for tu in tool_uses:
            result = _execute_tool(tu.name, tu.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result,
            })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    # Max turns hit — stream with what we have
    with _client.messages.stream(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text


async def run_agent_full(question: str) -> str:
    chunks = []
    async for chunk in run_agent(question):
        chunks.append(chunk)
    return "".join(chunks)


def init_agent():
    init_retrieval()


async def _test():
    print("Initializing...")
    init_agent()
    questions = [
        "What's the duty cycle for MIG at 200A on 240V?",
        "TIG polarity — which cable goes where?",
        "Getting porosity in flux-cored welds",
    ]
    for q in questions:
        print(f"\n{'='*60}\nQ: {q}\n{'='*60}")
        async for chunk in run_agent(q):
            print(chunk, end="", flush=True)
        print()


if __name__ == "__main__":
    asyncio.run(_test())