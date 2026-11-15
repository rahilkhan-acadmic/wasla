"use client";

import { useEffect, useId, useRef, useState } from "react";
import { SearchResult } from "../lib/api";

// Editable combobox (ARIA 1.2 pattern). The page decides what the options
// are -- local index matches for 1-2 typed characters, backend search
// results (index + Yahoo Finance) from 3 -- and this just shows them, with
// keyboard support. Picking an option calls onSelect; typing calls onChange.
export default function TickerCombobox({
  value,
  onChange,
  onSelect,
  options,
  status,
  hint,
  closeSignal = 0,
}: {
  value: string;
  onChange: (text: string) => void;
  onSelect: (r: SearchResult) => void;
  options: SearchResult[];
  status?: React.ReactNode; // e.g. "Searching…" shown inside the open list
  hint?: React.ReactNode;
  // Bump to close the list from outside, e.g. after the page auto-fills a
  // single search match while the input still has focus.
  closeSignal?: number;
}) {
  const id = useId();
  const listId = `${id}-list`;
  const hintId = `${id}-hint`;
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (closeSignal) setOpen(false);
  }, [closeSignal]);

  const showList = open && (options.length > 0 || !!status);

  function choose(r: SearchResult) {
    onSelect(r);
    setOpen(false);
  }

  function scrollTo(i: number) {
    const el = listRef.current?.querySelectorAll('[role="option"]')[i] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      const i = Math.min(active + 1, options.length - 1);
      setActive(i);
      scrollTo(i);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const i = Math.max(active - 1, 0);
      setActive(i);
      scrollTo(i);
    } else if (e.key === "Enter" && showList && options[active]) {
      e.preventDefault();
      choose(options[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="combobox">
      <label htmlFor={`${id}-input`}>Ticker or company name</label>
      <input
        id={`${id}-input`}
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showList && options[active] ? `${id}-opt-${active}` : undefined}
        aria-describedby={hint ? hintId : undefined}
        autoComplete="off"
        spellCheck={false}
        placeholder="e.g. TCS, AAPL or “Tata Power”"
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
          {options.map((r, i) => (
            <li
              key={r.yahoo_ticker}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              className={`combobox-option ${i === active ? "combobox-option-active" : ""}`}
              onMouseDown={(e) => e.preventDefault()}
              onMouseEnter={() => setActive(i)}
              onClick={() => choose(r)}
            >
              <span className="opt-symbol">{r.symbol}</span>
              <span className="opt-name">{r.name}</span>
              <span className="opt-flag">
                {r.in_index
                  ? r.has_financials === false
                    ? "partial data"
                    : r.index_label ?? "LargeMidcap 250"
                  : r.exchange ?? "online"}
              </span>
            </li>
          ))}
          {status && (
            <li className="combobox-status" role="presentation">
              {status}
            </li>
          )}
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
