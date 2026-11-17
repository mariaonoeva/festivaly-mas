import type { Metadata } from "next";
import "./globals.css";
import SiteHeader from "../components/SiteHeader";
import ChatPanel from "../components/ChatPanel";

export const metadata: Metadata = {
  title: "Festivaly — Find your next stage",
  description:
    "Explore Czech and Slovak festivals by genre, location and season, with links to the original sources.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <SiteHeader />
        {children}
        <ChatPanel />
      </body>
    </html>
  );
}
