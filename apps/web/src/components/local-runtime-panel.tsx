"use client";

import { useState } from "react";
import { Check, Copy, Laptop } from "lucide-react";
import type { AgentDetail, HireResponse } from "@/lib/api";

// Installer served from apps/web/public/downloads; override with a hosted URL via env.
export const LOCAL_RUNTIME_DOWNLOAD_URL =
  process.env.NEXT_PUBLIC_LOCAL_RUNTIME_DOWNLOAD_URL || "/downloads/AgentHubLocalRuntimeSetup-0.1.0.exe";
export const LOCAL_RUNTIME_VERSION = "0.1.0";
export const LOCAL_RUNTIME_SIZE_LABEL = "19 MB";

export function isLocalAgent(agent: Pick<AgentDetail, "manifest">): boolean {
  return agent.manifest?.runtime?.type === "local";
}

export interface LocalClaim {
  sessionId: string;
  claimToken: string | null;
}

type HireLike = Pick<HireResponse, "session"> & Partial<Pick<HireResponse, "session_token" | "runtime_provider">>;

/**
 * The only place that reads local-runtime fields off a hire/session response, so the
 * shape can be adjusted in one spot while the API settles.
 *   local flag:  session.runtime_provider === "local" (fallback: top-level runtime_provider)
 *   session id:  session.id
 *   token:       session.session_token (pinned), fallback top-level session_token
 * MVP: the sidecar binds with the existing session token; claim codes / lease certs come later.
 */
export function isLocalSession(res: HireLike): boolean {
  return (res.session.runtime_provider ?? res.runtime_provider) === "local";
}

export function getLocalClaim(res: HireLike): LocalClaim {
  return {
    sessionId: res.session.id,
    claimToken: res.session.session_token || res.session_token || null,
  };
}

export function LocalRuntimeBadge({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border border-emerald-800 bg-emerald-950/40 px-2.5 py-1 text-xs font-medium text-emerald-300 ${className}`}
    >
      <Laptop className="h-3.5 w-3.5" />
      Runs on your device
    </span>
  );
}

export function LocalRuntimeSetupPanel({ claim }: { claim: LocalClaim }) {
  const [copied, setCopied] = useState<string | null>(null);

  async function copy(text: string, label: string) {
    await navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(null), 2000);
  }

  return (
    <div className="mt-8 rounded-xl border border-indigo-800/50 bg-indigo-950/20 p-6 text-left">
      <h2 className="text-lg font-semibold text-indigo-200">Run it on your device</h2>
      <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-zinc-400">
        <li>Install AgentHub Local on your Windows PC.</li>
        <li>Paste your session ID and session token into AgentHub Local.</li>
        <li>Pick your files — they stay on your computer.</li>
      </ol>
      <p className="mt-3 text-xs text-zinc-500">
        Windows 10/11 only. Requires Ollama. v{LOCAL_RUNTIME_VERSION}, {LOCAL_RUNTIME_SIZE_LABEL}. Windows may warn about an
        unknown publisher: choose More info, then Run anyway.
      </p>

      {claim.claimToken ? (
        <div className="mt-4 space-y-3">
          <div>
            <p className="text-xs font-medium uppercase text-zinc-500">Session ID</p>
            <div className="mt-1 flex items-center gap-2">
              <code className="flex-1 truncate rounded bg-zinc-900 px-2 py-2 font-mono text-xs text-zinc-300">
                {claim.sessionId}
              </code>
              <button
                type="button"
                onClick={() => copy(claim.sessionId, "id")}
                className="rounded border border-zinc-700 p-2 hover:bg-zinc-800"
                aria-label="Copy session ID"
              >
                {copied === "id" ? <Check className="h-4 w-4 text-green-400" /> : <Copy className="h-4 w-4" />}
              </button>
            </div>
          </div>
          <div>
            <p className="text-xs font-medium uppercase text-zinc-500">Session token</p>
            <div className="mt-1 flex items-center gap-2">
              <code className="flex-1 truncate rounded bg-zinc-900 px-2 py-2 font-mono text-xs text-zinc-300">
                {claim.claimToken}
              </code>
              <button
                type="button"
                onClick={() => copy(claim.claimToken!, "token")}
                className="rounded border border-zinc-700 p-2 hover:bg-zinc-800"
                aria-label="Copy session token"
              >
                {copied === "token" ? <Check className="h-4 w-4 text-green-400" /> : <Copy className="h-4 w-4" />}
              </button>
            </div>
          </div>
          <p className="text-xs text-zinc-500">Keep this private: it grants access to this rental until it ends.</p>
        </div>
      ) : (
        <div className="mt-4 rounded-lg border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          Your rental is active, but we couldn&apos;t get a session token for AgentHub Local. Please don&apos;t hire
          again — contact support with session ID {claim.sessionId}.
        </div>
      )}
    </div>
  );
}
