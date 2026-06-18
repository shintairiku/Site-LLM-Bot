"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

export default function LoginFormPassword() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const supabase = createClient();

    const { error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (signInError) {
      setError("メールアドレスまたはパスワードが正しくありません。");
      setLoading(false);
      return;
    }

    // tenant_membersに登録されているか確認
    const { data: member } = await supabase
      .from("tenant_members")
      .select("tenant_id")
      .eq("email", email)
      .single();

    if (!member) {
      await supabase.auth.signOut();
      setError("このアカウントはアクセス権がありません。管理者にお問い合わせください。");
      setLoading(false);
      return;
    }

    router.push("/prompt");
    router.refresh();
  }

  return (
    <form onSubmit={handleLogin}>
      {error && (
        <div
          className="text-[13px] px-4 py-3 rounded-[9px] mb-4"
          style={{ background: "#fee2e2", color: "var(--red)" }}
        >
          {error}
        </div>
      )}

      <div className="mb-4">
        <label
          className="block text-[12px] font-semibold mb-[6px]"
          style={{ color: "var(--gray-700)" }}
        >
          メールアドレス
        </label>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-[9px] px-3 py-[10px] text-[13px]"
          style={{ border: "1px solid var(--gray-300)", fontFamily: "inherit" }}
          placeholder="admin@example.com"
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

      <div className="mb-6">
        <label
          className="block text-[12px] font-semibold mb-[6px]"
          style={{ color: "var(--gray-700)" }}
        >
          パスワード
        </label>
        <input
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-[9px] px-3 py-[10px] text-[13px]"
          style={{ border: "1px solid var(--gray-300)", fontFamily: "inherit" }}
          placeholder="••••••••"
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

      <button
        type="submit"
        disabled={loading}
        className="w-full py-3 rounded-[10px] text-[14px] font-semibold"
        style={{
          background: loading ? "var(--gray-300)" : "var(--blue-600)",
          color: "#fff",
          cursor: loading ? "not-allowed" : "pointer",
          border: "none",
        }}
      >
        {loading ? "ログイン中..." : "ログイン"}
      </button>
    </form>
  );
}
