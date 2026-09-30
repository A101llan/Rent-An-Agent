"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Bot, Send } from "lucide-react";

interface Question {
  id: string;
  question: string;
  placeholder?: string;
}

interface Bootstrap {
  agent_name: string;
  onboarding_complete: boolean;
  questions: Question[];
  welcome_message: string | null;
}

interface Message {
  role: "user" | "agent";
  content: string;
}

export default function EmbedChatPage() {
  const params = useSearchParams();
  const apiKey = params.get("key") || "";
  const apiBase = (params.get("api") || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const headers = useCallback(
    () => ({
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    }),
    [apiKey],
  );

  useEffect(() => {
    if (!apiKey) {
      setError("Missing embed API key.");
      return;
    }
    fetch(`${apiBase}/api/v1/embed/bootstrap`, { headers: headers() })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).error?.message || r.statusText);
        return r.json();
      })
      .then(setBootstrap)
      .catch((e) => setError(e.message));
  }, [apiKey, apiBase, headers]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, bootstrap]);

  async function submitOnboarding() {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${apiBase}/api/v1/embed/onboarding`, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ answers }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error?.message || "Onboarding failed");
      setBootstrap((b) =>
        b ? { ...b, onboarding_complete: true, welcome_message: data.welcome_message, questions: [] } : b,
      );
      setMessages([{ role: "agent", content: data.welcome_message }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Onboarding failed");
    } finally {
      setLoading(false);
    }
  }

  async function sendMessage() {
    if (!input.trim() || loading) return;
    const text = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${apiBase}/api/v1/embed/chat`, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ message: text }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error?.message || "Send failed");
      setMessages((m) => [...m, { role: "agent", content: data.reply }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Send failed");
    } finally {
      setLoading(false);
    }
  }

  if (error && !bootstrap) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-sm text-red-400">{error}</div>
    );
  }

  if (!bootstrap) {
    return <div className="flex h-full items-center justify-center text-sm text-zinc-500">Loading agent…</div>;
  }

  return (
    <div className="flex h-full flex-col bg-zinc-950 text-zinc-100">
      <div className="flex items-center gap-2 border-b border-zinc-800 px-4 py-3">
        <Bot className="h-4 w-4 text-indigo-400" />
        <span className="text-sm font-medium">{bootstrap.agent_name}</span>
        <span className="ml-auto text-xs text-zinc-500">Runs in your system</span>
      </div>

      {!bootstrap.onboarding_complete ? (
        <div className="flex flex-1 flex-col overflow-y-auto p-4">
          <p className="text-sm text-zinc-300">
            Before we start, I have a few quick questions so I can work in your context.
          </p>
          <div className="mt-4 space-y-4">
            {bootstrap.questions.map((q) => (
              <label key={q.id} className="block">
                <span className="text-xs font-medium text-zinc-400">{q.question}</span>
                <input
                  value={answers[q.id] || ""}
                  onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
                  placeholder={q.placeholder}
                  className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                />
              </label>
            ))}
          </div>
          {error && <p className="mt-3 text-xs text-red-400">{error}</p>}
          <button
            type="button"
            disabled={loading}
            onClick={submitOnboarding}
            className="mt-6 rounded-lg bg-indigo-600 py-2.5 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
          >
            {loading ? "Saving…" : "Continue to chat"}
          </button>
        </div>
      ) : (
        <>
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {messages.length === 0 && bootstrap.welcome_message && (
              <div className="rounded-xl bg-zinc-900 px-3 py-2 text-sm whitespace-pre-wrap">
                {bootstrap.welcome_message.replace(/\*\*/g, "")}
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[90%] rounded-xl px-3 py-2 text-sm whitespace-pre-wrap ${
                    m.role === "user" ? "bg-indigo-600 text-white" : "bg-zinc-800 text-zinc-200"
                  }`}
                >
                  {m.content.replace(/\*\*/g, "")}
                </div>
              </div>
            ))}
            <div ref={endRef} />
          </div>
          {error && <p className="px-4 text-xs text-red-400">{error}</p>}
          <div className="border-t border-zinc-800 p-3">
            <div className="flex gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                placeholder="Ask your agent…"
                disabled={loading}
                className="flex-1 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
              <button
                type="button"
                onClick={sendMessage}
                disabled={loading || !input.trim()}
                className="rounded-lg bg-indigo-600 px-3 hover:bg-indigo-500 disabled:opacity-50"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
