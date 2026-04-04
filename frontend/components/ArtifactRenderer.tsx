"use client";

import { useEffect, useRef, useState } from "react";
import type { Artifact } from "@/lib/parseResponse";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://web-production-9e721.up.railway.app";

// ─── React artifact sandbox ────────────────────────────────────────────────────
function ReactArtifact({ artifact }: { artifact: Artifact }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <script src="https://unpkg.com/react@18/umd/react.development.js"></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'DM Sans', system-ui, sans-serif; background: transparent; padding: 16px; }
  </style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel">
    const { useState, useEffect, useRef } = React;
    ${artifact.content}
    const root = ReactDOM.createRoot(document.getElementById('root'));
    root.render(React.createElement(typeof exports !== 'undefined' ? exports.default : window.default || (() => null)));
  </script>
</body>
</html>`;

  return (
    <iframe
      ref={iframeRef}
      srcDoc={html}
      sandbox="allow-scripts"
      style={{ width: "100%", minHeight: 320, border: "none", background: "transparent" }}
      onLoad={() => {
        // Auto-resize to content
        const iframe = iframeRef.current;
        if (iframe?.contentDocument?.body) {
          const h = iframe.contentDocument.body.scrollHeight;
          if (h > 100) iframe.style.height = `${h + 32}px`;
        }
      }}
    />
  );
}

// ─── Mermaid artifact ─────────────────────────────────────────────────────────
function MermaidArtifact({ artifact }: { artifact: Artifact }) {
  const ref = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: "dark",
          themeVariables: {
            primaryColor: "#1e1e2e",
            primaryTextColor: "#e2e8f0",
            primaryBorderColor: "#3b82f6",
            lineColor: "#64748b",
            secondaryColor: "#111118",
            tertiaryColor: "#0a0a0f",
          },
        });
        const id = `mermaid-${artifact.id}`;
        const { svg } = await mermaid.render(id, artifact.content);
        if (!cancelled) setSvg(svg);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [artifact.content, artifact.id]);

  if (error) return (
    <div className="p-4 text-red-400 font-mono text-sm">
      Diagram render error: {error}
    </div>
  );
  if (!svg) return (
    <div className="p-8 text-center text-vulcan-muted animate-pulse">
      Rendering diagram...
    </div>
  );
  return (
    <div
      ref={ref}
      className="p-4 overflow-auto"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

// ─── SVG artifact ─────────────────────────────────────────────────────────────
function SvgArtifact({ artifact }: { artifact: Artifact }) {
  return (
    <div
      className="p-4 overflow-auto"
      dangerouslySetInnerHTML={{ __html: artifact.content }}
    />
  );
}

// ─── Surface image artifact ────────────────────────────────────────────────────
function SurfaceArtifact({ artifact }: { artifact: Artifact }) {
  const src = artifact.src
    ? `${API}${artifact.src}`
    : "";

  if (!src) return (
    <div className="p-4 text-vulcan-muted text-sm">No image source provided.</div>
  );

  return (
    <div className="p-4">
      <img
        src={src}
        alt={artifact.title}
        className="max-w-full rounded-lg border border-vulcan-border"
        style={{ maxHeight: 600, objectFit: "contain" }}
      />
      <p className="mt-2 text-xs text-vulcan-muted font-mono">
        📄 {artifact.title}
      </p>
    </div>
  );
}

// ─── Main ArtifactRenderer ─────────────────────────────────────────────────────
export default function ArtifactRenderer({ artifact }: { artifact: Artifact }) {
  const typeLabel: Record<string, string> = {
    "application/vnd.ant.react": "INTERACTIVE",
    "application/vnd.ant.mermaid": "DIAGRAM",
    "image/svg+xml": "DIAGRAM",
    "image/surface": "MANUAL PAGE",
    "text/html": "HTML",
  };

  const typeColor: Record<string, string> = {
    "application/vnd.ant.react": "text-vulcan-blue",
    "application/vnd.ant.mermaid": "text-vulcan-green",
    "image/svg+xml": "text-vulcan-green",
    "image/surface": "text-yellow-400",
    "text/html": "text-purple-400",
  };

  return (
    <div className="artifact-container my-3">
      <div className="artifact-header">
        <span className={typeColor[artifact.type] ?? "text-vulcan-muted"}>
          ▣
        </span>
        <span className={typeColor[artifact.type] ?? "text-vulcan-muted"}>
          {typeLabel[artifact.type] ?? artifact.type}
        </span>
        <span className="text-vulcan-text/60 ml-1">{artifact.title}</span>
      </div>
      <div className="artifact-body">
        {artifact.type === "application/vnd.ant.react" && (
          <ReactArtifact artifact={artifact} />
        )}
        {artifact.type === "application/vnd.ant.mermaid" && (
          <MermaidArtifact artifact={artifact} />
        )}
        {artifact.type === "image/svg+xml" && (
          <SvgArtifact artifact={artifact} />
        )}
        {artifact.type === "image/surface" && (
          <SurfaceArtifact artifact={artifact} />
        )}
        {artifact.type === "text/html" && (
          <iframe
            srcDoc={artifact.content}
            sandbox="allow-scripts"
            style={{ width: "100%", minHeight: 300, border: "none" }}
          />
        )}
      </div>
    </div>
  );
}