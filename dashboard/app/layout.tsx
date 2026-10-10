import "./globals.css";
import ModelStatusPanel from "../components/ModelStatusPanel";

export const metadata = {
  title: "Financial Distress Screening",
  description: "Research/screening tool -- not investment advice.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header>
          <h1>Financial Distress Screening</h1>
          <ModelStatusPanel />
        </header>
        <main>{children}</main>
        <footer>Research/screening tool only -- not investment advice.</footer>
      </body>
    </html>
  );
}
