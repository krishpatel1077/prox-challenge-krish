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

// Maps vizblock type attr → ArtifactType
const TYPE_MAP: Record<string, ArtifactType> = {
  "react": "application/vnd.ant.react",
  "mermaid": "application/vnd.ant.mermaid",
  "svg": "image/svg+xml",
  "image": "image/surface",
  "html": "text/html",
  // Also accept full mime types directly
  "application/vnd.ant.react": "application/vnd.ant.react",
  "application/vnd.ant.mermaid": "application/vnd.ant.mermaid",
  "image/svg+xml": "image/svg+xml",
  "image/surface": "image/surface",
};

function parseAttrs(attrString: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  const re = /(\w+)=["']([^"']*)["']/g;
  let m;
  while ((m = re.exec(attrString)) !== null) {
    attrs[m[1]] = m[2];
  }
  return attrs;
}

// Matches both <vizblock ...>content</vizblock>
// and <antArtifact ...>content</antArtifact>
const BLOCK_RE = /<(?:vizblock|antArtifact)\s+([\s\S]*?)>([\s\S]*?)<\/(?:vizblock|antArtifact)>/g;

// Also match self-closing image blocks: <vizblock type="image" src="..." title="..."></vizblock>
// and <antArtifact type="image/surface" src="..." ...></antArtifact>
const SELF_CLOSING_RE = /<(?:vizblock|antArtifact)\s+([^>]*?(?:type=["']image[^"']*["'][^>]*?))><\/(?:vizblock|antArtifact)>/g;

export function parseResponse(raw: string): ParsedSegment[] {
  const segments: ParsedSegment[] = [];
  const matches: Array<{ index: number; length: number; artifact: Artifact }> = [];

  // Find all block matches
  BLOCK_RE.lastIndex = 0;
  let m;
  while ((m = BLOCK_RE.exec(raw)) !== null) {
    const attrs = parseAttrs(m[1]);
    const rawType = attrs.type ?? "";
    const type: ArtifactType = TYPE_MAP[rawType] ?? "application/vnd.ant.react";
    matches.push({
      index: m.index,
      length: m[0].length,
      artifact: {
        id: Math.random().toString(36).slice(2),
        identifier: attrs.identifier ?? attrs.id ?? "",
        type,
        title: attrs.title ?? "Output",
        src: attrs.src,
        content: m[2].trim(),
      },
    });
  }

  // Find self-closing image blocks not already captured
  SELF_CLOSING_RE.lastIndex = 0;
  while ((m = SELF_CLOSING_RE.exec(raw)) !== null) {
    const alreadyCaptured = matches.some(
      (x) => x.index === m!.index
    );
    if (!alreadyCaptured) {
      const attrs = parseAttrs(m[1]);
      matches.push({
        index: m.index,
        length: m[0].length,
        artifact: {
          id: Math.random().toString(36).slice(2),
          identifier: attrs.identifier ?? "",
          type: "image/surface",
          title: attrs.title ?? "Manual Page",
          src: attrs.src,
          content: "",
        },
      });
    }
  }

  // Sort by position
  matches.sort((a, b) => a.index - b.index);

  let lastIndex = 0;
  for (const match of matches) {
    if (match.index > lastIndex) {
      const text = raw.slice(lastIndex, match.index).trim();
      if (text) segments.push({ kind: "text", text });
    }
    segments.push({ kind: "artifact", artifact: match.artifact });
    lastIndex = match.index + match.length;
  }

  if (lastIndex < raw.length) {
    const text = raw.slice(lastIndex).trim();
    if (text) segments.push({ kind: "text", text });
  }

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
    .replace(/^\|(.+)\|$/gm, (line) => {
      const cells = line.split("|").slice(1, -1);
      return `<tr>${cells.map((c) => `<td>${c.trim()}</td>`).join("")}</tr>`;
    })
    .replace(/(<tr>[\s\S]*?<\/tr>\n?)+/g, (block) => `<table>${block}</table>`)
    .replace(/<tr><td>[-: ]+<\/td>(<td>[-: ]+<\/td>)*<\/tr>/g, "")
    .replace(/^[\*\-] (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>[\s\S]*?<\/li>\n?)+/g, "<ul>$&</ul>")
    .replace(/^\d+\. (.+)$/gm, "<li>$1</li>")
    .replace(/\n\n+/g, "</p><p>")
    .replace(/\n/g, "<br>");
}