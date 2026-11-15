"use client";

import { useCallback, useEffect, useState } from "react";
import Logo from "./Logo";
import ModelStatusPanel from "./ModelStatusPanel";
import { useSignOut } from "./AuthGate";
import {
  ChevronIcon,
  InsolvencyIcon,
  MarketIcon,
  MenuIcon,
  ModelIcon,
  ScoreIcon,
  SignOutIcon,
} from "./Icons";
import { ROUTES, RouteId, routeHref } from "../lib/routes";

const ROUTE_ICONS: Record<RouteId, React.ComponentType<{ size?: number }>> = {
  score: ScoreIcon,
  market: MarketIcon,
  insolvency: InsolvencyIcon,
  model: ModelIcon,
};

const PANEL_PREF_KEY = "wasla-panel-open";
// Below this width the panel overlays the page instead of pushing it.
const OVERLAY_QUERY = "(max-width: 899px)";

function readPanelPref(): boolean | null {
  try {
    const v = window.localStorage.getItem(PANEL_PREF_KEY);
    return v === null ? null : v === "1";
  } catch {
    return null;
  }
}

function writePanelPref(open: boolean) {
  try {
    window.localStorage.setItem(PANEL_PREF_KEY, open ? "1" : "0");
  } catch {
    // Storage blocked (private mode etc.) -- the panel still works, it just
    // won't remember its state.
  }
}

export default function AppShell({
  route,
  extraCrumb,
  children,
}: {
  route: RouteId;
  extraCrumb?: string | null;
  children: React.ReactNode;
}) {
  const signOut = useSignOut();
  const [overlay, setOverlay] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia(OVERLAY_QUERY);
    const apply = () => {
      setOverlay(mq.matches);
      // Overlay mode always starts closed; docked mode remembers the choice
      // and defaults to open.
      setOpen(mq.matches ? false : readPanelPref() ?? true);
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  const toggle = useCallback(() => {
    setOpen((prev) => {
      const next = !prev;
      if (!overlay) writePanelPref(next);
      return next;
    });
  }, [overlay]);

  // Escape closes the overlay panel.
  useEffect(() => {
    if (!(overlay && open)) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [overlay, open]);

  const current = ROUTES.find((r) => r.id === route)!;

  const breadcrumb = (
    <nav aria-label="Breadcrumb" className="breadcrumb">
      <ol>
        <li>
          <a href={routeHref("score")}>Home</a>
        </li>
        <li aria-hidden="true" className="crumb-sep">
          <ChevronIcon size={14} />
        </li>
        <li>
          {extraCrumb ? (
            <a href={routeHref(current.id)}>{current.label}</a>
          ) : (
            <span aria-current="page">{current.label}</span>
          )}
        </li>
        {extraCrumb && (
          <>
            <li aria-hidden="true" className="crumb-sep">
              <ChevronIcon size={14} />
            </li>
            <li>
              <span aria-current="page">{extraCrumb}</span>
            </li>
          </>
        )}
      </ol>
    </nav>
  );

  return (
    <div className={`app ${open ? "panel-open" : "panel-closed"} ${overlay ? "panel-overlay" : "panel-docked"}`}>
      <header className="topbar">
        <div className="topbar-start">
          <button
            type="button"
            className="icon-button"
            aria-label={open ? "Close navigation" : "Open navigation"}
            aria-expanded={open}
            aria-controls="side-panel"
            onClick={toggle}
          >
            <MenuIcon />
          </button>
          <a href={routeHref("score")} className="brand" aria-label="WASLA home">
            <Logo />
            <span className="brand-name">WASLA</span>
          </a>
        </div>

        <div className="topbar-center">{breadcrumb}</div>

        <div className="topbar-end">
          <button
            type="button"
            className="icon-button"
            onClick={signOut}
            aria-label="Sign out"
            title="Sign out"
          >
            <SignOutIcon />
          </button>
        </div>
      </header>

      <div className="breadcrumb-row">{breadcrumb}</div>

      <div className="app-body">
        <aside
          id="side-panel"
          className="side-panel"
          aria-label="Pages"
          // Hidden panels must not be reachable by keyboard.
          inert={!open}
        >
          <ul className="nav-list">
            {ROUTES.map((r) => {
              const Icon = ROUTE_ICONS[r.id];
              const active = r.id === route;
              return (
                <li key={r.id}>
                  <a
                    href={routeHref(r.id)}
                    className={`nav-item ${active ? "nav-item-active" : ""}`}
                    aria-current={active ? "page" : undefined}
                    onClick={() => overlay && setOpen(false)}
                  >
                    <Icon />
                    <span>{r.label}</span>
                    {r.comingSoon && <span className="soon-tag">Soon</span>}
                  </a>
                </li>
              );
            })}
          </ul>
          <div className="side-panel-footer">
            <ModelStatusPanel />
          </div>
        </aside>

        {overlay && open && (
          <div className="panel-backdrop" onClick={() => setOpen(false)} aria-hidden="true" />
        )}

        <main className="content">{children}</main>
      </div>

      <footer className="app-footer">Research/screening tool only — not investment advice.</footer>
    </div>
  );
}
