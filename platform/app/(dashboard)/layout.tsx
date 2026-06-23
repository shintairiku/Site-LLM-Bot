import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { fetchAnalyticsData } from "@/lib/analytics";
import { DashboardProvider, type PromptRecord } from "@/lib/dashboard-context";
import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  const [promptsResult, day, week, month] = await Promise.all([
    supabase
      .from("prompts")
      .select("id, content, note, created_by, created_at")
      .order("created_at", { ascending: false })
      .limit(20),
    fetchAnalyticsData(supabase, "day"),
    fetchAnalyticsData(supabase, "week"),
    fetchAnalyticsData(supabase, "month"),
  ]);

  const initialPrompts: PromptRecord[] = promptsResult.data ?? [];
  const initialAnalytics = { day, week, month };

  return (
    <DashboardProvider initialPrompts={initialPrompts} initialAnalytics={initialAnalytics}>
      <div className="flex h-full overflow-hidden">
        <Sidebar />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Topbar userEmail={user.email ?? null} />
          <main className="flex-1 overflow-auto p-6">{children}</main>
        </div>
      </div>
    </DashboardProvider>
  );
}
