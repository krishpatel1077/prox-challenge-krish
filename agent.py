"""
agent.py — Vulcan OmniPro 220 Technical Expert Agent
======================================================
Uses the standard Anthropic Python client with tool use + streaming.
After the main response, detects ANTARTIFACTLINK tags and generates
the actual artifact content via a follow-up call.
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

Your user is in their garage. Be direct, practical, precise. Always cite manual page numbers.

ALWAYS call a tool before answering. Never answer from memory alone."""


ARTIFACT_SYSTEM = """You generate self-contained visual components for a welding expert app.
Output ONLY the raw component code with no explanation, no markdown fences, no preamble.

For React: output JSX with hooks via React.useState, React.useEffect etc. End with: export default function ComponentName() {...}
For SVG: output a complete <svg> element.
For Mermaid: output flowchart TD syntax using only ASCII text, no emoji.

The component renders inside a dark-themed app (background #111118, text #e2e8f0).
Keep it focused, practical, and visually clear."""


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


def _generate_artifact_content(artifact_type: str, title: str, context: str) -> str:
    """Generate the actual artifact content for an ANTARTIFACTLINK reference."""
    
    type_instructions = {
        "application/vnd.ant.react": f"Generate a React interactive component for: {title}. Output only JSX code ending with 'export default function {title.replace(' ', '').replace('-', '')}() {{...}}'",
        "image/svg+xml": f"Generate an SVG wiring/polarity diagram for: {title}. Output only the <svg> element.",
        "application/vnd.ant.mermaid": f"Generate a Mermaid flowchart for: {title}. Output only 'flowchart TD' syntax with ASCII-only labels.",
    }
    
    instruction = type_instructions.get(artifact_type, f"Generate content for: {title}")
    
    response = _client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=ARTIFACT_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"{instruction}\n\nContext from the conversation:\n{context}"
        }]
    )
    
    content = ""
    for block in response.content:
        if hasattr(block, "text"):
            content += block.text
    
    # Strip any markdown fences if Claude added them
    content = re.sub(r'^```\w*\n?', '', content.strip())
    content = re.sub(r'\n?```$', '', content.strip())
    return content.strip()


ANTARTIFACTLINK_RE = re.compile(
    r'<ANTARTIFACTLINK\s+([^/]*?)\s*/?>',
    re.IGNORECASE
)

def _parse_antartifactlink_attrs(attr_string: str) -> dict:
    attrs = {}
    for m in re.finditer(r'(\w+)=["\']([^"\']*)["\']', attr_string):
        attrs[m.group(1)] = m.group(2)
    return attrs


def _replace_antartifactlinks(text: str, context: str) -> str:
    """Replace ANTARTIFACTLINK tags with actual antArtifact tags containing generated content."""
    
    def replace_match(m):
        attrs = _parse_antartifactlink_attrs(m.group(1))
        artifact_type = attrs.get("type", "application/vnd.ant.react")
        title = attrs.get("title", "Component")
        identifier = attrs.get("identifier", "artifact")
        
        # For image/surface types, no content needed
        if artifact_type == "image/surface":
            src = attrs.get("src", "")
            return f'<antArtifact identifier="{identifier}" type="image/surface" title="{title}" src="{src}"></antArtifact>'
        
        # Generate the actual content
        try:
            content = _generate_artifact_content(artifact_type, title, context)
            return f'<antArtifact identifier="{identifier}" type="{artifact_type}" title="{title}">\n{content}\n</antArtifact>'
        except Exception as e:
            return f'<antArtifact identifier="{identifier}" type="{artifact_type}" title="{title}">\n// Error generating content: {e}\n</antArtifact>'
    
    return ANTARTIFACTLINK_RE.sub(replace_match, text)


async def run_agent(question: str) -> AsyncIterator[str]:
    """Run agent and stream text response. Replaces ANTARTIFACTLINK refs with real content."""
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
            # Stream final answer
            messages.append({"role": "assistant", "content": response.content})
            
            full_text = ""
            with _client.messages.stream(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages[:-1],
            ) as stream:
                for text in stream.text_stream:
                    full_text += text
                    yield text
            
            # Check if there are any ANTARTIFACTLINK tags to replace
            if "ANTARTIFACTLINK" in full_text.upper():
                # Build context for artifact generation
                context = f"Question: {question}\n\nAnswer so far:\n{full_text[:500]}"
                
                # Find all links and generate replacements
                links = list(ANTARTIFACTLINK_RE.finditer(full_text))
                if links:
                    yield "\n\n"  # separator before artifacts
                    for m in links:
                        attrs = _parse_antartifactlink_attrs(m.group(1))
                        artifact_type = attrs.get("type", "application/vnd.ant.react")
                        title = attrs.get("title", "Component")
                        identifier = attrs.get("identifier", "artifact")
                        
                        if artifact_type == "image/surface":
                            src = attrs.get("src", "")
                            yield f'<antArtifact identifier="{identifier}" type="image/surface" title="{title}" src="{src}"></antArtifact>\n'
                        else:
                            try:
                                content = _generate_artifact_content(artifact_type, title, context)
                                yield f'<antArtifact identifier="{identifier}" type="{artifact_type}" title="{title}">\n{content}\n</antArtifact>\n'
                            except Exception as e:
                                pass  # silently skip failed artifacts
            return

        # Execute tools
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

    # Max turns
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