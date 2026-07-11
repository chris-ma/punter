"use client";

import { useEffect, useState } from "react";

interface Props {
  dataAgeSeconds: number | null; // null = no live data yet
  lastFetchedAt: Date | null;    // when we last polled the API
}

export function FreshnessBar({ dataAgeSeconds, lastFetchedAt }: Props) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (dataAgeSeconds === null) {
    return (
      <div className="flex items-center gap-2 rounded-md bg-muted px-3 py-1.5 text-xs text-muted-foreground">
        <span className="h-2 w-2 rounded-full bg-muted-foreground/40" />
        No live odds yet
      </div>
    );
  }

  // How stale are the odds themselves (not just our API poll)
  const apiAge = lastFetchedAt
    ? Math.floor((now - lastFetchedAt.getTime()) / 1000)
    : 0;
  const totalAge = dataAgeSeconds + apiAge;

  const isAmber = totalAge >= 90;
  const isRed   = totalAge >= 180;

  const display =
    totalAge < 10  ? "just now"
    : totalAge < 60 ? `${totalAge}s ago`
    : `${Math.floor(totalAge / 60)}m ${totalAge % 60}s ago`;

  return (
    <div
      className={[
        "flex items-center gap-2 rounded-md px-3 py-1.5 text-xs font-medium",
        isRed   ? "bg-red-50 text-red-700"
        : isAmber ? "bg-amber-50 text-amber-700"
        : "bg-green-50 text-green-700",
      ].join(" ")}
    >
      <span
        className={[
          "h-2 w-2 rounded-full",
          isRed   ? "bg-red-500"
          : isAmber ? "bg-amber-400"
          : "bg-green-500 animate-pulse",
        ].join(" ")}
      />
      {isRed
        ? `⚠ Odds stale · last update ${display}`
        : `Live · last update ${display}`}
    </div>
  );
}
