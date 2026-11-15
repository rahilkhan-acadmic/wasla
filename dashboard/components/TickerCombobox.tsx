"use client";

import { useId, useMemo, useRef, useState } from "react";
import { CompanySummary } from "../lib/api";

const MAX_OPTIONS = 50;

function rank(c: CompanySummary, q: string): number {
  const sym = c.symbol.toUpperCase();
  const name = c.name.toUpperCase();
  if (sym === q) return 0;
  if (sym.startsWith(q)) return 1;
  if (name.startsWith(q)) return 2;
  if (sym.includes(q) || name.includes(q)) return 3;
  return -1;
}

// Editable combobox (ARIA 1.2 pattern): type freely, or pick an index
// constituent from the list. Picking calls onSelect; typing calls onChange,
// and the parent decides whether to search for typed text.
export default function TickerCombobox({
  value,
  onChange,
  onSelect,
  companies,
  hint,
}: {
  value: string;
  onChange: (text: string) => void;
  onSelect: (c: CompanySummary) => void;
  companies: CompanySummary[];
  hint?: React.ReactNode;
}) {
  const id = useId();
  const listId = `${id}-list`;
  const hintId = `${id}-hint`;
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);

  const matches = useMemo(() => {
    const q = value.trim().toUpperCase();
    if (!q) return companies.slice(0, MAX_OPTIONS);
    return companies
      .map((c) => [c, rank(c, q)] as const)
      .filter(([, r]) => r >= 0)
      .sort((a, b) => a[1] - b[1] || a[0].symbol.localeCompare(b[0].symbol))
      .slice(0, MAX_OPTIONS)
      .map(([c]) => c);
  }, [value, companies]);

  const showList = open && companies.length > 0 && matches.length > 0;

  function choose(c: CompanySummary) {
    onSelect(c);
    setOpen(false);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) setOpen(true);
      setActive((i) => Math.min(i + 1, matches.length - 1));
      scrollActive(active + 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
      scrollActive(active - 1);
    } else if (e.key === "Enter" && showList && matches[active]) {
      e.preventDefault();
      choose(matches[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  function scrollActive(i: number) {
    const el = listRef.current?.children[Math.max(0, Math.min(i, matches.length - 1))] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }

  return (
    <div className="combobox">
      <label htmlFor={`${id}-input`}>Ticker</label>
      <input
        id={`${id}-input`}
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showList && matches[active] ? `${id}-opt-${active}` : undefined}
        aria-describedby={hint ? hintId : undefined}
        autoComplete="off"
        spellCheck={false}
        placeholder={companies.length ? "Search NSE LargeMidcap 250, or type any ticker" : "e.g. RELIANCE or TCS.NS"}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        // Delay so a click on an option registers before the list closes.
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={onKeyDown}
        required
      />
      {showList && (
        <ul id={listId} role="listbox" className="combobox-list" ref={listRef}>
          {matches.map((c, i) => (
            <li
              key={c.symbol}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              className={`combobox-option ${i === active ? "combobox-option-active" : ""}`}
              onMouseDown={(e) => e.preventDefault()}
              onMouseEnter={() => setActive(i)}
              onClick={() => choose(c)}
            >
              <span className="opt-symbol">{c.symbol}</span>
              <span className="opt-name">{c.name}</span>
              {!c.has_financials && <span className="opt-flag">partial data</span>}
            </li>
          ))}
        </ul>
      )}
      {hint && (
        <div id={hintId} className="field-hint">
          {hint}
        </div>
      )}
    </div>
  );
}
