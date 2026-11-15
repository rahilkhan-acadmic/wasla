// Field definitions shared by the score form and the financials chart.

export const REQUIRED_FIELDS = [
  ["total_assets", "Total assets"],
  ["total_liabilities", "Total liabilities"],
  ["current_assets", "Current assets"],
  ["current_liabilities", "Current liabilities"],
  ["retained_earnings", "Retained earnings"],
  ["ebit", "EBIT"],
  ["sales", "Sales"],
] as const;

export const OPTIONAL_FIELDS = [
  ["market_value_equity", "Market value of equity"],
  ["book_value_equity", "Book value of equity"],
] as const;

export type FieldKey =
  | (typeof REQUIRED_FIELDS)[number][0]
  | (typeof OPTIONAL_FIELDS)[number][0];

export type FormValues = Partial<Record<FieldKey, string>>;

export function parseValue(raw: string | undefined): number | null {
  if (raw === undefined || raw.trim() === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
const full = new Intl.NumberFormat("en", { maximumFractionDigits: 2 });

// Compact beside the bars ("1.2B", or "₹1.2T" when the currency is known);
// full in the table view.
export function formatCompact(n: number, currency: string | null = null): string {
  if (currency) {
    try {
      return new Intl.NumberFormat("en", {
        notation: "compact",
        maximumFractionDigits: 1,
        style: "currency",
        currency,
        currencyDisplay: "narrowSymbol",
      }).format(n);
    } catch {
      // Unknown currency code -- fall through to the plain format.
    }
  }
  return compact.format(n);
}

export function formatFull(n: number): string {
  return full.format(n);
}
