"use client";

import { useRef, useState } from "react";
import ChatInput from "./components/ChatInput";
import ResultCard from "./components/ResultCard";
import { DispatchResult } from "./types";

interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  model?: string;
  sources?: string[];
  dispatch?: DispatchResult;
}

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const nextId = useRef(0);

  async function handleSend(message: string) {
    const userId = ++nextId.current;
    const userMsg: ChatMessage = { id: userId, role: "user", text: message };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });

      if (!res.ok) {
        const errText = await res.text();
        setMessages((prev) => [
          ...prev,
          { id: ++nextId.current, role: "assistant", text: `Fout: ${res.status} ${errText}` },
        ]);
        return;
      }

      const data = await res.json();

      if (data.type === "qa") {
        setMessages((prev) => [
          ...prev,
          {
            id: ++nextId.current,
            role: "assistant",
            text: data.response,
            model: data.model,
            sources: data.sources,
          },
        ]);
      } else if (data.type === "dispatch") {
        setMessages((prev) => [
          ...prev,
          {
            id: ++nextId.current,
            role: "assistant",
            text: "",
            model: data.model,
            sources: data.sources,
            dispatch: data.response as DispatchResult,
          },
        ]);
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        { id: ++nextId.current, role: "assistant", text: "Verbindingsfout. Probeer het opnieuw." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 flex flex-col">
      <header className="border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-6 py-4">
        <div className="mx-auto max-w-3xl flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">DRAAD</h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Dispatch &amp; Regelcontrole voor Alliander Dienst
            </p>
          </div>
          <span className="rounded-full bg-orange-100 px-3 py-1 text-xs font-semibold text-orange-700 dark:bg-orange-900/30 dark:text-orange-400">
            BEI-BLS
          </span>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto max-w-3xl space-y-4">
          {messages.map((m) => (
            <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm ${
                  m.role === "user"
                    ? "bg-orange-500 text-white rounded-br-sm"
                    : "bg-zinc-100 text-zinc-900 rounded-bl-sm dark:bg-zinc-800 dark:text-zinc-100"
                }`}
              >
                {m.dispatch ? (
                  <ResultCard result={m.dispatch} />
                ) : (
                  <div className="whitespace-pre-wrap">{m.text}</div>
                )}
                {m.model && (
                  <p className="mt-2 text-xs opacity-50">model: {m.model}</p>
                )}
                {m.sources && m.sources.length > 0 && (
                  <p className="mt-1 text-xs opacity-50">
                    bronnen: {m.sources.join(", ")}
                  </p>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex justify-start">
              <div className="rounded-2xl rounded-bl-sm bg-zinc-100 px-4 py-3 dark:bg-zinc-800">
                <div className="flex gap-1">
                  <span className="h-2 w-2 animate-bounce rounded-full bg-orange-400" style={{ animationDelay: "0ms" }} />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-orange-400" style={{ animationDelay: "150ms" }} />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-orange-400" style={{ animationDelay: "300ms" }} />
                </div>
              </div>
            </div>
          )}
        </div>
      </main>

      <footer className="border-t border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-4 py-4">
        <div className="mx-auto max-w-3xl">
          <ChatInput onSend={handleSend} disabled={loading} />
          <p className="mt-2 text-center text-xs text-zinc-400 dark:text-zinc-600">
            Stel een vraag over BEI-BLS, of beschrijf een storing om een dekkingsanalyse te starten.
          </p>
        </div>
      </footer>
    </div>
  );
}
