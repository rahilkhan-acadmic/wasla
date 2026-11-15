// WASLA mark: a rounded tile holding a "W" drawn as a price line that ends
// in a dot -- reads as both the initial and a chart. Inline SVG so it stays
// crisp at any size. The same drawing is in public/favicon.svg.

export default function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
      className="logo-mark"
    >
      <rect width="32" height="32" rx="8" fill="var(--brand)" />
      <polyline
        points="6,10 10.5,22 16,13.5 21.5,22 25,12"
        fill="none"
        stroke="#ffffff"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="25" cy="12" r="2.6" fill="#ffffff" />
    </svg>
  );
}
