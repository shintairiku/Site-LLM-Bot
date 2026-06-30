"use client";

import { useRef, useState } from "react";
import { useDashboard, type DataSource } from "@/lib/dashboard-context";

const KIND_LABEL: Record<DataSource["kind"], string> = {
  pdf: "PDF",
  text: "テキスト",
  url: "URL",
};

const KIND_ICON: Record<DataSource["kind"], string> = {
  pdf: "📄",
  text: "📝",
  url: "🔗",
};

function formatDate(iso: string) {
  const d = new Date(iso);
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function formatBytes(bytes: number | null): string {
  if (!bytes) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DataManager() {
  const { dataSources, setDataSources } = useDashboard();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    setMessage(null);
    let added: DataSource[] = [];
    let failed = 0;
    for (const file of Array.from(files)) {
      const form = new FormData();
      form.append("file", file);
      try {
        const res = await fetch("/api/data-sources", { method: "POST", body: form });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? "失敗");
        added = [data, ...added];
      } catch (e) {
        failed++;
        setMessage({ type: "err", text: `${file.name}: ${(e as Error).message}` });
      }
    }
    if (added.length > 0) setDataSources([...added, ...dataSources]);
    if (failed === 0 && added.length > 0) {
      setMessage({ type: "ok", text: `${added.length}件のファイルを取り込みました` });
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
    setBusy(false);
  }

  async function handleAddUrl() {
    const trimmed = url.trim();
    if (!trimmed) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await fetch("/api/data-sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: trimmed }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "失敗");
      setDataSources([data, ...dataSources]);
      setUrl("");
      setMessage({ type: "ok", text: "URLを取り込みました" });
    } catch (e) {
      setMessage({ type: "err", text: `URL取り込みに失敗: ${(e as Error).message}` });
    }
    setBusy(false);
  }

  async function handleDelete(id: string) {
    setDeletingId(id);
    setMessage(null);
    try {
      const res = await fetch(`/api/data-sources?id=${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error ?? "失敗");
      }
      setDataSources(dataSources.filter((d) => d.id !== id));
    } catch (e) {
      setMessage({ type: "err", text: `削除に失敗: ${(e as Error).message}` });
    }
    setDeletingId(null);
  }

  return (
    <div>
      <div className="mb-[18px]">
        <div className="text-[15px] font-bold">データソース</div>
        <div className="text-[12px]" style={{ color: "var(--gray-500)" }}>
          PDF・テキスト・URLを取り込み、質問に応じてチャットボットが必要時に参照します
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

      {/* 取り込みパネル */}
      <div
        style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "18px" }}
      >
        {/* ファイル */}
        <div
          className="bg-white rounded-[14px] p-5"
          style={{ border: "1px solid var(--gray-200)" }}
        >
          <div className="text-[13px] font-bold mb-1">ファイルを追加</div>
          <div className="text-[12px] mb-3" style={{ color: "var(--gray-500)" }}>
            PDF / txt / md（最大25MB・複数選択可）
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.txt,.md"
            multiple
            disabled={busy}
            onChange={(e) => handleFiles(e.target.files)}
            className="block w-full text-[13px] text-[color:var(--gray-700)]
              file:mr-3 file:py-[8px] file:px-4 file:rounded-[9px] file:border-0
              file:text-[13px] file:font-semibold file:text-white
              file:bg-[color:var(--blue-600)] hover:file:bg-[color:var(--blue-700)]
              file:cursor-pointer file:disabled:opacity-65"
          />
        </div>

        {/* URL */}
        <div
          className="bg-white rounded-[14px] p-5"
          style={{ border: "1px solid var(--gray-200)" }}
        >
          <div className="text-[13px] font-bold mb-1">URLを追加</div>
          <div className="text-[12px] mb-3" style={{ color: "var(--gray-500)" }}>
            ページ本文を取得して取り込みます
          </div>
          <div className="flex gap-2">
            <input
              type="url"
              placeholder="https://example.com/page"
              value={url}
              disabled={busy}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleAddUrl();
              }}
              className="flex-1 rounded-[9px] p-[8px_12px] text-[13px]"
              style={{ border: "1px solid var(--gray-300)", fontFamily: "inherit" }}
            />
            <button
              onClick={handleAddUrl}
              disabled={busy || !url.trim()}
              className="px-4 rounded-[9px] text-[13px] font-semibold"
              style={{
                background: busy || !url.trim() ? "var(--gray-300)" : "var(--blue-600)",
                color: "#fff",
                cursor: busy || !url.trim() ? "not-allowed" : "pointer",
                whiteSpace: "nowrap",
              }}
            >
              追加
            </button>
          </div>
        </div>
      </div>

      {busy && (
        <div className="text-[13px] mb-4" style={{ color: "var(--blue-700)" }}>
          取り込み中です… 完了までこのままお待ちください
        </div>
      )}

      {/* 一覧 */}
      <div className="bg-white rounded-[14px] p-5" style={{ border: "1px solid var(--gray-200)" }}>
        <div className="text-[15px] font-bold mb-4">
          取り込み済みデータ（{dataSources.length}件）
        </div>
        {dataSources.length === 0 ? (
          <p className="text-[13px]" style={{ color: "var(--gray-500)" }}>
            まだデータがありません。上のパネルから追加してください。
          </p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr>
                {["種別", "タイトル", "サイズ", "追加日時", ""].map((h) => (
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
              {dataSources.map((d) => (
                <tr key={d.id}>
                  <td style={{ padding: "12px", borderBottom: "1px solid var(--gray-100)", whiteSpace: "nowrap" }}>
                    {KIND_ICON[d.kind]} {KIND_LABEL[d.kind]}
                  </td>
                  <td
                    style={{
                      padding: "12px",
                      borderBottom: "1px solid var(--gray-100)",
                      maxWidth: "360px",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {d.source_url ? (
                      <a
                        href={d.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ color: "var(--blue-600)" }}
                      >
                        {d.title}
                      </a>
                    ) : (
                      d.title
                    )}
                  </td>
                  <td style={{ padding: "12px", borderBottom: "1px solid var(--gray-100)", whiteSpace: "nowrap", color: "var(--gray-500)" }}>
                    {formatBytes(d.bytes)}
                    {d.chunk_count ? ` ・ ${d.chunk_count}チャンク` : ""}
                  </td>
                  <td style={{ padding: "12px", borderBottom: "1px solid var(--gray-100)", whiteSpace: "nowrap", color: "var(--gray-500)" }}>
                    {formatDate(d.created_at)}
                  </td>
                  <td style={{ padding: "12px", borderBottom: "1px solid var(--gray-100)", textAlign: "right" }}>
                    <button
                      onClick={() => handleDelete(d.id)}
                      disabled={deletingId === d.id}
                      className="text-[12px]"
                      style={{
                        color: "var(--red)",
                        background: "none",
                        border: "none",
                        cursor: deletingId === d.id ? "not-allowed" : "pointer",
                        padding: 0,
                      }}
                    >
                      {deletingId === d.id ? "削除中…" : "削除"}
                    </button>
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
