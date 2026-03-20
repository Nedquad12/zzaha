"use client";
import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";
import { LogOut, RefreshCw, Wifi, WifiOff } from "lucide-react";

interface Props {
  tickerCount: number;
  lastUpdate:  string | null;
  marketOpen:  boolean;
  onRefresh:   () => void;
  refreshing:  boolean;
}

export default function Header({ tickerCount, lastUpdate, marketOpen, onRefresh, refreshing }: Props) {
  const { logout } = useAuth();
  const router = useRouter();

  const handleLogout = () => { logout(); router.replace("/"); };

  const fmtTime = (iso: string | null) => {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
    } catch { return "—"; }
  };

  return (
    <header className="flex items-center justify-between px-5 py-3 bg-surface border-b border-border flex-shrink-0">

      {/* Left: logo + status */}
      <div className="flex items-center gap-5">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full glow-pulse ${marketOpen ? "bg-bull" : "bg-muted"}`} />
          <span className="ticker-tag text-sm font-bold text-text">SSD</span>
        </div>

        <div className="flex items-center gap-1.5 text-xs text-muted">
          {marketOpen ? (
            <><Wifi className="w-3 h-3 text-bull" /><span className="text-bull">MARKET OPEN</span></>
          ) : (
            <><WifiOff className="w-3 h-3" /><span>MARKET CLOSED</span></>
          )}
        </div>

        <div className="hidden sm:flex items-center gap-4 text-xs text-muted">
          <span><span className="text-dim">TICKERS</span> <span className="text-text font-mono">{tickerCount}</span></span>
          <span><span className="text-dim">UPDATED</span> <span className="text-text font-mono">{fmtTime(lastUpdate)}</span></span>
        </div>
      </div>

      {/* Right: actions */}
      <div className="flex items-center gap-2">
        <button onClick={onRefresh} disabled={refreshing}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-border hover:border-accent/40 text-muted hover:text-accent text-xs font-mono transition-all disabled:opacity-40">
          <RefreshCw className={`w-3 h-3 ${refreshing ? "animate-spin" : ""}`} />
          <span className="hidden sm:inline">REFRESH</span>
        </button>

        <button onClick={handleLogout}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-border hover:border-bear/40 text-muted hover:text-bear text-xs font-mono transition-all">
          <LogOut className="w-3 h-3" />
          <span className="hidden sm:inline">LOGOUT</span>
        </button>
      </div>
    </header>
  );
}
