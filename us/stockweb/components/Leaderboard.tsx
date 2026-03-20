"use client";
import { useState, useMemo } from "react";
import { ScoreCell, TotalBadge, ChangeBadge, MiniScoreBar } from "./ScoreBadge";
import { ChevronUp, ChevronDown, Search, SlidersHorizontal } from "lucide-react";

export interface TickerRow {
  ticker:   string;
  date:     string;
  price:    number;
  change:   number;
  vsa:      number;
  fsa:      number;
  vfa:      number;
  wcc:      number;
  srst:     number;
  rsi:      number;
  macd:     number;
  ma:       number;
  ip_score: number;
  tight:    number;
  total:    number;
}

const COLS = [
  { key: "ticker",   label: "TICKER",   sortable: false, w: "w-20" },
  { key: "price",    label: "PRICE",    sortable: true,  w: "w-20" },
  { key: "change",   label: "CHG%",     sortable: true,  w: "w-20" },
  { key: "total",    label: "TOTAL",    sortable: true,  w: "w-24" },
  { key: "vsa",      label: "VSA",      sortable: true,  w: "w-14" },
  { key: "fsa",      label: "FSA",      sortable: true,  w: "w-14" },
  { key: "vfa",      label: "VFA",      sortable: true,  w: "w-14" },
  { key: "wcc",      label: "WCC",      sortable: true,  w: "w-14" },
  { key: "srst",     label: "SRST",     sortable: true,  w: "w-14" },
  { key: "rsi",      label: "RSI",      sortable: true,  w: "w-14" },
  { key: "macd",     label: "MACD",     sortable: true,  w: "w-14" },
  { key: "ma",       label: "MA",       sortable: true,  w: "w-14" },
  { key: "ip_score", label: "IP",       sortable: true,  w: "w-14" },
  { key: "tight",    label: "T",        sortable: true,  w: "w-10" },
];

interface Props {
  data: TickerRow[];
  onSelect: (ticker: string) => void;
  selected: string | null;
}

export default function Leaderboard({ data, onSelect, selected }: Props) {
  const [sortKey, setSortKey]   = useState<string>("total");
  const [sortDir, setSortDir]   = useState<"asc" | "desc">("desc");
  const [search, setSearch]     = useState("");
  const [filter, setFilter]     = useState<"all" | "bull" | "bear">("all");
  const [showBars, setShowBars] = useState(true);

  const sorted = useMemo(() => {
    let rows = [...data];

    if (search) {
      const q = search.toUpperCase();
      rows = rows.filter(r => r.ticker.includes(q));
    }
    if (filter === "bull") rows = rows.filter(r => r.total > 0);
    if (filter === "bear") rows = rows.filter(r => r.total < 0);

    rows.sort((a, b) => {
      const av = (a as any)[sortKey] ?? 0;
      const bv = (b as any)[sortKey] ?? 0;
      return sortDir === "desc" ? bv - av : av - bv;
    });
    return rows;
  }, [data, sortKey, sortDir, search, filter]);

  const handleSort = (key: string) => {
    if (sortKey === key) setSortDir(d => d === "desc" ? "asc" : "desc");
    else { setSortKey(key); setSortDir("desc"); }
  };

  const SortIcon = ({ col }: { col: string }) => {
    if (sortKey !== col) return <span className="text-muted/40 text-xs">⇅</span>;
    return sortDir === "desc"
      ? <ChevronDown className="w-3 h-3 text-accent" />
      : <ChevronUp   className="w-3 h-3 text-accent" />;
  };

  const bullCount = data.filter(r => r.total > 0).length;
  const bearCount = data.filter(r => r.total < 0).length;

  return (
    <div className="flex flex-col h-full">

      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border flex-shrink-0">
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search ticker..."
            className="bg-surface border border-border rounded pl-8 pr-3 py-1.5 text-xs text-text placeholder:text-muted focus:outline-none focus:border-accent/40 w-40 font-mono"
          />
        </div>

        {/* Filter pills */}
        <div className="flex gap-1">
          {(["all","bull","bear"] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-2.5 py-1 rounded text-xs font-mono uppercase tracking-wider transition-all ${
                filter === f
                  ? f === "bull" ? "bg-bull/20 border border-bull/40 text-bull"
                  : f === "bear" ? "bg-bear/20 border border-bear/40 text-bear"
                  : "bg-accent/20 border border-accent/40 text-accent"
                  : "bg-surface border border-border text-muted hover:border-border/80"
              }`}>
              {f === "all" ? `ALL ${data.length}` : f === "bull" ? `▲ ${bullCount}` : `▼ ${bearCount}`}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <button onClick={() => setShowBars(v => !v)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded border text-xs font-mono transition-all ${
              showBars ? "bg-accent/10 border-accent/30 text-accent" : "bg-surface border-border text-muted"
            }`}>
            <SlidersHorizontal className="w-3 h-3" /> BARS
          </button>
          <span className="text-muted text-xs">{sorted.length} results</span>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-auto flex-1">
        <table className="w-full text-xs border-collapse min-w-max">
          <thead className="sticky top-0 z-10">
            <tr className="bg-surface border-b border-border">
              <th className="px-3 py-2.5 text-left text-dim font-mono font-medium tracking-wider w-8 text-center">#</th>
              {COLS.map(col => (
                <th key={col.key}
                  onClick={() => col.sortable && handleSort(col.key)}
                  className={`px-3 py-2.5 text-left text-dim font-mono font-medium tracking-wider ${col.w} ${
                    col.sortable ? "cursor-pointer hover:text-text select-none" : ""
                  } ${sortKey === col.key ? "text-accent" : ""}`}>
                  <span className="flex items-center gap-1">
                    {col.label}
                    {col.sortable && <SortIcon col={col.key} />}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => {
              const isSelected = selected === row.ticker;
              const rowBg = isSelected
                ? "bg-accent/10 border-l-2 border-l-accent"
                : i % 2 === 0 ? "bg-bg" : "bg-card";

              return (
                <tr key={row.ticker}
                  onClick={() => onSelect(row.ticker)}
                  className={`tr-hover border-b border-border/40 ${rowBg}`}>

                  {/* Rank */}
                  <td className="px-3 py-2 text-center text-muted tabular-nums">{i + 1}</td>

                  {/* Ticker */}
                  <td className="px-3 py-2">
                    <span className={`ticker-tag text-xs ${isSelected ? "text-accent" : "text-text"}`}>
                      {row.ticker}
                    </span>
                  </td>

                  {/* Price */}
                  <td className="px-3 py-2 text-text tabular-nums font-mono">
                    ${row.price?.toFixed(2) ?? "—"}
                  </td>

                  {/* Change */}
                  <td className="px-3 py-2">
                    <ChangeBadge value={row.change ?? 0} />
                  </td>

                  {/* Total */}
                  <td className="px-3 py-2">
                    <TotalBadge value={row.total ?? 0} />
                  </td>

                  {/* Indicator scores */}
                  {(["vsa","fsa","vfa","wcc","srst","rsi","macd","ma","ip_score","tight"] as const).map(f => (
                    <td key={f} className="px-3 py-2">
                      <div className="flex flex-col items-center gap-1">
                        <ScoreCell value={(row as any)[f] ?? 0} />
                        {showBars && <MiniScoreBar field={f} value={(row as any)[f] ?? 0} />}
                      </div>
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>

        {sorted.length === 0 && (
          <div className="text-center py-16 text-muted text-sm">
            No results for &quot;{search}&quot;
          </div>
        )}
      </div>
    </div>
  );
}
