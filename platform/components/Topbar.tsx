"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";

const pageMeta: Record<string, { title: string; crumb: string }> = {
  "/prompt": { title: "プロンプト", crumb: "チャットボットの標準プロンプトを管理" },
  "/data": { title: "データ", crumb: "参照データソースの登録・管理" },
  "/analytics": { title: "分析", crumb: "利用状況とパフォーマンスの分析" },
  "/settings": { title: "設定", crumb: "チャットボットと表示の設定" },
};

export default function Topbar() {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  const meta = pageMeta[pathname] ?? { title: "BotConsole", crumb: "" };

  return (
    <header
      className="h-[60px] bg-white flex items-center justify-between px-6 flex-shrink-0"
      style={{ borderBottom: "1px solid var(--gray-200)" }}
    >
      <div>
        <h1 className="text-[18px] font-bold">{meta.title}</h1>
        <div className="text-[12px]" style={{ color: "var(--gray-500)" }}>
          {meta.crumb}
        </div>
      </div>

      <div className="flex items-center gap-4 relative">
        <div
          className="flex items-center gap-2 px-3 py-[7px] rounded-full text-[13px] font-semibold cursor-pointer"
          style={{
            background: "var(--blue-50)",
            border: "1px solid var(--blue-100)",
            color: "var(--blue-700)",
          }}
        >
          🏢 <span>テナント名</span> ▾
        </div>

        <div
          className="w-[38px] h-[38px] rounded-full flex items-center justify-center font-bold cursor-pointer"
          style={{
            background: "var(--blue-600)",
            color: "#fff",
            border: "2px solid var(--blue-100)",
          }}
          onClick={() => setMenuOpen((v) => !v)}
        >
          管
        </div>

        {menuOpen && (
          <div
            className="absolute top-[50px] right-0 bg-white rounded-[12px] w-[230px] p-2 z-50"
            style={{
              border: "1px solid var(--gray-200)",
              boxShadow: "0 10px 30px rgba(2,32,71,.15)",
            }}
          >
            <div
              className="px-3 py-[10px] mb-[6px]"
              style={{ borderBottom: "1px solid var(--gray-100)" }}
            >
              <b className="block text-[14px]">管理者</b>
              <span className="text-[12px]" style={{ color: "var(--gray-500)" }}>
                admin@example.com
              </span>
            </div>
            <button
              className="flex items-center gap-[10px] w-full px-3 py-[9px] rounded-lg text-[13px] text-left hover:bg-gray-100"
              style={{ color: "var(--red)" }}
              onClick={() => setMenuOpen(false)}
            >
              ⎋ ログアウト
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
