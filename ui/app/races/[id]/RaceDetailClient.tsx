"use client";

import useSWR from "swr";
import { useEffect, useRef, useState } from "react";
import { api, type Race, type Runner } from "@/lib/api";
import { RunnerTable } from "@/components/RunnerTable";
import { FreshnessBar } from "@/components/FreshnessBar";
import { CountdownTimer } from "@/components/CountdownTimer";
import { formatJumpTime } from "@/lib/timezone";

interface Props {
  race: Race;
}

function useAdaptiveInterval(jumpAt: string) {
  const minsToJump = (new Date(jumpAt).getTime() - Date.now()) / 60000;
  return minsToJump <= 10 ? 10_000 : 30_000;
}

export function RaceDetailClient({ race }: Props) {
  const interval = useAdaptiveInterval(race.scheduled_jump_at);
  const [lastFetchedAt, setLastFetchedAt] = useState<Date | null>(null);

  const { data: runners } = useSWR<Runner[]>(
    `/races/${race.id}/runners`,
    () => api.getRaceRunners(race.id),
    {
      refreshInterval: interval,
      onSuccess: () => setLastFetchedAt(new Date()),
    }
  );

  const isPhase1 = !runners || runners.every((r) => r.confidence_score === null);

  // The most recently seen data_age_seconds across all runners
  const maxAge = runners
    ? Math.max(...runners.map((r) => r.data_age_seconds ?? 0))
    : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">
            {race.track}
            {race.race_number ? ` · R${race.race_number}` : ""}
          </h2>
          <p className="text-sm text-muted-foreground">
            {formatJumpTime(race.scheduled_jump_at, race.state)}
            {race.distance_m ? ` · ${race.distance_m}m` : ""}
            {race.going ? ` · ${race.going}` : ""}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <CountdownTimer jumpAt={race.scheduled_jump_at} />
          <FreshnessBar
            dataAgeSeconds={maxAge}
            lastFetchedAt={lastFetchedAt}
          />
        </div>
      </div>

      {runners ? (
        <RunnerTable runners={runners} isPhase1={isPhase1} />
      ) : (
        <div className="py-12 text-center text-muted-foreground">Loading runners…</div>
      )}
    </div>
  );
}
