"use client";

import { useSearchParams } from "next/navigation";
import { useEffect } from "react";

export default function EmbedDemoPage() {
  const params = useSearchParams();
  const apiKey = params.get("key") || "";

  useEffect(() => {
    if (!apiKey || document.getElementById("agenthub-embed-loader")) return;

    const s = document.createElement("script");
    s.id = "agenthub-embed-loader";
    s.src = "/embed.js";
    s.async = true;
    s.setAttribute("data-api-key", apiKey);
    s.setAttribute("data-agenthub-url", window.location.origin);
    s.setAttribute(
      "data-agenthub-api",
      process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
    );
    document.body.appendChild(s);
  }, [apiKey]);

  return (
    <div className="min-h-dvh bg-zinc-900 p-8">
      <div className="mx-auto max-w-2xl">
        <h1 className="text-xl font-bold">Your system (demo)</h1>
        <p className="mt-2 text-sm text-zinc-400">
          This page simulates your ERP or internal app. The AgentHub widget appears at the bottom-right —
          the same experience your team gets after pasting one script tag.
        </p>
        <div className="mt-8 rounded-xl border border-zinc-700 bg-zinc-950 p-6 text-sm text-zinc-500">
          <p>Invoice #INV-4421 — pending review</p>
          <p className="mt-2">Invoice #INV-4422 — approved</p>
        </div>
      </div>
    </div>
  );
}
