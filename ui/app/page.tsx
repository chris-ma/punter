import { api, type Race } from "@/lib/api";
import { RaceList } from "@/components/RaceList";

export const dynamic = "force-dynamic";
export const revalidate = 0;

function todayAEST(): string {
  return new Date()
    .toLocaleDateString("en-AU", { timeZone: "Australia/Sydney" })
    .split("/")
    .reverse()
    .join("-");
}

export default async function HomePage() {
  const date = todayAEST();

  let races: Race[] = [];
  try {
    races = await api.getRaces(date);
  } catch {
    // API not yet running — show empty state
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Racing Edge</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Today ·{" "}
          {new Date().toLocaleDateString("en-AU", {
            timeZone: "Australia/Sydney",
            weekday: "long",
            day: "numeric",
            month: "long",
          })}
        </p>
      </div>
      <RaceList races={races} />
    </main>
  );
}
