"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

const errorMessages: Record<string, string> = {
  unauthorized: "このGoogleアカウントはアクセス権がありません。管理者にお問い合わせください。",
  auth_failed: "認証に失敗しました。もう一度お試しください。",
  missing_code: "認証コードが取得できませんでした。もう一度お試しください。",
};

export default function LoginForm() {
  const searchParams = useSearchParams();
  const callbackError = searchParams.get("error");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(
    callbackError ? (errorMessages[callbackError] ?? "ログインに失敗しました。") : null
  );

  async function handleGoogleLogin() {
    setLoading(true);
    setError(null);

    const supabase = createClient();
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${location.origin}/auth/callback`,
      },
    });

    if (error) {
      setError("ログインに失敗しました。もう一度お試しください。");
      setLoading(false);
    }
  }

  return (
    <>
      {error && (
        <div
          className="text-[13px] px-4 py-3 rounded-[9px] mb-4"
          style={{ background: "#fee2e2", color: "var(--red)" }}
        >
          {error}
        </div>
      )}

      <button
        onClick={handleGoogleLogin}
        disabled={loading}
        className="w-full flex items-center justify-center gap-3 py-3 rounded-[10px] text-[14px] font-semibold"
        style={{
          background: "#fff",
          border: "1px solid var(--gray-300)",
          color: "var(--gray-700)",
          opacity: loading ? 0.7 : 1,
          cursor: loading ? "not-allowed" : "pointer",
        }}
      >
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4"/>
          <path d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" fill="#34A853"/>
          <path d="M3.964 10.706A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.706V4.962H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.038l3.007-2.332z" fill="#FBBC05"/>
          <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.962L3.964 7.294C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
        </svg>
        {loading ? "ログイン中..." : "Googleでログイン"}
      </button>
    </>
  );
}
