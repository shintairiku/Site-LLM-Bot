"use client";

import { useState } from "react";
import { useDashboard, type PromptRecord } from "@/lib/dashboard-context";

function formatDate(iso: string) {
  const d = new Date(iso);
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function PromptEditor() {
  const { prompts, setPrompts } = useDashboard();
  const [content, setContent] = useState(() => prompts[0]?.content ?? "");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  async function handleSave() {
    setSaving(true);
    setMessage(null);
    const res = await fetch("/api/prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, note }),
    });
    if (res.ok) {
      const saved: PromptRecord = await res.json();
      setPrompts([saved, ...prompts]);
      setNote("");
      setMessage({ type: "ok", text: "保存しました" });
    } else {
      setMessage({ type: "err", text: "保存に失敗しました" });
    }
    setSaving(false);
  }

  function handleRevert(record: PromptRecord) {
    setContent(record.content);
    setNote(`${formatDate(record.created_at)} の版を復元`);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <div>
      <div className="flex items-start justify-between mb-[18px] flex-wrap gap-3">
        <div>
          <div className="text-[15px] font-bold">標準プロンプト</div>
          <div className="text-[12px]" style={{ color: "var(--gray-500)" }}>
            このテナントのチャットボットに常時適用される指示文
          </div>
        </div>
        <div className="flex gap-[10px]">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-[7px] px-4 py-[9px] rounded-[9px] text-[13px] font-semibold"
            style={{
              background: saving ? "var(--gray-300)" : "var(--blue-600)",
              color: "#fff",
              cursor: saving ? "not-allowed" : "pointer",
            }}
          >
            💾 {saving ? "保存中..." : "保存"}
          </button>
        </div>
      </div>

      {message && (
        <div
          className="text-[13px] px-4 py-3 rounded-[9px] mb-4"
          style={{
            background: message.type === "ok" ? "#dcfce7" : "#fee2e2",
            color: message.type === "ok" ? "var(--green)" : "var(--red)",
          }}
        >
          {message.text}
        </div>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 320px",
          gap: "18px",
        }}
      >
        {/* エディタ */}
        <div
          className="bg-white rounded-[14px] p-5"
          style={{ border: "1px solid var(--gray-200)" }}
        >
          <label
            className="block text-[12px] font-semibold mb-[6px]"
            style={{ color: "var(--gray-700)" }}
          >
            プロンプト本文
          </label>
          <textarea
            className="w-full rounded-[9px] p-[10px_12px] text-[13px] leading-relaxed"
            style={{ border: "1px solid var(--gray-300)", resize: "vertical", minHeight: "240px", fontFamily: "inherit" }}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            onFocus={(e) => {
              e.currentTarget.style.outline = "none";
              e.currentTarget.style.borderColor = "var(--blue-500)";
              e.currentTarget.style.boxShadow = "0 0 0 3px var(--blue-100)";
            }}
            onBlur={(e) => {
              e.currentTarget.style.borderColor = "var(--gray-300)";
              e.currentTarget.style.boxShadow = "none";
            }}
          />
          <div className="mt-[14px]">
            <label
              className="block text-[12px] font-semibold mb-[6px]"
              style={{ color: "var(--gray-700)" }}
            >
              変更メモ（任意）
            </label>
            <input
              type="text"
              className="w-full rounded-[9px] p-[10px_12px] text-[13px]"
              style={{ border: "1px solid var(--gray-300)", fontFamily: "inherit" }}
              placeholder="例：イベント案内の文言を追加"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onFocus={(e) => {
                e.currentTarget.style.outline = "none";
                e.currentTarget.style.borderColor = "var(--blue-500)";
                e.currentTarget.style.boxShadow = "0 0 0 3px var(--blue-100)";
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = "var(--gray-300)";
                e.currentTarget.style.boxShadow = "none";
              }}
            />
          </div>
        </div>

        {/* 変更履歴 */}
        <div
          className="bg-white rounded-[14px] p-5"
          style={{ border: "1px solid var(--gray-200)" }}
        >
          <div className="text-[15px] font-bold mb-[14px]">変更履歴</div>
          {prompts.length === 0 ? (
            <p className="text-[13px]" style={{ color: "var(--gray-500)" }}>
              まだ保存履歴がありません
            </p>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {prompts.map((r, i) => (
                <li
                  key={r.id}
                  style={{
                    position: "relative",
                    paddingLeft: "22px",
                    paddingBottom: i < prompts.length - 1 ? "18px" : "0",
                    borderLeft: i < prompts.length - 1 ? "2px solid var(--gray-200)" : "2px solid transparent",
                  }}
                >
                  <span
                    style={{
                      position: "absolute",
                      left: "-7px",
                      top: "2px",
                      width: "12px",
                      height: "12px",
                      borderRadius: "50%",
                      background: i === 0 ? "var(--blue-500)" : "var(--gray-300)",
                      border: "2px solid #fff",
                      boxShadow: i === 0 ? "0 0 0 2px var(--blue-100)" : "none",
                      display: "block",
                    }}
                  />
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="text-[11px]" style={{ color: "var(--gray-500)" }}>
                      {formatDate(r.created_at)}
                      {r.created_by && ` ・ ${r.created_by.split("@")[0]}`}
                    </div>
                    {i === 0 && (
                      <span
                        className="text-[10px] font-bold px-2 py-[2px] rounded-full"
                        style={{ background: "var(--blue-100)", color: "var(--blue-700)" }}
                      >
                        現在の版
                      </span>
                    )}
                  </div>
                  {r.note && (
                    <div
                      className="text-[12px] mt-1 px-[10px] py-2 rounded-lg"
                      style={{
                        background: "var(--gray-50)",
                        border: "1px solid var(--gray-200)",
                        color: "var(--gray-700)",
                      }}
                    >
                      {r.note}
                    </div>
                  )}
                  {i > 0 && (
                    <button
                      className="text-[11px] mt-[6px]"
                      style={{ color: "var(--blue-600)", cursor: "pointer", background: "none", border: "none", padding: 0 }}
                      onClick={() => handleRevert(r)}
                    >
                      この版に戻す
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
