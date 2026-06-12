import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BotConsole",
  description: "チャットボット管理ダッシュボード",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja" className="h-full">
      <body className="h-full">{children}</body>
    </html>
  );
}
