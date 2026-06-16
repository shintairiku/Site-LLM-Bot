"use client";

import { useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

const pageMeta: Record<string, { title: string; crumb: string }> = {
  "/prompt": { title: "プロンプト", crumb: "チャットボットの標準プロンプトを管理" },
  "/data": { title: "データ", crumb: "参照データソースの登録・管理" },
  "/analytics": { title: "分析", crumb: "利用状況とパフォーマンスの分析" },
  "/settings": { title: "設定", crumb: "チャットボットと表示の設定" },
};

interface TopbarProps {
  userEmail: string | null;
}

export default function Topbar({ userEmail }: TopbarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);

  const meta = pageMeta[pathname] ?? { title: "BotConsole", crumb: "" };
  const initial = userEmail ? userEmail[0].toUpperCase() : "?";

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
  }

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
          className="w-[38px] h-[38px] rounded-full flex items-center justify-center font-bold cursor-pointer select-none"
          style={{
            background: "var(--blue-600)",
            color: "#fff",
            border: "2px solid var(--blue-100)",
          }}
          onClick={() => setMenuOpen((v) => !v)}
        >
          {initial}
        </div>

        {menuOpen && (
          <>
            <div
              className="fixed inset-0 z-40"
              onClick={() => setMenuOpen(false)}
            />
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
                <span className="block text-[12px]" style={{ color: "var(--gray-500)" }}>
                  {userEmail}
                </span>
              </div>
              <button
                className="flex items-center gap-[10px] w-full px-3 py-[9px] rounded-lg text-[13px] text-left"
                style={{ color: "var(--red)" }}
                onClick={handleSignOut}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--gray-100)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                ⎋ ログアウト
              </button>
            </div>
          </>
        )}
      </div>
    </header>
  );
}
