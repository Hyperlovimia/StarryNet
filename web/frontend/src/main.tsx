import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";

import { AppShell } from "./app/AppShell";
import { CreateExperimentPage } from "./pages/CreateExperimentPage";
import { ExperimentDetailPage } from "./pages/ExperimentDetailPage";
import { ExperimentsPage } from "./pages/ExperimentsPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunEventsPage } from "./pages/RunEventsPage";
import { RunMapPage } from "./pages/RunMapPage";
import { RunTasksPage } from "./pages/RunTasksPage";
import { RunTopologyPage } from "./pages/RunTopologyPage";
import { appRoutes } from "./routes";
import "./styles.css";

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to={appRoutes.experiments()} replace /> },
      { path: appRoutes.experiments(), element: <ExperimentsPage /> },
      { path: appRoutes.experimentCreate(), element: <CreateExperimentPage /> },
      { path: appRoutes.experimentDetail(), element: <ExperimentDetailPage /> },
      { path: appRoutes.runDetail(), element: <RunDetailPage /> },
      { path: appRoutes.runMap(), element: <RunMapPage /> },
      { path: appRoutes.runTopology(), element: <RunTopologyPage /> },
      { path: appRoutes.runEvents(), element: <RunEventsPage /> },
      { path: appRoutes.runTasks(), element: <RunTasksPage /> }
    ]
  }
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
