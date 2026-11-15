// Placeholder for pages in the agreed redesign plan that need backend work
// first (doc/PROGRESS_STATUS.md, "Dashboard redesign").

const CONTENT = {
  market: {
    title: "Market Overview",
    body: [
      "How the Nifty LargeMidcap 250 splits into Low, Moderate and High risk, with a separate count of loss-making companies.",
      "Needs a weekly job that fetches and scores all 250 companies, which is planned next.",
    ],
  },
  insolvency: {
    title: "Insolvency Watch",
    body: [
      "Major listed Indian companies that entered the insolvency process (CIRP) since 2016: when, and what happened next — acquired, liquidated, ongoing or withdrawn.",
      "Built from a hand-checked list with a source link for every case.",
    ],
  },
} as const;

export default function ComingSoonPage({ page }: { page: keyof typeof CONTENT }) {
  const c = CONTENT[page];
  return (
    <section className="card coming-soon">
      <span className="soon-tag">Coming soon</span>
      <h2>{c.title}</h2>
      {c.body.map((p) => (
        <p key={p}>{p}</p>
      ))}
    </section>
  );
}
