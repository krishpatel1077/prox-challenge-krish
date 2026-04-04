export type ArtifactType =
  | "application/vnd.ant.react"
  | "application/vnd.ant.mermaid"
  | "image/svg+xml"
  | "image/surface"
  | "text/html";

export interface Artifact {
  id: string;
  identifier: string;
  type: ArtifactType;
  title: string;
  src?: string;
  content: string;
}

export interface ParsedSegment {
  kind: "text" | "artifact";
  text?: string;
  artifact?: Artifact;
}

// Robust regex — handles multiline, flexible whitespace, single or double quotes
const ARTIFACT_RE = /<antArtifact\s+([\s\S]*?)>([\s\S]*?)<\/antArtifact>/g;

function parseAttrs(attrString: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  // Match both single and double quoted attribute values
  const re = /(\w+)=["']([^"']*)["']/g;
  let m;
  while ((m = re.exec(attrString)) !== null) {
    attrs[m[1]] = m[2];
  }
  return attrs;
}

export function parseResponse(raw: string): ParsedSegment[] {
  const segments: ParsedSegment[] = [];
  let lastIndex = 0;
  let match;
  ARTIFACT_RE.lastIndex = 0;

  while ((match = ARTIFACT_RE.exec(raw)) !== null) {
    // Text before this artifact
    if (match.index > lastIndex) {
      const text = raw.slice(lastIndex, match.index).trim();
      if (text) segments.push({ kind: "text", text });
    }

    const attrs = parseAttrs(match[1]);
    const artifact: Artifact = {
      id: Math.random().toString(36).slice(2),
      identifier: attrs.identifier ?? "",
      type: (attrs.type as ArtifactType) ?? "text/html",
      title: attrs.title ?? "Output",
      src: attrs.src,
      content: match[2].trim(),
    };
    segments.push({ kind: "artifact", artifact });
    lastIndex = match.index + match[0].length;
  }

  // Remaining text
  if (lastIndex < raw.length) {
    const text = raw.slice(lastIndex).trim();
    if (text) segments.push({ kind: "text", text });
  }

  // If no artifacts found but raw contains <antArtifact, the stream is still
  // accumulating — return as text so it streams in
  return segments.length > 0 ? segments : [{ kind: "text", text: raw }];
}

// Simple markdown → HTML
export function markdownToHtml(md: string): string {
  return md
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/^---$/gm, "<hr>")
    .replace(/^> (.+)$/gm, "<blockquote>$1</blockquote>")
    // Tables
    .replace(/^\|(.+)\|$/gm, (line) => {
      const cells = line.split("|").slice(1, -1);
      return `<tr>${cells.map((c) => `<td>${c.trim()}</td>`).join("")}</tr>`;
    })
    .replace(/(<tr>[\s\S]*?<\/tr>\n?)+/g, (block) => `<table>${block}</table>`)
    // Skip separator rows like |---|---|
    .replace(/<tr><td>[-: ]+<\/td>(<td>[-: ]+<\/td>)*<\/tr>/g, "")
    // Lists
    .replace(/^[\*\-] (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>[\s\S]*?<\/li>\n?)+/g, "<ul>$&</ul>")
    .replace(/^\d+\. (.+)$/gm, "<li>$1</li>")
    // Paragraphs
    .replace(/\n\n+/g, "</p><p>")
    .replace(/\n/g, "<br>");
}