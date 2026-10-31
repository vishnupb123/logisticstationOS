import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import "./Layout.css";

const NAV = [
  { to: "/", label: "Station Overview" },
  { to: "/induct", label: "Induct & Sortation" },
  { to: "/stow", label: "Stow & Jackpot" },
  { to: "/investigations", label: "AI Investigations" },
  { to: "/simulation", label: "Digital Twin Runner" },
  { to: "/rl", label: "RL Policy Comparison" },
  { to: "/decisions", label: "Decisions & Audit" },
];

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="layout">
      <aside className="layout__sidebar">
        <div className="layout__brand">
          <div className="layout__brand-name">StationOS</div>
          <div className="layout__brand-sub">Station NOVA-1 — synthetic/fictional</div>
        </div>
        <nav className="layout__nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                "layout__nav-link" + (isActive ? " layout__nav-link--active" : "")
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="layout__footer">
          No real operational data anywhere in this app — see docs/SECURITY_AND_GOVERNANCE.md.
        </div>
      </aside>
      <main className="layout__content">{children}</main>
    </div>
  );
}
