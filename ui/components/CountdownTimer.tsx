"use client";

import { useEffect, useState } from "react";
import { jumpCountdown } from "@/lib/timezone";

interface Props {
  jumpAt: string; // ISO UTC
}

export function CountdownTimer({ jumpAt }: Props) {
  const [state, setState] = useState(() => jumpCountdown(jumpAt));

  useEffect(() => {
    const id = setInterval(() => setState(jumpCountdown(jumpAt)), 1000);
    return () => clearInterval(id);
  }, [jumpAt]);

  if (state.isPast) {
    return <span className="text-muted-foreground text-sm">Jumped</span>;
  }

  return (
    <span
      className={
        state.isNear
          ? "font-mono font-semibold text-orange-500"
          : "font-mono text-sm text-muted-foreground"
      }
    >
      {state.display}
    </span>
  );
}
