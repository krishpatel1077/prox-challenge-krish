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

const TYPE_MAP: Record<string, ArtifactType> = {
  "react": "application/vnd.ant.react",
  "mermaid": "application/vnd.ant.mermaid",
  "svg": "image/svg+xml",
  "image": "image/surface",
  "html": "text/html",
  "application/vnd.ant.react": "application/vnd.ant.react",
  "application/vnd.ant.mermaid": "application/vnd.ant.mermaid",
  "image/svg+xml": "image/svg+xml",
  "image/surface": "image/surface",
};

function parseAttrs(attrString: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  // Match key="value" or key='value' — value can contain anything except the quote
  const re = /(\w+)=(?:"([^"]*)"|'([^']*)')/g;
  let m;
  while ((m = re.exec(attrString)) !== null) {
    attrs[m[1]] = m[2] ?? m[3] ?? "";
  }
  return attrs;
}

/**
 * String-based parser — finds opening tags, then scans forward for the
 * matching closing tag. Not vulnerable to > inside JSX content.
 */
export function parseResponse(raw: string): ParsedSegment[] {
  const segments: ParsedSegment[] = [];
  const TAG_NAMES = ["antArtifact", "vizblock"];
  
  let pos = 0;
  
  while (pos < raw.length) {
    // Find the next opening tag
    let nearestOpen = -1;
    let nearestTagName = "";
    
    for (const tagName of TAG_NAMES) {
      const idx = raw.indexOf(`<${tagName}`, pos);
      if (idx !== -1 && (nearestOpen === -1 || idx < nearestOpen)) {
        nearestOpen = idx;
        nearestTagName = tagName;
      }
    }
    
    if (nearestOpen === -1) {
      // No more tags — rest is text
      const text = raw.slice(pos).trim();
      if (text) segments.push({ kind: "text", text });
      break;
    }
    
    // Text before this tag
    if (nearestOpen > pos) {
      const text = raw.slice(pos, nearestOpen).trim();
      if (text) segments.push({ kind: "text", text });
    }
    
    // Find end of opening tag (the >)
    const openTagEnd = raw.indexOf(">", nearestOpen);
    if (openTagEnd === -1) {
      // Malformed — treat rest as text
      const text = raw.slice(nearestOpen).trim();
      if (text) segments.push({ kind: "text", text });
      break;
    }
    
    const openTagFull = raw.slice(nearestOpen, openTagEnd + 1);
    // Extract just the attributes part (between <tagName and >)
    const attrString = openTagFull.slice(nearestTagName.length + 1, -1).trim();
    const attrs = parseAttrs(attrString);
    
    // Find closing tag
    const closeTag = `</${nearestTagName}>`;
    const closeStart = raw.indexOf(closeTag, openTagEnd + 1);
    
    let content = "";
    let endPos: number;
    
    if (closeStart === -1) {
      // No closing tag — self-closing or incomplete; treat as empty artifact
      endPos = openTagEnd + 1;
    } else {
      content = raw.slice(openTagEnd + 1, closeStart).trim();
      endPos = closeStart + closeTag.length;
    }
    
    const rawType = attrs.type ?? "";
    const type: ArtifactType = TYPE_MAP[rawType] ?? "application/vnd.ant.react";
    
    segments.push({
      kind: "artifact",
      artifact: {
        id: Math.random().toString(36).slice(2),
        identifier: attrs.identifier ?? attrs.id ?? "",
        type,
        title: attrs.title ?? "Output",
        src: attrs.src,
        content,
      },
    });
    
    pos = endPos;
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