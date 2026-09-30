"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { api, formatPrice } from "@/lib/api";

export default function DashboardPage() {
  const router = useRouter();

  const { data: user } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.me(),
  });

  const { data: rentals } = useQuery({
    queryKey: ["rentals"],
    queryFn: () => api.listRentals(),
    enabled: !!user,
  });

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) router.push("/login");
  }, [router]);

  const activeRentals = rentals?.filter((r) => r.status === "active") || [];
  const totalSpent = rentals?.reduce((sum, r) => sum + r.total_cost_minor, 0) || 0;

  return (
    <div className="mx-auto max-w-7xl px-6 py-12">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <p className="mt-2 text-zinc-400">Welcome back, {user?.display_name || user?.email}</p>

      <div className="mt-8 grid gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-6">
          <p className="text-sm text-zinc-400">Active Rentals</p>
          <p className="mt-2 text-3xl font-bold">{activeRentals.length}</p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-6">
          <p className="text-sm text-zinc-400">Total Rentals</p>
          <p className="mt-2 text-3xl font-bold">{rentals?.length || 0}</p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-6">
          <p className="text-sm text-zinc-400">Total Spent</p>
          <p className="mt-2 text-3xl font-bold">{formatPrice(totalSpent)}</p>
        </div>
      </div>

      <section className="mt-10">
        <h2 className="text-lg font-semibold">Recent Rentals</h2>
        <div className="mt-4 space-y-3">
          {(rentals || []).length === 0 ? (
            <p className="text-zinc-500">No rentals yet. <Link href="/marketplace" className="text-indigo-400">Browse marketplace</Link></p>
          ) : (
            rentals?.map((r) => (
              <div key={r.id} className="flex items-center justify-between rounded-lg border border-zinc-800 p-4">
                <div>
                  <p className="font-medium">{r.agent_name}</p>
                  <p className="text-sm text-zinc-500 capitalize">{r.status} · {formatPrice(r.total_cost_minor)}</p>
                </div>
                {r.status === "active" && (
                  <Link
                    href={`/agents/${r.agent_slug}/hire`}
                    className="rounded-lg bg-indigo-600 px-4 py-2 text-sm hover:bg-indigo-500"
                  >
                    New Session
                  </Link>
                )}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
