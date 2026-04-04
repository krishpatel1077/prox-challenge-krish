import type { Config } from "tailwindcss";
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        mono: ["'JetBrains Mono'", "monospace"],
        sans: ["'DM Sans'", "system-ui", "sans-serif"],
      },
      colors: {
        vulcan: {
          bg: "#0a0a0f",
          surface: "#111118",
          border: "#1e1e2e",
          accent: "#ff6b2b",
          blue: "#3b82f6",
          green: "#22c55e",
          text: "#e2e8f0",
          muted: "#64748b",
        },
      },
    },
  },
  plugins: [],
};
export default config;
