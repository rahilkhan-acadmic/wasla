"use client";

import { useEffect, useId, useState } from "react";

// A card whose body can be folded away (Market Overview, Insolvency Watch).
// Accordion pattern: the heading holds a button with aria-expanded, so the
// toggle is keyboard- and screen-reader-friendly. Toolbar `actions` (search,
// filters) show only while open. The open/closed choice is remembered per
// browser under `storageKey`; storage may be unavailable (private mode), in
// which case the card simply starts in its default state.

const PREFIX = "wasla-card-open:";

function readStored(key: string | undefined): boolean | null {
  if (!key) return null;
  try {
    const v = window.localStorage.getItem(PREFIX + key);
    return v === null ? null : v === "1";
  } catch {
    return null;
  }
}

function writeStored(key: string | undefined, open: boolean) {
  if (!key) return;
  try {
    window.localStorage.setItem(PREFIX + key, open ? "1" : "0");
  } catch {
    // not persisted; fine
  }
}

export default function CollapsibleCard({
  title,
  storageKey,
  defaultOpen = true,
  actions,
  className = "",
  children,
}: {
  title: React.ReactNode;
  storageKey?: string;
  defaultOpen?: boolean;
  actions?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  const bodyId = useId();
  const [open, setOpen] = useState(defaultOpen);

  // Read after mount: the page is a static export, so the first render must
  // match the server-rendered HTML.
  useEffect(() => {
    const stored = readStored(storageKey);
    if (stored !== null) setOpen(stored);
  }, [storageKey]);

  function toggle() {
    setOpen((o) => {
      writeStored(storageKey, !o);
      return !o;
    });
  }

  return (
    <section className={`card collapsible ${open ? "" : "collapsed"} ${className}`.trim()}>
      <div className="table-toolbar collapsible-head">
        <h2>
          <button type="button" className="collapse-toggle" aria-expanded={open} aria-controls={bodyId} onClick={toggle}>
            <svg className="collapse-chevron" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                strokeLinejoin="round" />
            </svg>
            {title}
          </button>
        </h2>
        {open && actions && <div className="filters">{actions}</div>}
      </div>
      <div id={bodyId} hidden={!open}>
        {children}
      </div>
    </section>
  );
}
