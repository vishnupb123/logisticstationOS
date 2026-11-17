import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { ChatLauncher } from "./ChatPanel";
import { CycleBanner } from "./CycleBanner";
import { NotificationBell } from "./Notifications";
import { SessionBar } from "./SessionBar";
import "./live.css";
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
  command: "M3 4h18v12H3zM8 20h8M12 16v4M7 12l3-3 2 2 4-4",
  truck: "M2 6h11v9H2zM13 9h4l3 3v3h-7M6 18a1.5 1.5 0 1 0 0-.1M17 18a1.5 1.5 0 1 0 0-.1",
  bot: "M5 8h14v11H5zM12 4v4M9 13h.01M15 13h.01M9 16h6",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  ferry: "M3 17c2 2 4 2 6 0s4-2 6 0 4 2 6 0M5 14l1-6h12l1 6M9 8V5h6v3",
  wrench: "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 3",
  waves: "M3 6h18M3 12h12M3 18h6",
  cart: "M3 4h2l2 11h11l2-8H7M9 20h.01M18 20h.01",
  stage: "M4 20V8l8-4 8 4v12M9 20v-6h6v6",
  pin: "M12 21s-7-6-7-11a7 7 0 0 1 14 0c0 5-7 11-7 11zM12 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  lock: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
  users: "M16 21v-2a4 4 0 0 0-8 0v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM20 21v-2a3 3 0 0 0-2-3M4 21v-2a3 3 0 0 1 2-3",
  calendar: "M4 6h16v15H4zM4 10h16M8 3v4M16 3v4",
  chat: "M4 5h16v11H8l-4 4z",
  layout: "M3 3h18v18H3zM3 9h18M9 9v12",
  doc: "M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7",
  rotate: "M20 11a8 8 0 0 0-14.7-4.3L3 9M3 4v5h5M4 13a8 8 0 0 0 14.7 4.3L21 15M21 20v-5h-5",
  sliders: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
  moon: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z",
};

const NAV_GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: "Operate",
    items: [
      { to: "/command", label: "Command Center", icon: ICON.command },
      { to: "/work-items", label: "Work Items", icon: ICON.list },
      { to: "/plan-vs-actual", label: "Plan vs. actual", icon: ICON.chart },
    ],
  },
  {
    title: "Inbound",
    items: [
      { to: "/inbound", label: "Receive & Linehauls", icon: ICON.truck },
    ],
  },
  {
    title: "Sort",
    items: [
      { to: "/induct", label: "Sort Overview", icon: ICON.flow },
      { to: "/stow", label: "Stow & Buffers", icon: ICON.box },
      { to: "/problem-solve", label: "Problem Solve", icon: ICON.wrench },
    ],
  },
  {
    title: "Package summary",
    items: [{ to: "/packages", label: "Dwell · Ageing · RTS", icon: ICON.clock }],
  },
  {
    title: "Outbound",
    items: [
      { to: "/outbound", label: "Outbound Overview", icon: ICON.waves },
      { to: "/pick", label: "Pick", icon: ICON.cart },
      { to: "/stage", label: "Stage", icon: ICON.stage },
      { to: "/dispatch", label: "Dispatch & DSPs", icon: ICON.pin },
      { to: "/high-value", label: "High Value", icon: ICON.lock },
    ],
  },
  {
    title: "After dispatch",
    items: [
      { to: "/closeout", label: "Close-out & Tomorrow", icon: ICON.moon },
      { to: "/report", label: "Shift report", icon: ICON.doc },
    ],
  },
  {
    title: "People",
    items: [
      { to: "/associates", label: "Associates", icon: ICON.users },
      { to: "/labor", label: "Shift Plan", icon: ICON.calendar },
      { to: "/rotation", label: "Shift rotation", icon: ICON.rotate },
    ],
  },
  {
    title: "AI",
    items: [
      { to: "/agent", label: "Agent Console", icon: ICON.bot },
      { to: "/assistant", label: "Station Assistant", icon: ICON.chat },
      { to: "/investigations", label: "Flow Investigations", icon: ICON.spark },
    ],
  },
  {
    title: "Analyze & govern",
    items: [
      { to: "/station", label: "Station & Resources", icon: ICON.layout },
      { to: "/simulation", label: "Scenario Runner", icon: ICON.cube },
      { to: "/rl", label: "Policy Comparison", icon: ICON.chart },
      { to: "/decisions", label: "Decisions & Audit", icon: ICON.shield },
      { to: "/settings", label: "Settings", icon: ICON.sliders },
    ],
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

function GlobalSearch() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (q.trim()) navigate(`/packages?tab=search&q=${encodeURIComponent(q.trim())}`);
      }}
    >
      <input className="topbar__search" aria-label="Search packages, routes, associates" placeholder="Search packages…" value={q} onChange={(e) => setQ(e.target.value)} />
    </form>
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
          <GlobalSearch />
          <NotificationBell />
          <Clock />
          <ThemeToggle />
        </header>
        <SessionBar />
        <CycleBanner />
        <main className="layout__content">{children}</main>
        <ChatLauncher />
      </div>
    </div>
  );
}
