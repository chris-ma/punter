import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import type { Race } from "@/lib/api";
import { formatJumpTime } from "@/lib/timezone";
import { CountdownTimer } from "@/components/CountdownTimer";

interface Props {
  race: Race;
}

const STATUS_BADGE: Record<string, string> = {
  upcoming: "bg-blue-100 text-blue-800",
  open:     "bg-green-100 text-green-800",
  closed:   "bg-orange-100 text-orange-800",
  settled:  "bg-muted text-muted-foreground",
};

export function RaceCard({ race }: Props) {
  const jumpLabel = formatJumpTime(race.scheduled_jump_at, race.state);
  const statusClass = STATUS_BADGE[race.status] ?? STATUS_BADGE.upcoming;

  return (
    <Link
      href={`/races/${race.id}`}
      className="flex items-center justify-between rounded-lg border bg-card px-4 py-3 transition-colors hover:bg-accent"
    >
      <div className="space-y-0.5">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-sm">{race.track}</span>
          {race.race_number && (
            <span className="text-xs text-muted-foreground">R{race.race_number}</span>
          )}
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusClass}`}>
            {race.status}
          </span>
        </div>
        <div className="text-xs text-muted-foreground">
          {race.race_name && <span className="mr-2">{race.race_name}</span>}
          {race.distance_m && <span className="mr-2">{race.distance_m}m</span>}
          {race.going && <span className="mr-2">· {race.going}</span>}
          {race.field_size && <span>{race.field_size} runners</span>}
        </div>
      </div>
      <div className="flex flex-col items-end gap-1 text-right">
        <span className="text-xs text-muted-foreground">{jumpLabel}</span>
        {race.status === "upcoming" || race.status === "open" ? (
          <CountdownTimer jumpAt={race.scheduled_jump_at} />
        ) : null}
      </div>
    </Link>
  );
}
