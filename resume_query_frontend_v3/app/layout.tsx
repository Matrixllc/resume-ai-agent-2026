import "./globals.css";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "简历候选人库",
  description: "候选人档案、项目经历与总结展示",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
