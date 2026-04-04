"use client";

import { useEffect, useRef, useState } from "react";
import type { Artifact } from "@/lib/parseResponse";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://web-production-9e721.up.railway.app";

function ReactArtifact({ artifact }: { artifact: Artifact }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(360);

  // Process export default — strip it from declarations, assign to window
  const nameMatch = artifact.content.match(/export\s+default\s+function\s+(\w+)/);
  const componentName = nameMatch ? nameMatch[1] : null;
  const processedCode = artifact.content
    // export default function Name -> function Name (preserve the function)
    .replace(/export\s+default\s+function\s+(\w+)/g, 'function $1')
    // export default SomeName; -> (handled below by appending)
    .replace(/export\s+default\s+(\w+)\s*;?\s*$/gm, '')
    // Append window assignment at end
    + (componentName ? `\nwindow.__ArtifactComponent = ${componentName};` : '');

  const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <script src="https://unpkg.com/react@18/umd/react.development.js" crossorigin></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js" crossorigin></script>
  <script src="https://unpkg.com/@babel/standalone@7.23.10/babel.min.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'DM Sans', system-ui, sans-serif;
      background: #111118;
      color: #e2e8f0;
      padding: 16px;
    }
  </style>
</head>
<body>
  <div id="root"></div>
  <script>
    // Make React hooks available globally
    window.useState = React.useState;
    window.useEffect = React.useEffect;
    window.useRef = React.useRef;
    window.useMemo = React.useMemo;
    window.useCallback = React.useCallback;
  </script>
  <script type="text/babel" data-presets="react">
    ${processedCode}

    // Mount the component
    (function() {
      const Component = window.__ArtifactComponent;
      if (!Component) {
        document.getElementById('root').innerHTML =
          '<div style="color:#f87171;padding:16px;font-family:monospace">Component not found. Make sure it uses "export default".</div>';
        return;
      }
      try {
        const root = ReactDOM.createRoot(document.getElementById('root'));
        root.render(React.createElement(Component));
      } catch(e) {
        document.getElementById('root').innerHTML =
          '<pre style="color:#f87171;font-size:12px;padding:16px">' + e.message + '</pre>';
      }
    })();
  </script>
  <script>
    // Report height to parent for auto-resize
    function reportHeight() {
      const h = document.body.scrollHeight;
      window.parent.postMessage({ type: 'resize', height: h }, '*');
    }
    // Report after render
    setTimeout(reportHeight, 200);
    setTimeout(reportHeight, 800);
    new ResizeObserver(reportHeight).observe(document.body);
  </script>
</body>
</html>`;

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === 'resize' && e.data.height > 100) {
        setHeight(Math.min(e.data.height + 32, 800));
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, []);

  return (
    <iframe
      ref={iframeRef}
      srcDoc={html}
      sandbox="allow-scripts"
      style={{ width: "100%", height, border: "none", background: "transparent" }}
    />
  );
}

function MermaidArtifact({ artifact }: { artifact: Artifact }) {
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
        const id = `mermaid-${artifact.id}-${Date.now()}`;
        const { svg: rendered } = await mermaid.render(id, artifact.content);
        if (!cancelled) setSvg(rendered);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [artifact.content, artifact.id]);

  if (error) return (
    <div className="p-4 text-red-400 font-mono text-sm">Diagram error: {error}</div>
  );
  if (!svg) return (
    <div className="p-8 text-center text-vulcan-muted text-sm animate-pulse">Rendering diagram...</div>
  );
  return (
    <div className="p-4 overflow-auto" dangerouslySetInnerHTML={{ __html: svg }} />
  );
}

function SvgArtifact({ artifact }: { artifact: Artifact }) {
  return (
    <div className="p-4 overflow-auto" dangerouslySetInnerHTML={{ __html: artifact.content }} />
  );
}

function SurfaceArtifact({ artifact }: { artifact: Artifact }) {
  const src = artifact.src ? `${API}${artifact.src}` : "";
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
      <p className="mt-2 text-xs text-vulcan-muted font-mono">📄 {artifact.title}</p>
    </div>
  );
}

export default function ArtifactRenderer({ artifact }: { artifact: Artifact }) {
  // const [mounted, setMounted] = useState(false);
  // useEffect(() => { setMounted(true); }, []);

  const typeLabel: Record<string, string> = {
    "application/vnd.ant.react": "INTERACTIVE",
    "application/vnd.ant.mermaid": "DIAGRAM",
    "image/svg+xml": "DIAGRAM",
    "image/surface": "MANUAL PAGE",
    "text/html": "HTML",
  };

  const typeColor: Record<string, string> = {
    "application/vnd.ant.react": "text-blue-400",
    "application/vnd.ant.mermaid": "text-green-400",
    "image/svg+xml": "text-green-400",
    "image/surface": "text-yellow-400",
    "text/html": "text-purple-400",
  };

  // if (!mounted) return (
  //   <div className="artifact-container my-3">
  //     <div className="artifact-header">
  //       <span className="text-vulcan-muted">▣ {artifact.title}</span>
  //     </div>
  //     <div className="p-4 text-sm text-vulcan-muted animate-pulse">Loading...</div>
  //   </div>
  // );

  return (
    <div className="artifact-container my-3">
      <div className="artifact-header">
        <span className={typeColor[artifact.type] ?? "text-vulcan-muted"}>▣</span>
        <span className={typeColor[artifact.type] ?? "text-vulcan-muted"}>
          {typeLabel[artifact.type] ?? artifact.type}
        </span>
        <span className="text-vulcan-text/60 ml-1">{artifact.title}</span>
      </div>
      <div className="artifact-body">
        {artifact.type === "application/vnd.ant.react" && <ReactArtifact artifact={artifact} />}
        {artifact.type === "application/vnd.ant.mermaid" && <MermaidArtifact artifact={artifact} />}
        {artifact.type === "image/svg+xml" && <SvgArtifact artifact={artifact} />}
        {artifact.type === "image/surface" && <SurfaceArtifact artifact={artifact} />}
        {artifact.type === "text/html" && (
          <iframe srcDoc={artifact.content} sandbox="allow-scripts"
            style={{ width: "100%", minHeight: 300, border: "none" }} />
        )}
      </div>
    </div>
  );
}