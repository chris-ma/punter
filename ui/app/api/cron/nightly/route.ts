import { NextRequest, NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

/**
 * Nightly batch — seeds tomorrow's races from the configured data source.
 * Called by Vercel Cron at 08:00 UTC (= 18:00 AEST / 19:00 AEDT).
 *
 * Protected by CRON_SECRET so only Vercel's scheduler can trigger it.
 * To test manually: curl -H "Authorization: Bearer $CRON_SECRET" /api/cron/nightly
 */
export async function GET(req: NextRequest) {
  const auth = req.headers.get("authorization");
  const secret = process.env.CRON_SECRET;

  if (secret && auth !== `Bearer ${secret}`) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const puntingFormKey = process.env.PUNTING_FORM_API_KEY;

  if (!puntingFormKey) {
    return NextResponse.json({
      ok: true,
      message: "No data source configured (PUNTING_FORM_API_KEY not set). Skipping race seeding.",
      seeded: 0,
    });
  }

  // Phase 2: seed from Punting Form API
  try {
    const count = await seedFromPuntingForm(puntingFormKey);
    return NextResponse.json({ ok: true, seeded: count });
  } catch (err) {
    console.error("Nightly batch failed:", err);
    return NextResponse.json({ ok: false, error: String(err) }, { status: 500 });
  }
}

async function seedFromPuntingForm(apiKey: string): Promise<number> {
  // TODO: implement Punting Form API seeding
  // Docs: https://www.puntingform.com.au/api/
  // 1. GET /form/fields?date=tomorrow
  // 2. Upsert each race + runner into Supabase
  throw new Error("Punting Form seeding not yet implemented");
}
