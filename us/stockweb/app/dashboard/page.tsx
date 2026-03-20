"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { AuthProvider, useAuth, apiFetch } from "@/lib/auth";
import Header from "@/components/Header";
import Leaderboard, { TickerRow } from "@/components/Leaderboard";
import TickerPanel from "@/components/TickerPanel";

function DashboardInner() {
  const { token } = useAuth();
  const router    = useRouter();

  const [rows,       setRows]       = useState<TickerRow[]>([]);
  const [selected,   setSelected]   = useState<string | null>(null);
  const [loading,    setLoading]    = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [status,     setStatus]     = useState<any>(null);
  const [error,      setError]      = useState("");
  const [ready,      setReady]      = useState(false);

  // Tunggu hydration selesai, baru cek token
  useEffect(() => {
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    if (!token) {
      router.replace("/");
      return;
    }
    fetchData();
  }, [ready, token]);

  const fetchData = useCallback(async (silent = false) => {
    if (!token) return;
    if (!silent) setLoading(true);
    else setRefreshing(true);
    setError("");
    try {
      const [lb, st] = await Promise.all([
        apiFetch("/api/leaderboard?limit=500", token),
        apiFetch("/api/status", token),
      ]);
      setRows(lb.data ?? []);
      setStatus(st);
    } catch (e: any) {
      // Kalau 401, logout dan redirect
      if (e.message?.includes("401")) {
        localStorage.removeItem("ssd_token");
        router.replace("/");
        return;
      }
      setError(e.message ?? "Failed to load");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token, router]);

  // Auto refresh setiap 60 detik
  useEffect(() => {
    if (!token) return;
    const id = setInterval(() => fetchData(true), 60_000);
    return () => clearInterval(id);
  }, [fetchData, token]);

  // Belum hydrate — jangan render apa-apa dulu
  if (!ready) return null;

  // Belum ada token — jangan render, tunggu redirect
  if (!token) return null;

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-bg">
      <Header
        tickerCount={status?.tickers_loaded ?? 0}
        lastUpdate={status?.last_reload ?? null}
        marketOpen={status?.market_open ?? false}
        onRefresh={() => fetchData(true)}
        refreshing={refreshing}
      />

      {error && (
        <div className="px-4 py-2 bg-bear-dim border-b border-bear/20 text-bear text-xs font-mono">
          ⚠ {error} — <button onClick={() => fetchData()} className="underline">retry</button>
        </div>
      )}

      {loading ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-3">
            <div className="text-muted text-xs tracking-widest cursor-blink uppercase">Loading data</div>
            <div className="flex justify-center gap-1">
              {[0,1,2,3,4].map(i => (
                <div key={i} className="w-1 h-4 bg-accent/40 rounded-full"
                  style={{ animation: `glow-pulse 1s ease-in-out ${i*0.15}s infinite` }} />
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="flex flex-1 overflow-hidden">
          <div className={`flex-1 overflow-hidden transition-all duration-300 ${selected ? "max-w-[calc(100%-360px)]" : ""}`}>
            <Leaderboard
              data={rows}
              onSelect={t => setSelected(s => s === t ? null : t)}
              selected={selected}
            />
          </div>

          {selected && token && (
            <div className="w-[360px] flex-shrink-0 overflow-hidden fade-up">
              <TickerPanel
                ticker={selected}
                token={token}
                onClose={() => setSelected(null)}
              />
            </div>
          )}
        </div>
      )}

      {!loading && rows.length > 0 && (
        <div className="flex items-center gap-6 px-4 py-2 bg-surface border-t border-border text-xs font-mono flex-shrink-0">
          <span className="text-muted">
            <span className="text-bull">▲ {rows.filter(r => r.total > 0).length}</span>
            <span className="mx-2 text-muted/40">|</span>
            <span className="text-bear">▼ {rows.filter(r => r.total < 0).length}</span>
            <span className="mx-2 text-muted/40">|</span>
            <span>— {rows.filter(r => r.total === 0).length}</span>
          </span>
          <span className="text-muted">
            AVG <span className="text-text">{(rows.reduce((s,r) => s + r.total, 0) / rows.length).toFixed(2)}</span>
          </span>
          <span className="text-muted">
            TOP <span className="text-bull">{rows[0]?.ticker} {rows[0]?.total?.toFixed(1)}</span>
          </span>
          <span className="text-muted ml-auto text-muted/60">
            {status?.server_time ? new Date(status.server_time).toLocaleTimeString() : ""}
          </span>
        </div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  return <AuthProvider><DashboardInner /></AuthProvider>;
}
