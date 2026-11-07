import type { ReactNode } from "react";
import "./PageHeader.css";

export function PageHeader({
  eyebrow,
  title,
  badges,
  actions,
  children,
}: {
  eyebrow?: string;
  title: string;
  badges?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div className="page-header__main">
        {eyebrow && <div className="page-header__eyebrow">{eyebrow}</div>}
        <div className="page-header__title-row">
          <h1>{title}</h1>
          {badges}
        </div>
        {children && <div className="page-header__desc">{children}</div>}
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </header>
  );
}
