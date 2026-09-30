"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Check, Download, Loader2 } from "lucide-react";
import { api, formatPrice, type ApiError, type EmbedSnippet } from "@/lib/api";
import { EmbedSetupPanel, saveEmbedKey } from "@/components/embed-setup-panel";
import { saveSessionToken } from "@/components/session-api-panel";
import {
  LOCAL_RUNTIME_DOWNLOAD_URL,
  LocalRuntimeBadge,
  LocalRuntimeSetupPanel,
  getLocalClaim,
  isLocalAgent,
  isLocalSession,
  type LocalClaim,
} from "@/components/local-runtime-panel";

const DURATIONS = [
  { minutes: 15, label: "15 minutes" },
  { minutes: 30, label: "30 minutes" },
  { minutes: 60, label: "1 hour" },
  { minutes: 120, label: "2 hours" },
];

const LOCAL_PROVISIONING_STEPS = ["Rental authorized", "Permissions granted", "Session ready"];

export default function HirePageContent() {
  const { slug } = useParams<{ slug: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const isDemo = searchParams.get("demo") === "1";

  const [duration, setDuration] = useState(30);
  const [step, setStep] = useState<"select" | "provisioning" | "ready">("select");
  const [provisioningSteps, setProvisioningSteps] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [embedSnippet, setEmbedSnippet] = useState<EmbedSnippet | null>(null);
  const [localClaim, setLocalClaim] = useState<LocalClaim | null>(null);

  const { data } = useQuery({
    queryKey: ["agent", slug],
    queryFn: () => api.getAgent(slug),
  });

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) router.push(`/login?redirect=/agents/${slug}/hire`);
  }, [router, slug]);

  if (!data) {
    return <div className="flex flex-1 items-center justify-center py-24 text-zinc-400">Loading...</div>;
  }

  const { agent } = data;
  const plan = agent.pricing_plans[0];
  const localAgent = isLocalAgent(agent);
  const costMinor =
    plan.pricing_model === "per_hour"
      ? Math.round((plan.price_minor * duration) / 60)
      : plan.pricing_model === "per_minute"
        ? plan.price_minor * duration
        : plan.price_minor;

  async function handleAuthorize() {
    if (!plan) return;
    setError(null);
    setStep("provisioning");
    const steps = localAgent
      ? LOCAL_PROVISIONING_STEPS
      : [
          "Rental authorized",
          "Permissions granted",
          "Runtime created",
          "Agent started",
        ];
    for (let i = 0; i < steps.length; i++) {
      await new Promise((r) => setTimeout(r, 600));
      setProvisioningSteps(steps.slice(0, i + 1));
    }

    try {
      const idempotencyKey = `hire_${slug}_${Date.now()}`;
      if (localAgent) {
        // Local agents: one-call hire; AgentHub Local binds with the returned session ID + session token.
        const hire = await api.hireAgent(
          {
            agent_slug: slug,
            pricing_plan_id: plan.id,
            duration_minutes: isDemo ? 5 : duration,
          },
          idempotencyKey,
        );
        setLocalClaim(getLocalClaim(hire));
        setSessionId(hire.session.id);
        setStep("ready");
        return;
      }
      const rental = await api.createRental(
        {
          agent_slug: slug,
          pricing_plan_id: plan.id,
          duration_minutes: isDemo ? 5 : duration,
        },
        idempotencyKey,
      );
      const session = await api.createSession(rental.id, `session_${rental.id}`);
      if (session.session_token) {
        saveSessionToken(session.id, session.session_token);
      }
      if (session.embed) {
        saveEmbedKey(session.id, session.embed.api_key);
        setEmbedSnippet(session.embed);
      }
      if (isLocalSession({ session })) {
        setLocalClaim(getLocalClaim({ session }));
      }
      setSessionId(session.id);
      setStep("ready");
    } catch (err) {
      const apiErr = err as ApiError;
      setError(apiErr.error?.message || "Failed to start session");
      setStep("select");
    }
  }

  if (step === "ready" && sessionId && localClaim) {
    return (
      <div className="mx-auto max-w-xl px-6 py-16">
        <div className="text-center">
          <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-green-900/30">
            <Check className="h-8 w-8 text-green-400" />
          </div>
          <h1 className="text-2xl font-bold">Rental ready</h1>
          <p className="mt-2 text-zinc-400">
            {agent.name} runs on your device with AgentHub Local. Download it, then paste your session ID and session token.
          </p>
        </div>

        <LocalRuntimeSetupPanel claim={localClaim} />

        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-center">
          <a
            href={LOCAL_RUNTIME_DOWNLOAD_URL}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-6 py-3 text-center text-sm font-medium hover:bg-indigo-500"
          >
            <Download className="h-4 w-4" />
            Download AgentHub Local
          </a>
        </div>
      </div>
    );
  }

  if (step === "ready" && sessionId) {
    return (
      <div className="mx-auto max-w-xl px-6 py-16">
        <div className="text-center">
          <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-green-900/30">
            <Check className="h-8 w-8 text-green-400" />
          </div>
          <h1 className="text-2xl font-bold">Agent ready</h1>
          <p className="mt-2 text-zinc-400">
            Add the widget to your own system, or try it here in the AgentHub workspace.
          </p>
        </div>

        {embedSnippet && <EmbedSetupPanel embed={embedSnippet} />}

        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-center">
          {embedSnippet && (
            <a
              href={embedSnippet.demo_page_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-lg border border-zinc-600 px-6 py-3 text-center text-sm font-medium hover:bg-zinc-900"
            >
              Preview embed demo
            </a>
          )}
          <Link
            href={`/workspace/${sessionId}`}
            className="rounded-lg bg-indigo-600 px-6 py-3 text-center text-sm font-medium hover:bg-indigo-500"
          >
            Open AgentHub workspace
          </Link>
        </div>
      </div>
    );
  }

  if (step === "provisioning") {
    return (
      <div className="mx-auto max-w-lg px-6 py-24">
        <h1 className="text-2xl font-bold text-center">Preparing your agent...</h1>
        <div className="mt-8 space-y-3">
          {(localAgent
            ? LOCAL_PROVISIONING_STEPS
            : ["Rental authorized", "Permissions granted", "Runtime created", "Agent started"]
          ).map((s) => (
            <div key={s} className="flex items-center gap-3">
              {provisioningSteps.includes(s) ? (
                <Check className="h-5 w-5 text-green-400" />
              ) : (
                <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
              )}
              <span className={provisioningSteps.includes(s) ? "text-zinc-200" : "text-zinc-500"}>{s}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-lg px-6 py-12">
      <Link href={`/agents/${slug}`} className="text-sm text-zinc-400 hover:text-white">
        ← Back to {agent.name}
      </Link>

      <h1 className="mt-6 text-2xl font-bold">Hire {agent.name}</h1>
      {localAgent && <LocalRuntimeBadge className="mt-3" />}

      {error && (
        <div className="mt-4 rounded-lg border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      <section className="mt-8">
        <h2 className="text-sm font-medium text-zinc-400">Rental duration</h2>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {DURATIONS.map((d) => (
            <button
              key={d.minutes}
              onClick={() => setDuration(d.minutes)}
              className={`rounded-lg border px-4 py-3 text-sm ${
                duration === d.minutes
                  ? "border-indigo-500 bg-indigo-600/10 text-indigo-300"
                  : "border-zinc-700 hover:border-zinc-600"
              }`}
            >
              {d.label}
            </button>
          ))}
        </div>
      </section>

      <section className="mt-8 rounded-xl border border-zinc-800 p-6">
        <div className="flex justify-between">
          <span className="text-zinc-400">Price</span>
          <span className="text-xl font-bold">{formatPrice(costMinor)}</span>
        </div>
        <div className="mt-4 border-t border-zinc-800 pt-4">
          <p className="text-sm font-medium text-zinc-400">Permissions</p>
          <ul className="mt-2 space-y-1">
            {(agent.permissions.length ? agent.permissions : ["No special permissions"]).map((p) => (
              <li key={p} className="flex items-center gap-2 text-sm">
                <Check className="h-3.5 w-3.5 text-green-400" />
                {p.replace(".", " — ")}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <button
        onClick={handleAuthorize}
        className="mt-8 w-full rounded-lg bg-indigo-600 py-3 font-medium hover:bg-indigo-500"
      >
        AUTHORIZE & START
      </button>
    </div>
  );
}
