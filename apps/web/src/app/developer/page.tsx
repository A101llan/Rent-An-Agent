"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { api, formatPrice } from "@/lib/api";

export default function DeveloperDashboardPage() {
  const router = useRouter();

  const { data: user } = useQuery({ queryKey: ["me"], queryFn: () => api.me() });
  const { data: stats } = useQuery({
    queryKey: ["dev-stats"],
    queryFn: () => api.getDeveloperStats(),
    enabled: user?.role === "developer" || user?.role === "admin",
  });
  const { data: agents } = useQuery({
    queryKey: ["dev-agents"],
    queryFn: () => api.listDeveloperAgents(),
    enabled: user?.role === "developer" || user?.role === "admin",
  });

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) router.push("/login");
  }, [router]);

  return (
    <div className="mx-auto max-w-7xl px-6 py-12">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Developer Dashboard</h1>
          <p className="mt-2 text-zinc-400">Manage your published agents</p>
        </div>
        <Link
          href="/developer/agents/new"
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500"
        >
          Create Agent
        </Link>
      </div>

      {stats && (
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {[
            { label: "Published Agents", value: stats.published_agents },
            { label: "Active Rentals", value: stats.active_rentals },
            { label: "Executions", value: stats.total_executions },
            { label: "Revenue", value: formatPrice(stats.total_revenue_minor) },
            { label: "Avg Rating", value: stats.avg_rating.toFixed(1) },
          ].map((s) => (
            <div key={s.label} className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
              <p className="text-xs text-zinc-500">{s.label}</p>
              <p className="mt-1 text-xl font-bold">{s.value}</p>
            </div>
          ))}
        </div>
      )}

      <section className="mt-10">
        <h2 className="text-lg font-semibold">Your Agents</h2>
        <div className="mt-4 space-y-3">
          {(agents || []).map((a) => (
            <div key={a.id} className="flex items-center justify-between rounded-lg border border-zinc-800 p-4">
              <div>
                <p className="font-medium">{a.name}</p>
                <p className="text-sm text-zinc-500 capitalize">{a.status} · ★ {a.avg_rating} ({a.review_count})</p>
              </div>
              <Link href={`/agents/${a.slug}`} className="text-sm text-indigo-400 hover:text-indigo-300">
                View →
              </Link>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
