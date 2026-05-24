import { NavLink, Outlet, useLocation } from "react-router-dom";

import { appRoutes } from "../routes";

export function AppShell() {
  const location = useLocation();
  const runMatch = location.pathname.match(/^\/runs\/([^/]+)/);
  const experimentMatch = location.pathname.match(/^\/experiments\/([^/]+)/);
  const runId = runMatch?.[1] ?? null;
  const experimentId =
    experimentMatch?.[1] && experimentMatch[1] !== "new" ? experimentMatch[1] : null;

  const workspaceLinks = [
    { label: "Experiments", to: appRoutes.experiments(), caption: "Browse and monitor" },
  ];

  const contextLinks = runId
    ? [
        { label: "Map", to: appRoutes.runMapPath(runId) },
        { label: "Topology", to: appRoutes.runTopologyPath(runId) },
        { label: "Events", to: appRoutes.runEventsPath(runId) },
        { label: "Tasks", to: appRoutes.runTasksPath(runId) }
      ]
    : experimentId
      ? [{ label: "Experiment Overview", to: appRoutes.experimentDetailPath(experimentId) }]
      : [];

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="brand-block">
          <h1>StarryNet</h1>
          <p className="brand-copy">
            Build experiments, launch runs, and inspect satellite networks from one place.
          </p>
        </div>
        <section className="sidebar-section">
          <p className="sidebar-section-title">Workspace</p>
          <nav className="sidebar-nav">
            {workspaceLinks.map(link => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) => (isActive ? "nav-link nav-link-active" : "nav-link")}
              >
                <span className="nav-link-label">{link.label}</span>
                <span className="nav-link-caption">{link.caption}</span>
              </NavLink>
            ))}
          </nav>
        </section>
        {contextLinks.length ? (
          <section className="sidebar-section">
            <p className="sidebar-section-title">Current View</p>
            <nav className="sidebar-nav">
              {contextLinks.map(link => (
                <NavLink
                  key={link.to}
                  to={link.to}
                  className={({ isActive }) => (isActive ? "nav-link nav-link-active" : "nav-link")}
                >
                  <span className="nav-link-label">{link.label}</span>
                </NavLink>
              ))}
            </nav>
          </section>
        ) : null}
        <div className="sidebar-card">
          {/* <p className="sidebar-card-label">Navigation model</p>
          <p className="sidebar-card-copy">
            Use Workspace for top-level entry, then Current View for local movement inside an experiment or run.
          </p> */}
        </div>
      </aside>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
