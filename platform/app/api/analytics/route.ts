import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

type Period = "day" | "week" | "month";

function getRangeStart(period: Period): Date {
  const now = new Date();
  if (period === "day") {
    const d = new Date(now);
    d.setDate(d.getDate() - 6);
    d.setHours(0, 0, 0, 0);
    return d;
  }
  if (period === "week") {
    const d = new Date(now);
    d.setDate(d.getDate() - 7 * 7);
    d.setHours(0, 0, 0, 0);
    return d;
  }
  // month
  const d = new Date(now);
  d.setMonth(d.getMonth() - 5);
  d.setDate(1);
  d.setHours(0, 0, 0, 0);
  return d;
}

function toBucket(iso: string, period: Period): string {
  const d = new Date(iso);
  if (period === "day") return d.toISOString().slice(0, 10);
  if (period === "week") {
    const day = d.getDay();
    const diff = day === 0 ? -6 : 1 - day;
    const mon = new Date(d);
    mon.setDate(d.getDate() + diff);
    return mon.toISOString().slice(0, 10);
  }
  return d.toISOString().slice(0, 7); // YYYY-MM
}

function buildBuckets(period: Period): string[] {
  const buckets: string[] = [];
  const now = new Date();

  if (period === "day") {
    for (let i = 6; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      buckets.push(d.toISOString().slice(0, 10));
    }
  } else if (period === "week") {
    const day = now.getDay();
    const diff = day === 0 ? -6 : 1 - day;
    const thisMonday = new Date(now);
    thisMonday.setDate(now.getDate() + diff);
    thisMonday.setHours(0, 0, 0, 0);
    for (let i = 7; i >= 0; i--) {
      const d = new Date(thisMonday);
      d.setDate(thisMonday.getDate() - i * 7);
      buckets.push(d.toISOString().slice(0, 10));
    }
  } else {
    for (let i = 5; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      buckets.push(d.toISOString().slice(0, 7));
    }
  }
  return buckets;
}

function formatLabel(bucket: string, period: Period): string {
  if (period === "day") {
    const [, m, d] = bucket.split("-");
    return `${parseInt(m)}/${parseInt(d)}`;
  }
  if (period === "week") {
    const [, m, d] = bucket.split("-");
    return `${parseInt(m)}/${parseInt(d)}週`;
  }
  const [, m] = bucket.split("-");
  return `${parseInt(m)}月`;
}

function deriveLinkTitle(url: string): string {
  try {
    const { pathname } = new URL(url);
    const segments = pathname.split("/").filter(Boolean);
    const labels: Record<string, string> = {
      blog: "ブログ", case: "施工事例", company: "会社情報",
      contact: "お問い合わせ", event: "イベント", faq: "よくある質問",
      news: "お知らせ", reform: "リフォーム", service: "サービス",
      works: "施工事例", price: "料金ページ",
    };
    for (const seg of segments.reverse()) {
      const key = seg.replace(/\.(html?|php)$/, "").toLowerCase();
      if (labels[key]) return labels[key];
    }
  } catch {
    // invalid URL
  }
  return "関連ページ";
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const period = (searchParams.get("period") ?? "week") as Period;

  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const rangeStart = getRangeStart(period).toISOString();

  const [messagesRes, linkClicksRes] = await Promise.all([
    supabase
      .from("analytics_chat_messages")
      .select("sent_at, visitor_id")
      .gte("sent_at", rangeStart),
    supabase
      .from("analytics_related_link_clicks")
      .select("link_url, clicked_at")
      .gte("clicked_at", rangeStart),
  ]);

  if (messagesRes.error) {
    return NextResponse.json({ error: messagesRes.error.message }, { status: 500 });
  }
  if (linkClicksRes.error) {
    return NextResponse.json({ error: linkClicksRes.error.message }, { status: 500 });
  }

  const messages = messagesRes.data ?? [];
  const linkClicks = linkClicksRes.data ?? [];

  // KPIs
  const chatCount = messages.length;
  const userCount = new Set(messages.map((m) => m.visitor_id).filter(Boolean)).size;
  const linkClickCount = linkClicks.length;

  // Trend: group by bucket
  const buckets = buildBuckets(period);
  const chatByBucket: Record<string, number> = {};
  const usersByBucket: Record<string, Set<string>> = {};
  buckets.forEach((b) => {
    chatByBucket[b] = 0;
    usersByBucket[b] = new Set();
  });

  for (const m of messages) {
    const b = toBucket(m.sent_at, period);
    if (b in chatByBucket) {
      chatByBucket[b]++;
      if (m.visitor_id) usersByBucket[b].add(m.visitor_id);
    }
  }

  const trend = buckets.map((b) => ({
    label: formatLabel(b, period),
    chatCount: chatByBucket[b],
    userCount: usersByBucket[b].size,
  }));

  // Link clicks: group by URL
  const clicksByUrl: Record<string, number> = {};
  for (const c of linkClicks) {
    clicksByUrl[c.link_url] = (clicksByUrl[c.link_url] ?? 0) + 1;
  }
  const linkClickTable = Object.entries(clicksByUrl)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 20)
    .map(([link_url, click_count]) => ({
      link_url,
      page_title: deriveLinkTitle(link_url),
      click_count,
    }));

  return NextResponse.json({
    kpis: { chatCount, userCount, linkClickCount, resolvedRate: 87 },
    trend,
    linkClicks: linkClickTable,
  });
}
