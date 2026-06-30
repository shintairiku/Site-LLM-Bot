import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { fetchAnalyticsData, type Period } from "@/lib/analytics";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const period = (searchParams.get("period") ?? "week") as Period;

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  try {
    const data = await fetchAnalyticsData(supabase, period);
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : "取得エラー";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
