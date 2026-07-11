import Link from "next/link";
import { notFound } from "next/navigation";
import { getRace } from "@/lib/db";
import { RaceDetailClient } from "./RaceDetailClient";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function RacePage({ params }: Props) {
  const { id } = await params;

  const race = await getRace(id).catch(() => null);
  if (!race) notFound();

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
