import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api/client";
import "./Layout.css";

interface NavItem {
  to: string;
  label: string;
  icon: string; // an SVG path (24x24 viewBox)
}

const ICON = {
  pulse: "M3 12h4l3-8 4 16 3-8h4",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  flow: "M4 6h10M4 12h16M4 18h7",
  box: "M3 7l9-4 9 4-9 4-9-4zM3 7v10l9 4 9-4V7",
  spark: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6",
  cube: "M12 2l9 5v10l-9 5-9-5V7zM12 12l9-5M12 12v10M12 12L3 7",
  chart: "M4 20V10M10 20V4M16 20v-8M22 20H2",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
};

const NAV_GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: "Operate",
    items: [
      { to: "/live", label: "Live Operations", icon: ICON.pulse },
      { to: "/", label: "Station Overview", icon: ICON.grid },
      { to: "/induct", label: "Induct & Sortation", icon: ICON.flow },
      { to: "/stow", label: "Stow & Jackpot", icon: ICON.box },
    ],
  },
  {
    title: "Analyze",
    items: [
      { to: "/investigations", label: "AI Investigations", icon: ICON.spark },
      { to: "/simulation", label: "Scenario Runner", icon: ICON.cube },
      { to: "/rl", label: "Policy Comparison", icon: ICON.chart },
    ],
  },
  {
    title: "Govern",
    items: [{ to: "/decisions", label: "Decisions & Audit", icon: ICON.shield }],
  },
];

interface Health {
  status: string;
  dependencies: Record<string, string>;
}

function Icon({ path }: { path: string }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={path} />
    </svg>
  );
}

function HealthIndicator() {
  // Polled — this is the one thing in the shell that should always be
  // current: whether the backend and its stores are actually reachable.
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<Health>("/health/ready"),
    refetchInterval: 10_000,
  });
  const ok = health.data?.status === "ok";
  const label = health.isLoading ? "Checking…" : ok ? "All systems operational" : "Backend degraded";
  const deps = health.data?.dependencies ?? {};
  return (
    <div
      className={`health health--${health.isLoading ? "pending" : ok ? "ok" : "down"}`}
      data-testid="health-indicator"
      title={
        health.error
          ? "Backend unreachable"
          : Object.entries(deps)
              .map(([k, v]) => `${k}: ${v}`)
              .join(" · ")
      }
    >
      <span className="health__dot" aria-hidden />
      <span>{health.error ? "Backend unreachable" : label}</span>
      {Object.entries(deps).map(([name, state]) => (
        <span key={name} className={`health__dep health__dep--${state === "ok" ? "ok" : "down"}`}>
          {name}
        </span>
      ))}
    </div>
  );
}

type Theme = "light" | "dark" | "system";

function readTheme(): Theme {
  try {
    return (localStorage.getItem("stationos-theme") as Theme) || "system";
  } catch {
    return "system";
  }
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("stationos-theme", theme);
    } catch {
      // storage unavailable — theme still applies for this session
    }
  }, [theme]);
  return (
    <select
      className="theme-toggle"
      aria-label="Color theme"
      value={theme}
      onChange={(e) => setTheme(e.target.value as Theme)}
    >
      <option value="system">System theme</option>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
    </select>
  );
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <span className="topbar__clock">
      {now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
    </span>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className={"layout" + (navOpen ? " layout--nav-open" : "")}>
      <aside className="layout__sidebar">
        <div className="layout__brand">
          <div className="layout__logo" aria-hidden>
            S
          </div>
          <div>
            <div className="layout__brand-name">StationOS</div>
            <div className="layout__brand-sub">Station NOVA-1 · fictional</div>
          </div>
        </div>
        <nav className="layout__nav" aria-label="Primary">
          {NAV_GROUPS.map((group) => (
            <div key={group.title} className="layout__nav-group">
              <div className="layout__nav-title">{group.title}</div>
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  onClick={() => setNavOpen(false)}
                  className={({ isActive }) =>
                    "layout__nav-link" + (isActive ? " layout__nav-link--active" : "")
                  }
                >
                  <Icon path={item.icon} />
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="layout__footer">
          Synthetic &amp; simulated data only — no real operational, employee, or customer data.
        </div>
      </aside>
      <div className="layout__main">
        <header className="topbar">
          <button
            className="topbar__menu"
            aria-label="Toggle navigation"
            onClick={() => setNavOpen((o) => !o)}
          >
            ☰
          </button>
          <div className="topbar__env">
            <span className="topbar__env-pill">LOCAL · DEV</span>
          </div>
          <HealthIndicator />
          <div className="topbar__spacer" />
          <Clock />
          <ThemeToggle />
        </header>
        <main className="layout__content">{children}</main>
      </div>
    </div>
  );
}
