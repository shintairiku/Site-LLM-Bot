import { createClient } from "@/lib/supabase/server";
import { fetchAnalyticsData } from "@/lib/analytics";
import AnalyticsDashboard from "./AnalyticsDashboard";

export default async function AnalyticsPage() {
  const supabase = await createClient();

  const [day, week, month] = await Promise.all([
    fetchAnalyticsData(supabase, "day"),
    fetchAnalyticsData(supabase, "week"),
    fetchAnalyticsData(supabase, "month"),
  ]);

  return <AnalyticsDashboard day={day} week={week} month={month} />;
}
