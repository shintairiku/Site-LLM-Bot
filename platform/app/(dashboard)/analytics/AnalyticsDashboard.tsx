"use client";

import { useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import type { AnalyticsData, Period } from "@/lib/analytics";

interface Props {
  day: AnalyticsData;
  week: AnalyticsData;
  month: AnalyticsData;
}

export default function AnalyticsDashboard({ day, week, month }: Props) {
  const [period, setPeriod] = useState<Period>("week");

  const data = period === "day" ? day : period === "week" ? week : month;

  return (
    <div>
      {/* ツールバー */}
      <div className="flex items-start justify-between mb-[18px] flex-wrap gap-3">
        <div>
          <div className="text-[15px] font-bold">チャットボット分析</div>
          <div className="text-[12px]" style={{ color: "var(--gray-500)" }}>
            利用状況とパフォーマンスの推移
          </div>
        </div>
        <div
          className="inline-flex rounded-[9px] p-[3px]"
          style={{ background: "var(--gray-100)" }}
        >
          {(["day", "week", "month"] as Period[]).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className="px-4 py-[7px] rounded-[7px] text-[13px] font-semibold"
              style={{
                background: period === p ? "#fff" : "transparent",
                color: period === p ? "var(--blue-700)" : "var(--gray-500)",
                boxShadow: period === p ? "0 1px 3px rgba(0,0,0,.08)" : "none",
                border: "none",
                cursor: "pointer",
              }}
            >
              {p === "day" ? "日" : p === "week" ? "週" : "月"}
            </button>
          ))}
        </div>
      </div>

      {/* KPIカード */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: "16px",
          marginBottom: "18px",
        }}
      >
        <KpiCard label="チャット送信回数" value={data.kpis.chatCount.toLocaleString()} />
        <KpiCard label="利用ユーザー数" value={data.kpis.userCount.toLocaleString()} />
        <KpiCard label="URL遷移数" value={data.kpis.linkClickCount.toLocaleString()} />
        <KpiCard
          label="解決率"
          value={data.kpis.resolvedRate !== null ? `${data.kpis.resolvedRate}%` : "-"}
        />
      </div>

      {/* トレンドチャート */}
      <div
        className="bg-white rounded-[14px] p-5 mb-[18px]"
        style={{ border: "1px solid var(--gray-200)" }}
      >
        <div className="text-[15px] font-bold mb-4">送信回数・ユーザー数の推移</div>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data.trend} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--gray-200)" />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: "var(--gray-500)" }} />
            <YAxis tick={{ fontSize: 11, fill: "var(--gray-500)" }} allowDecimals={false} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line
              type="monotone"
              dataKey="chatCount"
              name="送信回数"
              stroke="#2563eb"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              legendType="line"
            />
            <Line
              type="monotone"
              dataKey="userCount"
              name="ユーザー数"
              stroke="#3b82f6"
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={false}
              activeDot={{ r: 4 }}
              legendType="line"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* URL遷移テーブル */}
      <div
        className="bg-white rounded-[14px] p-5"
        style={{ border: "1px solid var(--gray-200)" }}
      >
        <div className="text-[15px] font-bold mb-4">関連リンク遷移</div>
        {data.linkClicks.length === 0 ? (
          <p className="text-[13px]" style={{ color: "var(--gray-500)" }}>
            この期間にURL遷移はありません
          </p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr>
                {["URL", "ページタイトル", "表示回数"].map((h) => (
                  <th
                    key={h}
                    style={{
                      textAlign: "left",
                      fontSize: "11px",
                      color: "var(--gray-500)",
                      textTransform: "uppercase",
                      letterSpacing: ".04em",
                      padding: "10px 12px",
                      borderBottom: "1px solid var(--gray-200)",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.linkClicks.map((row, i) => (
                <tr
                  key={i}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "var(--gray-50)")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "")}
                >
                  <td
                    style={{
                      padding: "12px",
                      borderBottom: "1px solid var(--gray-100)",
                      maxWidth: "340px",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    <a
                      href={row.link_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: "var(--blue-600)" }}
                    >
                      {row.link_url}
                    </a>
                  </td>
                  <td style={{ padding: "12px", borderBottom: "1px solid var(--gray-100)" }}>
                    {row.page_title}
                  </td>
                  <td
                    style={{
                      padding: "12px",
                      borderBottom: "1px solid var(--gray-100)",
                      fontWeight: 600,
                    }}
                  >
                    {row.click_count.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="bg-white rounded-[14px] p-[18px]"
      style={{ border: "1px solid var(--gray-200)" }}
    >
      <div className="text-[12px]" style={{ color: "var(--gray-500)" }}>
        {label}
      </div>
      <div className="text-[26px] font-extrabold mt-[6px] mb-[2px]">{value}</div>
    </div>
  );
}
