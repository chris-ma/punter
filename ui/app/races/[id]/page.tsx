import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { RaceDetailClient } from "./RaceDetailClient";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function RacePage({ params }: Props) {
  const { id } = await params;

  let race;
  try {
    race = await api.getRace(id);
  } catch {
    notFound();
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <Link
        href="/"
        className="mb-6 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        ← Today&apos;s races
      </Link>
      <RaceDetailClient race={race} />
    </main>
  );
}
