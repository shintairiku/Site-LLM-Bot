"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { PenLine, FolderOpen, BarChart2, Settings } from "lucide-react";

const navItems = [
  { href: "/prompt", label: "プロンプト", icon: PenLine },
  { href: "/data", label: "データ", icon: FolderOpen },
  { href: "/analytics", label: "分析", icon: BarChart2 },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="w-[220px] flex flex-col flex-shrink-0 text-white"
      style={{ background: "linear-gradient(180deg, var(--blue-900), var(--blue-800))" }}
    >
      <div
        className="px-[18px] py-5 flex items-center gap-[10px]"
        style={{ borderBottom: "1px solid rgba(255,255,255,.1)" }}
      >
        <div
          className="w-[30px] h-[30px] rounded-lg flex items-center justify-center font-bold text-sm flex-shrink-0"
          style={{ background: "var(--blue-500)" }}
        >
          B
        </div>
        <div>
          <div className="font-bold text-[15px]">BotConsole</div>
          <div className="text-[11px]" style={{ color: "#9fb3d1" }}>
            管理ダッシュボード
          </div>
        </div>
      </div>

      <nav className="flex-1 p-3 flex flex-col gap-1">
        {navItems.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className="flex items-center gap-3 px-[14px] py-[11px] rounded-[10px] text-sm transition-all duration-150"
              style={{
                color: active ? "#fff" : "#cdd9ed",
                background: active ? "var(--blue-600)" : "transparent",
                fontWeight: active ? 600 : 400,
              }}
              onMouseEnter={(e) => {
                if (!active) {
                  e.currentTarget.style.background = "rgba(255,255,255,.08)";
                  e.currentTarget.style.color = "#fff";
                }
              }}
              onMouseLeave={(e) => {
                if (!active) {
                  e.currentTarget.style.background = "transparent";
                  e.currentTarget.style.color = "#cdd9ed";
                }
              }}
            >
              <Icon size={18} />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="p-3" style={{ borderTop: "1px solid rgba(255,255,255,.1)" }}>
        <Link
          href="/settings"
          className="flex items-center gap-3 px-[14px] py-[11px] rounded-[10px] text-sm transition-all duration-150"
          style={{
            color: pathname === "/settings" ? "#fff" : "#cdd9ed",
            background: pathname === "/settings" ? "var(--blue-600)" : "transparent",
            fontWeight: pathname === "/settings" ? 600 : 400,
          }}
          onMouseEnter={(e) => {
            if (pathname !== "/settings") {
              e.currentTarget.style.background = "rgba(255,255,255,.08)";
              e.currentTarget.style.color = "#fff";
            }
          }}
          onMouseLeave={(e) => {
            if (pathname !== "/settings") {
              e.currentTarget.style.background = "transparent";
              e.currentTarget.style.color = "#cdd9ed";
            }
          }}
        >
          <Settings size={18} />
          設定
        </Link>
      </div>
    </aside>
  );
}
