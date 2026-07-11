import type { OddsTick } from "@/lib/api";

interface Props {
  currentPrice: number | null;
  ticks?: OddsTick[]; // most recent first from API, reversed to chronological
}

function trendArrow(ticks: OddsTick[] | undefined): "up" | "down" | null {
  if (!ticks || ticks.length < 2) return null;
  const sorted = [...ticks].sort(
    (a, b) => new Date(a.ticked_at).getTime() - new Date(b.ticked_at).getTime()
  );
  const prev = sorted[sorted.length - 2]?.win_back;
  const curr = sorted[sorted.length - 1]?.win_back;
  if (!prev || !curr) return null;
  if (curr < prev) return "down"; // price shortened = firmed
  if (curr > prev) return "up";   // price drifted
  return null;
}

export function OddsCell({ currentPrice, ticks }: Props) {
  const trend = trendArrow(ticks);

  if (!currentPrice) {
    return <span className="text-muted-foreground">—</span>;
  }

  return (
    <span className="flex items-center gap-1 font-mono tabular-nums">
      {currentPrice.toFixed(2)}
      {trend === "down" && (
        <span className="text-xs text-green-600 font-bold" title="Firmed">▼</span>
      )}
      {trend === "up" && (
        <span className="text-xs text-red-500 font-bold" title="Drifted">▲</span>
      )}
    </span>
  );
}
