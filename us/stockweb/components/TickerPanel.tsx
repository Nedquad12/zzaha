"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/auth";
import { TotalBadge, ChangeBadge, ScoreCell } from "./ScoreBadge";
import { X, TrendingUp, TrendingDown } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine,
  ResponsiveContainer, CartesianGrid
} from "recharts";

const INDICATORS = [
  { key: "vsa",      label: "VSA",  min: -2, max: 2  },
  { key: "fsa",      label: "FSA",  min: -1, max: 2  },
  { key: "vfa",      label: "VFA",  min: -3, max: 3  },
  { key: "wcc",      label: "WCC",  min: -3, max: 3  },
  { key: "srst",     label: "SRST", min: -4, max: 3  },
  { key: "rsi",      label: "RSI",  min: -1, max: 2  },
  { key: "macd",     label: "MACD", min: -2, max: 2  },
  { key: "ma",       label: "MA",   min: -2, max: 2  },
  { key: "ip_score", label: "IP",   min: -4, max: 4  },
  { key: "tight",    label: "T",    min: 0,  max: 2  },
];

function IndicatorRow({ label, value, min, max }: { label: string; value: number; min: number; max: number }) {
  const span   = max - min;
  const zero   = ((0 - min) / span) * 100;
  const pos    = ((value - min) / span) * 100;
  const left   = Math.min(zero, pos);
  const width  = Math.abs(pos - zero);
  const color  = value > 0 ? "#3fb950" : value < 0 ? "#f85149" : "#3a4a5c";

  return (
    <div className="flex items-center gap-3 py-1.5 border-b border-border/30">
      <span className="text-dim text-xs w-10 font-mono shrink-0">{label}</span>
      <div className="flex-1 relative h-2 bg-surface rounded-full overflow-hidden">
        <div className="absolute top-0 bottom-0 w-px bg-muted/40" style={{ left: `${zero}%` }} />
        <div className="absolute top-0 bottom-0 rounded-full"
          style={{ left: `${left}%`, width: `${Math.max(width, 2)}%`, backgroundColor: color, transition: "width 0.5s ease" }} />
      </div>
      <ScoreCell value={value} />
    </div>
  );
}

interface Props {
  ticker: string;
  token:  string;
  onClose: () => void;
}

export default function TickerPanel({ ticker, token, onClose }: Props) {
  const [data, setData]     = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    apiFetch(`/api/ticker/${ticker}`, token)
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [ticker, token]);

  const summary = data?.summary;
  const history = data?.history ?? [];

  // Chart data: last 60 bars
  const chartData = history.slice(-60).map((h: any) => ({
    date:  h.date?.slice(5),
    total: h.total,
    price: h.price,
  }));

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    return (
      <div className="bg-card border border-border rounded px-3 py-2 text-xs font-mono shadow-lg">
        <div className="text-dim mb-1">{label}</div>
        <div className={payload[0]?.value >= 0 ? "text-bull" : "text-bear"}>
          Score: {payload[0]?.value?.toFixed(1)}
        </div>
        {payload[1] && <div className="text-text">Price: ${payload[1]?.value?.toFixed(2)}</div>}
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full bg-card border-l border-border">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-3">
          <span className="ticker-tag text-lg text-text">{ticker}</span>
          {summary && <TotalBadge value={summary.total} />}
        </div>
        <button onClick={onClose} className="text-muted hover:text-text transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>

      {loading ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-muted text-xs cursor-blink">LOADING</div>
        </div>
      ) : !data ? (
        <div className="flex-1 flex items-center justify-center text-muted text-xs">No data</div>
      ) : (
        <div className="flex-1 overflow-y-auto">

          {/* Price summary */}
          {summary && (
            <div className="px-4 py-3 border-b border-border">
              <div className="flex items-end gap-3">
                <span className="text-2xl font-mono font-bold text-text">
                  ${summary.price?.toFixed(2)}
                </span>
                <ChangeBadge value={summary.change ?? 0} />
              </div>
              <div className="text-dim text-xs mt-1">{summary.date}</div>
            </div>
          )}

          {/* Score history chart */}
          {chartData.length > 0 && (
            <div className="px-4 py-3 border-b border-border">
              <div className="text-dim text-xs mb-2 tracking-wider uppercase">Score History (60 bars)</div>
              <ResponsiveContainer width="100%" height={120}>
                <LineChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                  <CartesianGrid strokeDasharray="2 4" stroke="#1e2a38" />
                  <XAxis dataKey="date" tick={{ fill: "#3a4a5c", fontSize: 9 }} tickLine={false} interval="preserveStartEnd" />
                  <YAxis tick={{ fill: "#3a4a5c", fontSize: 9 }} tickLine={false} axisLine={false} />
                  <ReferenceLine y={0} stroke="#3a4a5c" strokeDasharray="3 3" />
                  <Tooltip content={<CustomTooltip />} />
                  <Line dataKey="total" stroke="#388bfd" dot={false} strokeWidth={1.5} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Indicator breakdown */}
          {summary && (
            <div className="px-4 py-3">
              <div className="text-dim text-xs mb-3 tracking-wider uppercase">Indicator Breakdown</div>
              {INDICATORS.map(ind => (
                <IndicatorRow
                  key={ind.key}
                  label={ind.label}
                  value={(summary as any)[ind.key] ?? 0}
                  min={ind.min}
                  max={ind.max}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
