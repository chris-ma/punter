import { formatInTimeZone } from "date-fns-tz";

export const STATE_TZ: Record<string, string> = {
  NSW: "Australia/Sydney",
  VIC: "Australia/Melbourne",
  QLD: "Australia/Brisbane",   // no daylight saving
  WA:  "Australia/Perth",
  SA:  "Australia/Adelaide",
  TAS: "Australia/Hobart",
  ACT: "Australia/Sydney",
  NT:  "Australia/Darwin",
  UNK: "Australia/Sydney",
};

export function stateTimezone(state: string): string {
  return STATE_TZ[state.toUpperCase()] ?? "Australia/Sydney";
}

export function formatJumpTime(utcIso: string, state: string): string {
  return formatInTimeZone(new Date(utcIso), stateTimezone(state), "h:mm a zzz");
}

export function jumpCountdown(utcIso: string): {
  display: string;
  isNear: boolean;  // within 10 min
  isPast: boolean;
} {
  const diff = new Date(utcIso).getTime() - Date.now();
  if (diff <= 0) return { display: "Jumped", isNear: false, isPast: true };

  const totalSeconds = Math.floor(diff / 1000);
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  const isNear = mins < 10;
  const display = mins > 0
    ? `${mins}m ${secs.toString().padStart(2, "0")}s`
    : `${secs}s`;
  return { display, isNear, isPast: false };
}
