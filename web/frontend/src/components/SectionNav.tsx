import { NavLink } from "react-router-dom";

interface SectionNavItem {
  label: string;
  to: string;
  description?: string;
}

interface SectionNavProps {
  title: string;
  items: SectionNavItem[];
}

export function SectionNav({ title, items }: SectionNavProps) {
  return (
    <section className="section-nav">
      <p className="section-nav-title">{title}</p>
      <div className="section-nav-grid">
        {items.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              isActive ? "section-nav-link section-nav-link-active" : "section-nav-link"
            }
          >
            <span className="section-nav-link-label">{item.label}</span>
            {item.description ? <span className="section-nav-link-copy">{item.description}</span> : null}
          </NavLink>
        ))}
      </div>
    </section>
  );
}
