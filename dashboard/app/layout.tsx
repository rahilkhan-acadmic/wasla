import "./globals.css";
import AuthGate from "../components/AuthGate";

export const metadata = {
  title: "WASLA",
  description: "Financial distress screening. Research/screening tool, not investment advice.",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthGate>{children}</AuthGate>
      </body>
    </html>
  );
}
