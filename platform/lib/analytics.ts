import type { SupabaseClient } from "@supabase/supabase-js";

export type Period = "day" | "week" | "month";

export interface AnalyticsData {
  kpis: {
    chatCount: number;
    userCount: number;
    linkClickCount: number;
    resolvedRate: number | null;
  };
  trend: Array<{ label: string; chatCount: number; userCount: number }>;
  linkClicks: Array<{ link_url: string; page_title: string; click_count: number }>;
}

export async function fetchAnalyticsData(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  supabase: SupabaseClient<any, any, any>,
  period: Period
): Promise<AnalyticsData> {
  const rangeStart = getRangeStart(period).toISOString();

  const [messagesRes, linkClicksRes, feedbackRes] = await Promise.all([
    supabase
      .from("analytics_chat_messages")
      .select("sent_at, visitor_id")
      .gte("sent_at", rangeStart),
    supabase
      .from("analytics_related_link_clicks")
      .select("link_url, clicked_at")
      .gte("clicked_at", rangeStart),
    supabase
      .from("analytics_session_feedback")
      .select("resolved")
      .gte("occurred_at", rangeStart),
  ]);

  if (messagesRes.error) throw new Error(messagesRes.error.message);
  if (linkClicksRes.error) throw new Error(linkClicksRes.error.message);
  if (feedbackRes.error) throw new Error(feedbackRes.error.message);

  const messages = messagesRes.data ?? [];
  const linkClicks = linkClicksRes.data ?? [];
  const feedback = feedbackRes.data ?? [];

  const chatCount = messages.length;
  const userCount = new Set(messages.map((m) => m.visitor_id).filter(Boolean)).size;
  const linkClickCount = linkClicks.length;

  const resolvedCount = feedback.filter((f) => f.resolved === true).length;
  const unresolvedCount = feedback.filter((f) => f.resolved === false).length;
  const feedbackTotal = resolvedCount + unresolvedCount;
  const resolvedRate =
    feedbackTotal > 0 ? Math.round((resolvedCount / feedbackTotal) * 100) : null;

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

  return {
    kpis: { chatCount, userCount, linkClickCount, resolvedRate },
    trend,
    linkClicks: linkClickTable,
  };
}

function getRangeStart(period: Period): Date {
  const now = new Date();
  if (period === "day") {
    const d = new Date(now);
    d.setUTCDate(d.getUTCDate() - 6);
    d.setUTCHours(0, 0, 0, 0);
    return d;
  }
  if (period === "week") {
    const d = new Date(now);
    d.setUTCDate(d.getUTCDate() - 7 * 7);
    d.setUTCHours(0, 0, 0, 0);
    return d;
  }
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 5, 1));
}

function toBucket(iso: string, period: Period): string {
  if (period === "day") return iso.slice(0, 10);
  if (period === "week") {
    const d = new Date(iso);
    const day = d.getUTCDay();
    const diff = day === 0 ? -6 : 1 - day;
    const mon = new Date(d);
    mon.setUTCDate(d.getUTCDate() + diff);
    return mon.toISOString().slice(0, 10);
  }
  return iso.slice(0, 7);
}

function buildBuckets(period: Period): string[] {
  const buckets: string[] = [];
  const now = new Date();

  if (period === "day") {
    for (let i = 6; i >= 0; i--) {
      const d = new Date(now);
      d.setUTCDate(d.getUTCDate() - i);
      buckets.push(d.toISOString().slice(0, 10));
    }
  } else if (period === "week") {
    const day = now.getUTCDay();
    const diff = day === 0 ? -6 : 1 - day;
    const thisMonday = new Date(now);
    thisMonday.setUTCDate(now.getUTCDate() + diff);
    thisMonday.setUTCHours(0, 0, 0, 0);
    for (let i = 7; i >= 0; i--) {
      const d = new Date(thisMonday);
      d.setUTCDate(thisMonday.getUTCDate() - i * 7);
      buckets.push(d.toISOString().slice(0, 10));
    }
  } else {
    for (let i = 5; i >= 0; i--) {
      const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - i, 1));
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
      blog: "ブログ",
      case: "施工事例",
      company: "会社情報",
      contact: "お問い合わせ",
      event: "イベント",
      faq: "よくある質問",
      news: "お知らせ",
      reform: "リフォーム",
      service: "サービス",
      works: "施工事例",
      price: "料金ページ",
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
