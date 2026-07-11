/**
 * Data access layer — reads directly from Supabase.
 * Replaces the FastAPI HTTP calls for the Vercel deployment.
 * Import `supabase` (anon, browser-safe) for client components.
 * Import `supabaseAdmin()` (service role) in server components / API routes.
 */

import { getSupabase } from "@/lib/supabase";

export interface Race {
  id: string;
  betfair_market_id: string;
  track: string;
  state: string;
  race_name: string | null;
  race_number: number | null;
  scheduled_jump_at: string;
  distance_m: number | null;
  going: string | null;
  field_size: number | null;
  status: string;
  form_fetched_at: string | null;
}

export interface Runner {
  id: string;
  horse_name: string;
  barrier: number | null;
  jockey: string | null;
  trainer: string | null;
  weight_kg: number | null;
  scratched: boolean;
  // joined from predictions
  win_prob: number | null;
  market_implied_prob: number | null;
  edge: number | null;
  confidence_score: number | null;
  // joined from latest odds tick
  win_back: number | null;
  data_age_seconds: number | null;
}

export interface OddsTick {
  ticked_at: string;
  win_back: number | null;
  win_lay: number | null;
  win_traded_vol: number | null;
}

export async function getRaces(date: string, state?: string): Promise<Race[]> {
  const sb = getSupabase();
  let q = sb
    .from("races")
    .select("*")
    .eq("race_date", date)
    .order("scheduled_jump_at");

  if (state) q = q.eq("state", state);

  const { data, error } = await q;
  if (error) throw error;
  return (data ?? []) as Race[];
}

export async function getRace(id: string): Promise<Race | null> {
  const { data, error } = await getSupabase()
    .from("races")
    .select("*")
    .eq("id", id)
    .maybeSingle();
  if (error) throw error;
  return data as Race | null;
}

export async function getRaceRunners(raceId: string): Promise<Runner[]> {
  const now = new Date();

  // 1. Runners
  const { data: runners, error: rErr } = await getSupabase()
    .from("runners")
    .select("*")
    .eq("race_id", raceId);
  if (rErr) throw rErr;
  if (!runners?.length) return [];

  const ids = runners.map((r) => r.id as string);

  // 2. Latest prediction per runner (bulk)
  const { data: preds } = await getSupabase()
    .from("predictions")
    .select("runner_id, win_prob, market_implied_prob, edge, confidence_score, predicted_at")
    .in("runner_id", ids)
    .order("predicted_at", { ascending: false });

  type PredRow = { runner_id: string; win_prob: number | null; market_implied_prob: number | null; edge: number | null; confidence_score: number | null; predicted_at: string };
  type TickRow = { runner_id: string; win_back: number | null; ticked_at: string };

  const latestPred: Record<string, PredRow> = {};
  for (const p of (preds ?? []) as PredRow[]) {
    if (!latestPred[p.runner_id]) latestPred[p.runner_id] = p;
  }

  // 3. Latest tick per runner (bulk)
  const { data: ticks } = await getSupabase()
    .from("odds_ticks")
    .select("runner_id, win_back, ticked_at")
    .in("runner_id", ids)
    .order("ticked_at", { ascending: false });

  const latestTick: Record<string, TickRow> = {};
  for (const t of (ticks ?? []) as TickRow[]) {
    if (!latestTick[t.runner_id]) latestTick[t.runner_id] = t;
  }

  const result: Runner[] = runners.map((r) => {
    const pred = latestPred[r.id];
    const tick = latestTick[r.id];
    const dataAge = tick
      ? (now.getTime() - new Date(tick.ticked_at).getTime()) / 1000
      : null;

    return {
      id: r.id,
      horse_name: r.horse_name,
      barrier: r.barrier ?? null,
      jockey: r.jockey ?? null,
      trainer: r.trainer ?? null,
      weight_kg: r.weight_kg ?? null,
      scratched: r.scratched,
      win_prob: pred?.win_prob ?? null,
      market_implied_prob: pred?.market_implied_prob ?? null,
      edge: pred?.edge ?? null,
      confidence_score: pred?.confidence_score ?? null,
      win_back: tick?.win_back ?? null,
      data_age_seconds: dataAge,
    };
  });

  return result.sort((a, b) => {
    if (a.win_prob === null && b.win_prob === null) return 0;
    if (a.win_prob === null) return 1;
    if (b.win_prob === null) return -1;
    return b.win_prob - a.win_prob;
  });
}

export async function getRunnerTicks(
  runnerId: string,
  limit = 30
): Promise<OddsTick[]> {
  const { data, error } = await getSupabase()
    .from("odds_ticks")
    .select("ticked_at, win_back, win_lay, win_traded_vol")
    .eq("runner_id", runnerId)
    .order("ticked_at", { ascending: false })
    .limit(limit);
  if (error) throw error;
  return ((data ?? []) as OddsTick[]).reverse();
}
