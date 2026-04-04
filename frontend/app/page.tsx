"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import ChatMessage from "@/components/ChatMessage";
import ProductDiagram from "@/components/ProductDiagram";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://web-production-9e721.up.railway.app";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = useCallback(async (question: string) => {
    if (!question.trim() || loading) return;

    const userMsg: Message = {
      id: Math.random().toString(36).slice(2),
      role: "user",
      content: question.trim(),
    };

    const assistantId = Math.random().toString(36).slice(2);
    const assistantMsg: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
      streaming: true,
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim() }),
      });

      if (!res.ok) {
        throw new Error(`Server error: ${res.status}`);
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let accumulated = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");

        let doneSignaled = false;
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6).trim();
          if (data === "[DONE]") { doneSignaled = true; continue; }
          try {
            const parsed = JSON.parse(data);
            if (parsed.chunk) {
              accumulated += parsed.chunk;
              console.log("RAW:", accumulated.slice(-200)); // last 200 chars
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: accumulated }
                    : m
                )
              );
            }
            if (parsed.error) {
              accumulated += `\n\n_Error: ${parsed.error}_`;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: accumulated }
                    : m
                )
              );
            }
          } catch {}
        }
        if (doneSignaled) break;
      }

      // Mark streaming done
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, streaming: false } : m
        )
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
                ...m,
                content: `_Could not reach the backend. Make sure the server is running._\n\nError: ${err}`,
                streaming: false,
              }
            : m
        )
      );
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }, [loading]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendMessage(input);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const isEmpty = messages.length === 0;

  return (
    <div className="flex h-screen overflow-hidden">
      {/* ─── Left sidebar: product diagram ────────────────────────────────── */}
      <div
        className="hidden lg:flex flex-col w-96 flex-shrink-0 border-r p-4 overflow-y-auto"
        style={{ borderColor: "#1e1e2e", background: "#0a0a0f" }}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 mb-6">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center font-bold text-sm"
            style={{ background: "#ff6b2b", color: "#0a0a0f" }}
          >
            V
          </div>
          <div>
            <p className="text-xs font-mono text-vulcan-muted uppercase tracking-widest">
              Powered by Prox
            </p>
            <h1 className="text-sm font-semibold text-vulcan-text">
              OmniPro 220 Expert
            </h1>
          </div>
        </div>

        <ProductDiagram onQuery={sendMessage} />

        {/* Footer */}
        <div className="mt-auto pt-4 border-t" style={{ borderColor: "#1e1e2e" }}>
          <p className="text-xs text-vulcan-muted font-mono">
            Knowledge base: 51 pages · 3 documents
          </p>
          <p className="text-xs text-vulcan-muted font-mono mt-1">
            Owner Manual · Quick-Start · Selection Chart
          </p>
        </div>
      </div>

      {/* ─── Right: chat ───────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">

        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0"
          style={{ borderColor: "#1e1e2e", background: "#0a0a0f" }}
        >
          <div className="flex items-center gap-3">
            {/* Mobile logo */}
            <div
              className="lg:hidden w-7 h-7 rounded flex items-center justify-center font-bold text-xs"
              style={{ background: "#ff6b2b", color: "#0a0a0f" }}
            >
              V
            </div>
            <div>
              <h1 className="text-sm font-semibold text-vulcan-text">
                Vulcan OmniPro 220
              </h1>
              <p className="text-xs text-vulcan-muted font-mono">
                Technical Expert · Ask anything about your welder
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-green-400" />
            <span className="text-xs text-vulcan-muted font-mono">ONLINE</span>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-6">
          {isEmpty ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div
                className="w-16 h-16 rounded-2xl flex items-center justify-center text-2xl font-bold mb-4"
                style={{ background: "#1e1e2e", color: "#ff6b2b" }}
              >
                V
              </div>
              <h2 className="text-lg font-semibold text-vulcan-text mb-2">
                What do you need to know?
              </h2>
              <p className="text-sm text-vulcan-muted max-w-sm">
                Ask about polarity setup, duty cycles, troubleshooting,
                wire feed, welding tips — anything in the manual.
              </p>
              <div className="mt-6 flex flex-wrap gap-2 justify-center max-w-md">
                {[
                  "MIG duty cycle at 200A/240V?",
                  "TIG polarity — which cable goes where?",
                  "Getting porosity in flux-cored welds",
                  "Best process for thin sheet metal?",
                ].map((q) => (
                  <button
                    key={q}
                    onClick={() => sendMessage(q)}
                    className="px-3 py-2 rounded-lg text-xs transition-all hover:scale-105"
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
          ) : (
            <>
              {messages.map((msg) => (
                <ChatMessage
                  key={msg.id}
                  role={msg.role}
                  content={msg.content}
                  streaming={msg.streaming}
                />
              ))}
              <div ref={bottomRef} />
            </>
          )}
        </div>

        {/* Input */}
        <div
          className="px-6 py-4 border-t flex-shrink-0"
          style={{ borderColor: "#1e1e2e", background: "#0a0a0f" }}
        >
          <form onSubmit={handleSubmit} className="flex gap-3 items-end">
            <div className="flex-1 relative">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about your Vulcan OmniPro 220..."
                disabled={loading}
                rows={1}
                className="w-full px-4 py-3 rounded-xl text-sm resize-none outline-none transition-all"
                style={{
                  background: "#111118",
                  border: `1px solid ${input ? "#ff6b2b" : "#1e1e2e"}`,
                  color: "#e2e8f0",
                  maxHeight: 120,
                  lineHeight: "1.5",
                }}
                onInput={(e) => {
                  const t = e.currentTarget;
                  t.style.height = "auto";
                  t.style.height = `${Math.min(t.scrollHeight, 120)}px`;
                }}
              />
            </div>
            <button
              type="submit"
              disabled={!input.trim() || loading}
              className="flex-shrink-0 w-11 h-11 rounded-xl flex items-center justify-center transition-all duration-150 disabled:opacity-40 hover:scale-105"
              style={{
                background: input.trim() && !loading ? "#ff6b2b" : "#1e1e2e",
                color: input.trim() && !loading ? "#0a0a0f" : "#64748b",
              }}
            >
              {loading ? (
                <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>
              ) : (
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/>
                </svg>
              )}
            </button>
          </form>
          <p className="text-xs text-vulcan-muted mt-2 font-mono text-center">
            Enter to send · Shift+Enter for new line
          </p>
        </div>
      </div>
    </div>
  );
}