"use client";

import { useEffect, useState } from "react";
import { Check, Copy, Terminal } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function storageKey(sessionId: string) {
  return `agenthub_session_token_${sessionId}`;
}

export function saveSessionToken(sessionId: string, token: string) {
  sessionStorage.setItem(storageKey(sessionId), token);
}

export function getSessionToken(sessionId: string): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(storageKey(sessionId));
}

interface SessionApiPanelProps {
  sessionId: string;
}

export function SessionApiPanel({ sessionId }: SessionApiPanelProps) {
  const [copied, setCopied] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    setToken(getSessionToken(sessionId));
  }, [sessionId]);

  const executeCurl = token
    ? `curl -X POST "${API_URL}/api/v1/sessions/${sessionId}/execute" \\
  -H "X-Session-Token: ${token}" \\
  -H "Content-Type: application/json" \\
  -d '{"input": "Analyze invoice #INV-4421", "context": {"source": "erp"}}'`
    : null;

  async function copy(text: string, label: string) {
    await navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(null), 2000);
  }

  return (
    <div className="mt-8 rounded-lg border border-zinc-800 bg-zinc-950/50 p-4">
      <div className="flex items-center gap-2 text-xs font-medium uppercase text-zinc-500">
        <Terminal className="h-3.5 w-3.5" />
        API Integration
      </div>
      <p className="mt-2 text-xs text-zinc-400">
        Call the agent from your ERP, scripts, or backend using the session token. Scoped to this session only.
      </p>

      <div className="mt-4 space-y-3 text-xs">
        <div>
          <p className="text-zinc-500">Session ID</p>
          <div className="mt-1 flex items-center gap-2">
            <code className="flex-1 truncate rounded bg-zinc-900 px-2 py-1 font-mono text-zinc-300">{sessionId}</code>
            <button
              type="button"
              onClick={() => copy(sessionId, "id")}
              className="rounded border border-zinc-700 p-1.5 hover:bg-zinc-800"
              aria-label="Copy session ID"
            >
              {copied === "id" ? <Check className="h-3.5 w-3.5 text-green-400" /> : <Copy className="h-3.5 w-3.5" />}
            </button>
          </div>
        </div>

        {token ? (
          <div>
            <p className="text-zinc-500">Session token (X-Session-Token)</p>
            <div className="mt-1 flex items-center gap-2">
              <code className="flex-1 truncate rounded bg-zinc-900 px-2 py-1 font-mono text-zinc-300">{token}</code>
              <button
                type="button"
                onClick={() => copy(token, "token")}
                className="rounded border border-zinc-700 p-1.5 hover:bg-zinc-800"
                aria-label="Copy session token"
              >
                {copied === "token" ? <Check className="h-3.5 w-3.5 text-green-400" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
            </div>
          </div>
        ) : (
          <p className="text-zinc-500">
            Session token not in this browser. Hire again or use your saved token from the hire response.
          </p>
        )}

        {executeCurl && (
          <div>
            <p className="text-zinc-500">Execute example</p>
            <pre className="mt-1 overflow-x-auto rounded bg-zinc-900 p-2 font-mono text-[10px] leading-relaxed text-zinc-300">
              {executeCurl}
            </pre>
            <button
              type="button"
              onClick={() => copy(executeCurl, "curl")}
              className="mt-2 text-indigo-400 hover:text-indigo-300"
            >
              {copied === "curl" ? "Copied" : "Copy curl command"}
            </button>
          </div>
        )}
      </div>

      <a
        href={`${API_URL}/docs#/rentals/hire_agent_api_v1_rentals_hire_post`}
        target="_blank"
        rel="noreferrer"
        className="mt-4 inline-block text-xs text-indigo-400 hover:text-indigo-300"
      >
        Full API docs →
      </a>
    </div>
  );
}
