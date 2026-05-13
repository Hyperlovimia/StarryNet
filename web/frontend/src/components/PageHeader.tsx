import type { ReactNode } from "react";

import { BreadcrumbItem, Breadcrumbs } from "./Breadcrumbs";

interface PageHeaderProps {
  title: string;
  description?: string;
  eyebrow?: string;
  tone?: "default" | "experiments" | "experiment" | "run" | "topology" | "events" | "tasks" | "create";
  breadcrumbs?: BreadcrumbItem[];
  actions?: ReactNode;
}

export function PageHeader({
  title,
  description,
  eyebrow,
  tone = "default",
  breadcrumbs,
  actions
}: PageHeaderProps) {
  return (
    <header className={`page-header page-header-${tone}`}>
      <div className="page-header-main">
        {breadcrumbs?.length ? <Breadcrumbs items={breadcrumbs} /> : null}
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h2>{title}</h2>
        <p className="page-description">{description}</p>
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}
