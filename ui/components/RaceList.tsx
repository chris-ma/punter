"use client";

import { useState } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import type { Race } from "@/lib/api";
import { RaceCard } from "@/components/RaceCard";

interface Props {
  races: Race[];
}

const AU_STATES = ["All", "VIC", "NSW", "QLD", "WA", "SA", "TAS", "NT"];

export function RaceList({ races }: Props) {
  const [activeState, setActiveState] = useState("All");

  const filtered =
    activeState === "All"
      ? races
      : races.filter((r) => r.state === activeState);

  const grouped = filtered.reduce<Record<string, Race[]>>((acc, race) => {
    const key = race.state || "Other";
    (acc[key] ??= []).push(race);
    return acc;
  }, {});

  if (races.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
        No races found for this date.
      </div>
    );
  }

  return (
    <Tabs value={activeState} onValueChange={setActiveState}>
      <TabsList className="mb-4 flex-wrap h-auto gap-1">
        {AU_STATES.filter(
          (s) => s === "All" || races.some((r) => r.state === s)
        ).map((s) => (
          <TabsTrigger key={s} value={s} className="text-xs">
            {s}
          </TabsTrigger>
        ))}
      </TabsList>

      <TabsContent value={activeState} className="mt-0">
        {activeState === "All" ? (
          Object.entries(grouped).map(([state, stateRaces]) => (
            <div key={state} className="mb-6">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {state}
              </h3>
              <div className="space-y-2">
                {stateRaces.map((race) => (
                  <RaceCard key={race.id} race={race} />
                ))}
              </div>
            </div>
          ))
        ) : (
          <div className="space-y-2">
            {filtered.map((race) => (
              <RaceCard key={race.id} race={race} />
            ))}
          </div>
        )}
      </TabsContent>
    </Tabs>
  );
}
