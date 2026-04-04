"use client";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://web-production-9e721.up.railway.app";

interface Hotspot {
  id: string;
  label: string;
  x: string;
  y: string;
  query: string;
  description: string;
}

const HOTSPOTS: Hotspot[] = [
  {
    id: "lcd",
    label: "LCD Display",
    x: "42%",
    y: "38%",
    query: "How do I use the LCD display and control knobs to set welding parameters?",
    description: "Control panel & settings",
  },
  {
    id: "wire-feed",
    label: "Wire Feed",
    x: "62%",
    y: "48%",
    query: "How do I install wire spool and set wire feed tension?",
    description: "Wire spool & feed mechanism",
  },
  {
    id: "power-sockets",
    label: "Sockets",
    x: "28%",
    y: "72%",
    query: "What are the positive and negative sockets used for — which cable goes where?",
    description: "Positive (+) and Negative (−) sockets",
  },
  {
    id: "power-switch",
    label: "Power",
    x: "18%",
    y: "45%",
    query: "How do I turn on the welder and what does the startup sequence look like?",
    description: "Power switch",
  },
  {
    id: "gas-inlet",
    label: "Gas Inlet",
    x: "72%",
    y: "78%",
    query: "How do I connect the shielding gas regulator and hose?",
    description: "Gas inlet for MIG & TIG",
  },
  {
    id: "duty-cycle",
    label: "Duty Cycle",
    x: "50%",
    y: "85%",
    query: "What is the duty cycle for this welder at different amperages?",
    description: "Usage limits & thermal protection",
  },
];

interface Props {
  onQuery: (query: string) => void;
}

export default function ProductDiagram({ onQuery }: Props) {
  const imageUrl = `${API}/knowledge/images/owner-manual/page_008.png`;

  return (
    <div className="relative w-full rounded-xl overflow-hidden border border-vulcan-border"
         style={{ background: "#0f0f18" }}>

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-vulcan-border">
        <div>
          <p className="text-xs font-mono text-vulcan-muted uppercase tracking-widest">
            Interactive Guide
          </p>
          <h3 className="text-sm font-semibold text-vulcan-text mt-0.5">
            Vulcan OmniPro 220 — Click any component to learn more
          </h3>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-vulcan-accent animate-pulse" />
          <span className="text-xs text-vulcan-muted font-mono">LIVE</span>
        </div>
      </div>

      {/* Image + hotspots */}
      <div className="relative" style={{ paddingBottom: "66%" }}>
        {/* Manual page image */}
        <img
          src={imageUrl}
          alt="Vulcan OmniPro 220 front panel"
          className="absolute inset-0 w-full h-full object-contain"
          style={{ filter: "brightness(0.9)" }}
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = "none";
          }}
        />

        {/* Dark overlay for contrast */}
        <div
          className="absolute inset-0"
          style={{ background: "linear-gradient(to bottom, transparent 60%, #0f0f18 100%)" }}
        />

        {/* Hotspot buttons */}
        {HOTSPOTS.map((h) => (
          <button
            key={h.id}
            onClick={() => onQuery(h.query)}
            className="absolute group"
            style={{ left: h.x, top: h.y, transform: "translate(-50%, -50%)" }}
            title={h.description}
          >
            {/* Pulsing ring */}
            <span
              className="absolute inset-0 rounded-full animate-ping"
              style={{
                background: "rgba(255, 107, 43, 0.3)",
                animationDuration: "2s",
              }}
            />
            {/* Dot */}
            <span
              className="relative flex items-center justify-center w-7 h-7 rounded-full border-2 text-xs font-bold transition-all duration-150 group-hover:scale-125"
              style={{
                background: "#ff6b2b",
                borderColor: "#ff6b2b",
                color: "#0a0a0f",
                boxShadow: "0 0 12px rgba(255,107,43,0.5)",
              }}
            >
              ?
            </span>
            {/* Tooltip */}
            <span
              className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 rounded text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
              style={{
                background: "#1e1e2e",
                border: "1px solid #2a2a3e",
                color: "#e2e8f0",
              }}
            >
              {h.label}
            </span>
          </button>
        ))}
      </div>

      {/* Quick question chips */}
      <div className="px-4 py-3 border-t border-vulcan-border">
        <p className="text-xs text-vulcan-muted mb-2 font-mono uppercase tracking-widest">
          Common questions
        </p>
        <div className="flex flex-wrap gap-2">
          {[
            "MIG duty cycle at 200A/240V?",
            "TIG polarity setup",
            "Porosity in flux-cored welds",
            "Which process for thin aluminum?",
            "Wire feed tension setting",
          ].map((q) => (
            <button
              key={q}
              onClick={() => onQuery(q)}
              className="px-3 py-1.5 rounded-lg text-xs transition-all duration-150 hover:scale-105"
              style={{
                background: "#1e1e2e",
                border: "1px solid #2a2a3e",
                color: "#94a3b8",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = "#ff6b2b";
                (e.currentTarget as HTMLButtonElement).style.color = "#ff6b2b";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = "#2a2a3e";
                (e.currentTarget as HTMLButtonElement).style.color = "#94a3b8";
              }}
            >
              {q}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}