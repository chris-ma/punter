"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";
import type { Runner } from "@/lib/api";
import { OddsCell } from "@/components/OddsCell";

interface Props {
  runners: Runner[];
  isPhase1: boolean; // true when all confidence_scores are null
}

function pct(v: number | null): string {
  if (v === null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function edgeClass(edge: number | null, isPhase1: boolean): string {
  if (isPhase1 || edge === null) return "text-muted-foreground";
  if (edge > 0.05) return "text-green-700 font-semibold";
  if (edge < -0.05) return "text-red-600";
  return "text-foreground";
}

function edgeDisplay(edge: number | null, isPhase1: boolean): string {
  if (isPhase1 || edge === null) return "—";
  const sign = edge > 0 ? "+" : "";
  return `${sign}${(edge * 100).toFixed(1)}%`;
}

export function RunnerTable({ runners, isPhase1 }: Props) {
  return (
    <div className="space-y-3">
      {isPhase1 && (
        <div className="flex items-center gap-2 rounded-md border border-dashed border-muted-foreground/40 bg-muted/30 px-4 py-2 text-sm text-muted-foreground">
          <span>🔒</span>
          <span>
            <strong>Phase 1 · Market rank only.</strong> Independent model not yet active.
            Edge and confidence will appear once form data is connected.
          </span>
        </div>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-8">#</TableHead>
            <TableHead>Runner</TableHead>
            <TableHead className="text-center">Barrier</TableHead>
            <TableHead className="text-right">
              {isPhase1 ? (
                <Tooltip>
                  <TooltipTrigger>
                    <span className="cursor-help text-muted-foreground">Edge 🔒</span>
                  </TooltipTrigger>
                  <TooltipContent>
                    Independent model not yet active. Showing market-implied ranking only.
                  </TooltipContent>
                </Tooltip>
              ) : (
                "Edge"
              )}
            </TableHead>
            <TableHead className="text-right">Model %</TableHead>
            <TableHead className="text-right">Market %</TableHead>
            <TableHead className="text-right">Price</TableHead>
            <TableHead className="text-center">Confidence</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runners.map((runner, i) => (
            <TableRow
              key={runner.id}
              className={runner.scratched ? "opacity-40 line-through" : undefined}
            >
              <TableCell className="text-muted-foreground">{i + 1}</TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <span className="font-medium">{runner.horse_name}</span>
                  {runner.scratched && (
                    <Badge variant="outline" className="text-xs">SCR</Badge>
                  )}
                  {runner.jockey && (
                    <span className="text-xs text-muted-foreground">{runner.jockey}</span>
                  )}
                </div>
              </TableCell>
              <TableCell className="text-center font-mono">
                {runner.barrier ?? "—"}
              </TableCell>
              <TableCell
                className={[
                  "text-right font-mono tabular-nums",
                  edgeClass(runner.edge, isPhase1),
                ].join(" ")}
              >
                {edgeDisplay(runner.edge, isPhase1)}
              </TableCell>
              <TableCell className="text-right font-mono tabular-nums text-muted-foreground">
                {pct(runner.win_prob)}
              </TableCell>
              <TableCell className="text-right font-mono tabular-nums text-muted-foreground">
                {pct(runner.market_implied_prob)}
              </TableCell>
              <TableCell className="text-right">
                <OddsCell currentPrice={runner.win_back} />
              </TableCell>
              <TableCell className="text-center">
                {runner.confidence_score !== null ? (
                  <div
                    className="mx-auto h-2 w-16 overflow-hidden rounded-full bg-muted"
                    title={`Confidence: ${(runner.confidence_score * 100).toFixed(0)}%`}
                  >
                    <div
                      className="h-full rounded-full bg-blue-500"
                      style={{ width: `${(runner.confidence_score * 100).toFixed(0)}%` }}
                    />
                  </div>
                ) : (
                  <span className="text-muted-foreground/40">—</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
