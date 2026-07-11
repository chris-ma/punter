const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Race {
  id: string;
  betfair_market_id: string;
  track: string;
  state: string;
  race_name: string | null;
  race_number: number | null;
  scheduled_jump_at: string; // ISO UTC
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
  win_prob: number | null;
  market_implied_prob: number | null;
  edge: number | null;
  confidence_score: number | null;
  win_back: number | null;
  data_age_seconds: number | null;
}

export interface OddsTick {
  ticked_at: string;
  win_back: number | null;
  win_lay: number | null;
  win_traded_vol: number | null;
}

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  getRaces: (date: string, state?: string) => {
    const params = new URLSearchParams({ race_date: date });
    if (state) params.set("state", state);
    return apiFetch<Race[]>(`/races/?${params}`);
  },
  getRace: (id: string) => apiFetch<Race>(`/races/${id}`),
  getRaceRunners: (id: string) => apiFetch<Runner[]>(`/races/${id}/runners`),
  getRunnerTicks: (id: string, limit = 30) =>
    apiFetch<OddsTick[]>(`/runners/${id}/ticks?limit=${limit}`),
};
