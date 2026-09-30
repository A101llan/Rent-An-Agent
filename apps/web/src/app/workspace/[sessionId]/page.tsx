"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Bot, Clock, DollarSign, Send, Server } from "lucide-react";
import { SessionApiPanel } from "@/components/session-api-panel";
import { api, formatPrice, type ApiError, type ExecuteResult } from "@/lib/api";

interface Message {
  role: "user" | "agent";
  content: string;
  output?: unknown;
}

function useCountdown(expiresAt: string | null) {
  const [remaining, setRemaining] = useState<number | null>(null);

  useEffect(() => {
    if (!expiresAt) return;
    const tick = () => {
      const diff = new Date(expiresAt).getTime() - Date.now();
      setRemaining(Math.max(0, Math.floor(diff / 1000)));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [expiresAt]);

  if (remaining === null) return "--:--";
  const m = Math.floor(remaining / 60);
  const s = remaining % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

export default function WorkspacePage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [expired, setExpired] = useState(false);
  const [costMinor, setCostMinor] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { data: session, error: sessionError } = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api.getSession(sessionId),
    refetchInterval: 5000,
    retry: false,
  });

  const { data: executions } = useQuery({
    queryKey: ["executions", sessionId],
    queryFn: () => api.getExecutions(sessionId),
    enabled: !!session,
  });

  const countdown = useCountdown(session?.expires_at ?? null);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) router.push("/login");
  }, [router]);

  useEffect(() => {
    if (sessionError) {
      const err = sessionError as unknown as ApiError;
      if (err.error?.code === "SESSION_EXPIRED") setExpired(true);
    }
  }, [sessionError]);

  useEffect(() => {
    if (countdown === "00:00" && session?.status === "active") {
      setExpired(true);
    }
  }, [countdown, session?.status]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const [pendingApproval, setPendingApproval] = useState<{
    id: string;
    title: string;
    description: string;
    action_type: string;
  } | null>(null);

  const handleSend = useCallback(async () => {
    if (!input.trim() || sending || expired) return;
    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setSending(true);

    try {
      const result: ExecuteResult = await api.execute(sessionId, userMsg);

      if (result.status === "waiting_for_approval" && result.approval_id && result.approval) {
        setPendingApproval({
          id: result.approval_id,
          title: result.approval.title,
          description: result.approval.description,
          action_type: result.approval.details?.keyword as string || "action",
        });
        setMessages((prev) => [
          ...prev,
          {
            role: "agent",
            content: `⏸ Approval required: ${result.approval!.title}\n${result.approval!.description}`,
          },
        ]);
      } else {
        const outputStr =
          typeof result.output === "string"
            ? result.output
            : JSON.stringify(result.output, null, 2);
        setMessages((prev) => [
          ...prev,
          { role: "agent", content: outputStr, output: result.output },
        ]);
        setCostMinor((c) => c + 10);
      }
      queryClient.invalidateQueries({ queryKey: ["executions", sessionId] });
    } catch (err) {
      const apiErr = err as ApiError;
      if (apiErr.error?.code === "SESSION_EXPIRED") {
        setExpired(true);
        setMessages((prev) => [
          ...prev,
          { role: "agent", content: "Session has expired. Runtime terminated." },
        ]);
      } else {
        setMessages((prev) => [
          ...prev,
          { role: "agent", content: `Error: ${apiErr.error?.message || "Execution failed"}` },
        ]);
      }
    } finally {
      setSending(false);
    }
  }, [input, sending, expired, sessionId, queryClient]);

  async function handleApproval(approved: boolean, scope?: "once" | "session") {
    if (!pendingApproval) return;
    try {
      await api.resolveApproval(sessionId, pendingApproval.id, approved, scope);
      setMessages((prev) => [
        ...prev,
        {
          role: "agent",
          content: approved
            ? `✓ Action approved${scope === "session" ? " for this session" : ""}.`
            : "✗ Action denied.",
        },
      ]);
      setPendingApproval(null);
      queryClient.invalidateQueries({ queryKey: ["executions", sessionId] });
    } catch (err) {
      const apiErr = err as ApiError;
      setMessages((prev) => [
        ...prev,
        { role: "agent", content: `Approval error: ${apiErr.error?.message}` },
      ]);
    }
  }

  if (expired) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-24 text-center">
        <h1 className="text-2xl font-bold text-red-400">SESSION EXPIRED</h1>
        <p className="mt-3 max-w-md text-zinc-400">
          Your agent runtime has been securely terminated. Credentials revoked and ephemeral data deleted.
        </p>
        {session && (
          <Link
            href={`/agents/${session.agent_slug}/hire`}
            className="mt-8 rounded-lg bg-indigo-600 px-8 py-3 font-medium hover:bg-indigo-500"
          >
            RENT AGAIN
          </Link>
        )}
      </div>
    );
  }

  if (!session) {
    return <div className="flex flex-1 items-center justify-center text-zinc-400">Loading workspace...</div>;
  }

  const isRunning = session.runtime_status === "running";

  return (
    <div className="flex flex-1 flex-col">
      {/* Header bar */}
      <div className="border-b border-zinc-800 bg-zinc-900/50 px-6 py-3">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div className="flex items-center gap-3">
            <Bot className="h-5 w-5 text-indigo-400" />
            <span className="font-semibold">{session.agent_name}</span>
            <span className="text-zinc-600">·</span>
            <span className="text-sm text-zinc-400">Session</span>
          </div>
          <Link href="/dashboard" className="text-sm text-zinc-400 hover:text-white">
            Dashboard
          </Link>
        </div>
      </div>

      <div className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 gap-0 lg:grid-cols-4">
        {/* Agent info panel */}
        <div className="hidden border-r border-zinc-800 p-6 lg:block">
          <h3 className="text-sm font-medium text-zinc-400">Agent Info</h3>
          <p className="mt-2 font-semibold">{session.agent_name}</p>
          <div className="mt-6">
            <h4 className="text-xs font-medium uppercase text-zinc-500">Capabilities</h4>
            <p className="mt-1 text-sm text-zinc-400">See agent detail page</p>
          </div>
          <div className="mt-6">
            <h4 className="text-xs font-medium uppercase text-zinc-500">Permissions</h4>
            <p className="mt-1 text-sm text-zinc-400">Granted for this session</p>
          </div>
        </div>

        {/* Conversation */}
        <div className="flex flex-col lg:col-span-2">
          <div className="flex-1 overflow-y-auto p-6 space-y-4 min-h-[400px] max-h-[calc(100vh-280px)]">
            {messages.length === 0 && (
              <div className="flex h-full items-center justify-center text-zinc-500 text-sm">
                Send a message to interact with the agent
              </div>
            )}
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] rounded-xl px-4 py-3 text-sm ${
                    msg.role === "user"
                      ? "bg-indigo-600 text-white"
                      : "bg-zinc-800 text-zinc-200"
                  }`}
                >
                  <pre className="whitespace-pre-wrap font-sans">{msg.content}</pre>
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          <div className="border-t border-zinc-800 p-4">
            {pendingApproval && (
              <div className="mb-4 rounded-lg border border-yellow-700/50 bg-yellow-950/30 p-4">
                <p className="font-medium text-yellow-300">{pendingApproval.title}</p>
                <p className="mt-1 text-sm text-zinc-400">{pendingApproval.description}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    onClick={() => handleApproval(true, "once")}
                    className="rounded-lg bg-green-700 px-3 py-1.5 text-sm hover:bg-green-600"
                  >
                    Approve Once
                  </button>
                  <button
                    onClick={() => handleApproval(true, "session")}
                    className="rounded-lg bg-green-900 px-3 py-1.5 text-sm hover:bg-green-800"
                  >
                    Approve For Session
                  </button>
                  <button
                    onClick={() => handleApproval(false)}
                    className="rounded-lg border border-zinc-600 px-3 py-1.5 text-sm hover:bg-zinc-800"
                  >
                    Deny
                  </button>
                </div>
              </div>
            )}
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
                placeholder="Type your message..."
                disabled={sending || expired}
                className="flex-1 rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2.5 text-sm outline-none focus:border-indigo-500 disabled:opacity-50"
              />
              <button
                onClick={handleSend}
                disabled={sending || !input.trim() || expired}
                className="rounded-lg bg-indigo-600 px-4 py-2.5 hover:bg-indigo-500 disabled:opacity-50"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Runtime panel */}
        <div className="border-l border-zinc-800 p-6">
          <h3 className="text-sm font-medium text-zinc-400">Runtime</h3>
          <div className="mt-4 space-y-4">
            <div className="flex items-center gap-2">
              <Server className="h-4 w-4 text-zinc-500" />
              <span
                className={`text-sm font-medium ${isRunning ? "text-green-400" : "text-yellow-400"}`}
              >
                {session.runtime_status?.toUpperCase() || "UNKNOWN"}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-zinc-500" />
              <span className="text-2xl font-mono font-bold">{countdown}</span>
            </div>
            <div className="flex items-center gap-2">
              <DollarSign className="h-4 w-4 text-zinc-500" />
              <span className="text-sm">{formatPrice(costMinor)}</span>
            </div>
          </div>

          <div className="mt-8">
            <h4 className="text-xs font-medium uppercase text-zinc-500">Execution History</h4>
            <div className="mt-2 space-y-2">
              {(executions || []).slice(0, 5).map((ex) => (
                <div key={ex.id} className="rounded border border-zinc-800 p-2 text-xs text-zinc-400">
                  <span className="text-zinc-300">{ex.status}</span>
                  {ex.duration_ms && <span className="ml-2">{ex.duration_ms}ms</span>}
                </div>
              ))}
            </div>
          </div>

          <SessionApiPanel sessionId={sessionId} />
        </div>
      </div>
    </div>
  );
}
