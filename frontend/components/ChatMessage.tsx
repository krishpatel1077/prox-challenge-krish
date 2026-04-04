"use client";

import { parseResponse, markdownToHtml } from "@/lib/parseResponse";
import ArtifactRenderer from "./ArtifactRenderer";

interface MessageProps {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

export default function ChatMessage({ role, content, streaming }: MessageProps) {
  if (role === "user") {
    return (
      <div className="flex justify-end mb-4">
        <div
          className="max-w-[80%] px-4 py-3 rounded-2xl rounded-tr-sm text-sm"
          style={{
            background: "#1e1e2e",
            border: "1px solid #2a2a3e",
            color: "#e2e8f0",
          }}
        >
          {content}
        </div>
      </div>
    );
  }

  // Assistant: parse into text + artifact segments
  const segments = parseResponse(content);

  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-2">
        <div
          className="w-6 h-6 rounded flex items-center justify-center text-xs font-bold"
          style={{ background: "#ff6b2b", color: "#0a0a0f" }}
        >
          V
        </div>
        <span className="text-xs font-mono text-vulcan-muted uppercase tracking-widest">
          Vulcan Expert
        </span>
        {streaming && (
          <span className="text-xs text-vulcan-accent animate-pulse">
            ● responding
          </span>
        )}
      </div>

      <div className="pl-8">
        {segments.map((seg, i) => {
          if (seg.kind === "text" && seg.text) {
            const isLast = i === segments.length - 1;
            return (
              <div
                key={i}
                className={`prose-chat text-sm leading-relaxed ${streaming && isLast ? "typing-cursor" : ""}`}
                dangerouslySetInnerHTML={{ __html: markdownToHtml(seg.text) }}
              />
            );
          }
          if (seg.kind === "artifact" && seg.artifact) {
            if (streaming) {
              // Don't render artifact while streaming — show placeholder
              return (
                <div key={i} className="artifact-container my-3">
                  <div className="artifact-header">
                    <span className="text-blue-400">▣</span>
                    <span className="text-blue-400">INTERACTIVE</span>
                    <span className="text-vulcan-text/60 ml-1">{seg.artifact.title}</span>
                  </div>
                  <div className="p-4 text-sm text-vulcan-muted animate-pulse">Generating visual...</div>
                </div>
              );
            }
            return (
              <ArtifactRenderer key={seg.artifact.identifier || i} artifact={seg.artifact} />
            );
          }
          return null;
        })}
        {streaming && segments.length === 0 && (
          <div className="text-sm text-vulcan-muted typing-cursor">
            Searching knowledge base
          </div>
        )}
      </div>
    </div>
  );
}