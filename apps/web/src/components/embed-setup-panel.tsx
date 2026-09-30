"use client";

import { Check, Copy, ExternalLink } from "lucide-react";
import { useState } from "react";

export interface EmbedSnippet {
  api_key: string;
  embed_html: string;
  embed_script: string;
  demo_page_url: string;
}

export function EmbedSetupPanel({ embed }: { embed: EmbedSnippet }) {
  const [copied, setCopied] = useState<string | null>(null);

  async function copy(text: string, label: string) {
    await navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(null), 2000);
  }

  return (
    <div className="mt-8 rounded-xl border border-indigo-800/50 bg-indigo-950/20 p-6 text-left">
      <h2 className="text-lg font-semibold text-indigo-200">Use in your system</h2>
      <p className="mt-2 text-sm text-zinc-400">
        Paste one snippet into your ERP, portal, or internal tool. A chat widget appears at the bottom of
        the screen — your data stays in your environment; the agent runs through your rental session.
      </p>

      <div className="mt-4">
        <p className="text-xs font-medium uppercase text-zinc-500">API key</p>
        <div className="mt-1 flex items-center gap-2">
          <code className="flex-1 truncate rounded bg-zinc-900 px-2 py-2 font-mono text-xs text-zinc-300">
            {embed.api_key}
          </code>
          <button
            type="button"
            onClick={() => copy(embed.api_key, "key")}
            className="rounded border border-zinc-700 p-2 hover:bg-zinc-800"
          >
            {copied === "key" ? <Check className="h-4 w-4 text-green-400" /> : <Copy className="h-4 w-4" />}
          </button>
        </div>
      </div>

      <div className="mt-4">
        <p className="text-xs font-medium uppercase text-zinc-500">Embed snippet</p>
        <pre className="mt-1 overflow-x-auto rounded bg-zinc-900 p-3 font-mono text-[11px] text-zinc-300">
          {embed.embed_html}
        </pre>
        <button
          type="button"
          onClick={() => copy(embed.embed_html, "html")}
          className="mt-2 text-sm text-indigo-400 hover:text-indigo-300"
        >
          {copied === "html" ? "Copied!" : "Copy snippet"}
        </button>
      </div>

      <a
        href={embed.demo_page_url}
        target="_blank"
        rel="noreferrer"
        className="mt-4 inline-flex items-center gap-2 text-sm text-indigo-400 hover:text-indigo-300"
      >
        Preview in a demo app
        <ExternalLink className="h-3.5 w-3.5" />
      </a>
    </div>
  );
}

export function saveEmbedKey(sessionId: string, apiKey: string) {
  sessionStorage.setItem(`agenthub_embed_key_${sessionId}`, apiKey);
}
