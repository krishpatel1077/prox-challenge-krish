"""
agent.py — Vulcan OmniPro 220 Technical Expert Agent
"""

import json
import re
import asyncio
from typing import AsyncIterator

import anthropic
from dotenv import load_dotenv

from retrieval import init_retrieval, tool_search_knowledge, tool_lookup_spec

load_dotenv()

_client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-6"

TOOLS = [
    {
        "name": "search_knowledge",
        "description": "Search the Vulcan OmniPro 220 manual knowledge base. Use for setup instructions, welding tips, operational procedures, maintenance.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]
        }
    },
    {
        "name": "lookup_spec",
        "description": "Direct structured lookup. spec_type: duty_cycle, polarity, troubleshooting, selection, images.",
        "input_schema": {
            "type": "object",
            "properties": {
                "spec_type": {"type": "string", "enum": ["duty_cycle", "polarity", "troubleshooting", "selection", "images"]},
                "params": {"type": "object"}
            },
            "required": ["spec_type", "params"]
        }
    }
]

SYSTEM_PROMPT = """You are the technical expert for the Vulcan OmniPro 220 multiprocess welder.
Deep knowledge of MIG, Flux-Cored, TIG, Stick — duty cycles, polarity, wire feed, troubleshooting.
User is in their garage. Direct, practical, precise. Always cite manual page numbers.
Always call a tool before answering."""

# Artifact generation prompts by type
ARTIFACT_PROMPTS = {
    "duty_cycle": """Generate a React interactive duty cycle table for the Vulcan OmniPro 220 MIG at 240V.
Data: 200A=25% (weld 150s, rest 450s per 10min), 115A=100% (continuous).
Dark theme: background #0f172a, text #e2e8f0, accent #3b82f6.
Clickable rows, progress bars, shows weld/rest time in seconds.
Output ONLY the React component code. End with: export default function DutyCycleTable() { ... }""",

    "polarity": """Generate an SVG wiring diagram for TIG DCEN polarity setup on the Vulcan OmniPro 220.
Show: welder front panel with two sockets (NEG on left in blue, POS on right in red).
TIG torch cable → NEG socket (blue line/label).
Ground clamp cable → POS socket (red line/label).
Dark background #1a1a2e, clear labels, viewBox="0 0 700 400".
Output ONLY the complete <svg> element.""",

    "troubleshooting": """Generate a Mermaid flowchart for troubleshooting porosity in flux-cored welds.
Start with polarity check (most common cause), then base metal cleanliness, CTWD, wire condition, gas flow.
Each branch ends with a fix action.
Use ONLY plain ASCII text in node labels. No emoji. No unicode.
Format: flowchart TD with A[text], B{question}, -- arrow labels -->
Output ONLY the mermaid flowchart syntax.""",

    "process_selection": """Generate a React process selector widget for the Vulcan OmniPro 220.
Shows 4 processes: MIG, Flux-Core, TIG, Stick with their material ranges and skill levels.
User can click a process to see details. Dark theme #0f172a background.
Output ONLY the React component. End with: export default function ProcessSelector() { ... }"""
}

ARTIFACT_TYPE_MAP = {
    "duty_cycle": "application/vnd.ant.react",
    "polarity": "image/svg+xml",
    "troubleshooting": "application/vnd.ant.mermaid",
    "process_selection": "application/vnd.ant.react",
}

ARTIFACT_TITLE_MAP = {
    "duty_cycle": "MIG Duty Cycle — 240V",
    "polarity": "TIG DCEN Polarity Diagram",
    "troubleshooting": "Troubleshooting Flowchart",
    "process_selection": "Process Selector",
}


def _classify_question(question: str) -> list[str]:
    """Detect which artifact types are needed for this question."""
    q = question.lower()
    artifacts = []
    if any(w in q for w in ["duty cycle", "duty", "200a", "115a", "overheat", "thermal", "how long", "continuous"]):
        artifacts.append("duty_cycle")
    if any(w in q for w in ["polarity", "tig", "cable", "socket", "positive", "negative", "dcen", "ground clamp", "torch"]):
        artifacts.append("polarity")
    if any(w in q for w in ["porosity", "spatter", "crack", "undercut", "burn through", "troubleshoot", "defect", "problem", "wrong", "issue"]):
        artifacts.append("troubleshooting")
    if any(w in q for w in ["which process", "what process", "mig vs", "tig vs", "select", "choose", "recommend", "thin sheet", "aluminum"]):
        artifacts.append("process_selection")
    return artifacts


def _generate_artifact(artifact_key: str) -> str:
    """Generate artifact content via a focused API call."""
    prompt = ARTIFACT_PROMPTS.get(artifact_key, "")
    if not prompt:
        return ""
    
    response = _client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system="You output raw code only. No markdown fences, no explanation, no preamble. Just the code.",
        messages=[{"role": "user", "content": prompt}]
    )
    
    content = ""
    for block in response.content:
        if hasattr(block, "text"):
            content += block.text
    
    # Strip markdown fences if present
    content = re.sub(r'^```[\w]*\n?', '', content.strip())
    content = re.sub(r'\n?```$', '', content.strip())
    return content.strip()


def _execute_tool(name: str, tool_input: dict) -> str:
    try:
        if name == "search_knowledge":
            result = tool_search_knowledge(tool_input.get("query", ""))
        elif name == "lookup_spec":
            result = tool_lookup_spec(tool_input.get("spec_type", ""), tool_input.get("params", {}))
        else:
            result = {"error": f"Unknown tool: {name}"}
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


async def run_agent(question: str) -> AsyncIterator[str]:
    """Run agent, stream text response, then append generated artifacts."""
    messages = [{"role": "user", "content": question}]

    # Tool loop
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
            # Stream final text answer
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

            # Classify question and generate artifacts
            artifact_keys = _classify_question(question)
            
            # Also check for polarity image
            if "polarity" in artifact_keys or any(w in question.lower() for w in ["tig", "polarity", "cable"]):
                yield '\n\n<antArtifact identifier="tig-qsg" type="image/surface" title="Quick-Start Guide — Polarity Setup (p.2)" src="/knowledge/images/quick-start-guide/page_002.png"></antArtifact>\n'

            for key in artifact_keys:
                artifact_type = ARTIFACT_TYPE_MAP.get(key, "application/vnd.ant.react")
                artifact_title = ARTIFACT_TITLE_MAP.get(key, "Visual")
                identifier = key.replace("_", "-")
                
                try:
                    content = _generate_artifact(key)
                    if content:
                        yield f'\n\n<antArtifact identifier="{identifier}" type="{artifact_type}" title="{artifact_title}">\n{content}\n</antArtifact>\n'
                except Exception:
                    pass
            return

        # Execute tools
        tool_results = []
        for tu in tool_uses:
            result = _execute_tool(tu.name, tu.input)
            tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": result})

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    # Max turns fallback
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