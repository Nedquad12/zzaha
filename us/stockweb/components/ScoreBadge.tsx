"use client";

interface ScoreBarProps {
  value: number;
  max: number;
  label: string;
  compact?: boolean;
}

const INDICATOR_RANGES: Record<string, { min: number; max: number }> = {
  vsa:      { min: -2, max: 2 },
  fsa:      { min: -1, max: 2 },
  vfa:      { min: -3, max: 3 },
  wcc:      { min: -3, max: 3 },
  srst:     { min: -4, max: 3 },
  rsi:      { min: -1, max: 2 },
  macd:     { min: -2, max: 2 },
  ma:       { min: -2, max: 2 },
  ip_score: { min: -4, max: 4 },
  tight:    { min: 0,  max: 2 },
};

export function ScoreCell({ value }: { value: number }) {
  const cls = value > 0 ? "pos" : value < 0 ? "neg" : "neu";
  return (
    <span className={`${cls} font-mono text-xs tabular-nums`}>
      {value > 0 ? `+${value}` : value}
    </span>
  );
}

export function MiniScoreBar({ field, value }: { field: string; value: number }) {
  const range = INDICATOR_RANGES[field] ?? { min: -5, max: 5 };
  const span  = range.max - range.min;
  const zero  = ((0 - range.min) / span) * 100;
  const pos   = ((value - range.min) / span) * 100;
  const left  = Math.min(zero, pos);
  const width = Math.abs(pos - zero);
  const color = value > 0 ? "#3fb950" : value < 0 ? "#f85149" : "#3a4a5c";

  return (
    <div className="relative h-1.5 bg-surface rounded-full w-16 overflow-hidden">
      {/* zero line */}
      <div className="absolute top-0 bottom-0 w-px bg-muted/50" style={{ left: `${zero}%` }} />
      {/* bar */}
      <div
        className="absolute top-0 bottom-0 rounded-full bar-grow"
        style={{ left: `${left}%`, width: `${width}%`, backgroundColor: color }}
      />
    </div>
  );
}

export function TotalBadge({ value }: { value: number }) {
  const abs = Math.abs(value);
  let bg = "bg-muted/20 border-muted/30 text-dim";
  if (value >= 8)       bg = "bg-bull/15 border-bull/40 text-bull shadow-glow-bull";
  else if (value >= 4)  bg = "bg-bull/10 border-bull/20 text-bull/80";
  else if (value <= -8) bg = "bg-bear/15 border-bear/40 text-bear shadow-glow-bear";
  else if (value <= -4) bg = "bg-bear/10 border-bear/20 text-bear/80";

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-mono font-bold tabular-nums ${bg}`}>
      {value > 0 ? `+${value.toFixed(1)}` : value.toFixed(1)}
    </span>
  );
}

export function ChangeBadge({ value }: { value: number }) {
  const pos = value >= 0;
  return (
    <span className={`text-xs font-mono tabular-nums ${pos ? "text-bull" : "text-bear"}`}>
      {pos ? "▲" : "▼"} {Math.abs(value).toFixed(2)}%
    </span>
  );
}
