import LoginFormPassword from "./LoginFormPassword";

export default function LoginPage() {
  return (
    <div
      className="min-h-screen flex items-center justify-center"
      style={{ background: "var(--gray-50)" }}
    >
      <div
        className="bg-white rounded-[16px] p-10 w-full max-w-[400px]"
        style={{ border: "1px solid var(--gray-200)", boxShadow: "0 10px 30px rgba(2,32,71,.08)" }}
      >
        <div className="flex items-center gap-3 mb-8">
          <div
            className="w-[36px] h-[36px] rounded-[10px] flex items-center justify-center font-bold text-white"
            style={{ background: "var(--blue-600)" }}
          >
            B
          </div>
          <div>
            <div className="font-bold text-[17px]" style={{ color: "var(--gray-900)" }}>
              BotConsole
            </div>
            <div className="text-[12px]" style={{ color: "var(--gray-500)" }}>
              管理ダッシュボード
            </div>
          </div>
        </div>

        <h1 className="text-[20px] font-bold mb-1" style={{ color: "var(--gray-900)" }}>
          ログイン
        </h1>
        <p className="text-[13px] mb-6" style={{ color: "var(--gray-500)" }}>
          管理者から発行されたメールアドレスとパスワードでログインしてください
        </p>

        <LoginFormPassword />
      </div>
    </div>
  );
}
