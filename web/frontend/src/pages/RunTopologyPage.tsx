import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingBlock } from "../components/LoadingBlock";
import { PageHeader } from "../components/PageHeader";
import { apiClient } from "../lib/api/client";
import { useAsyncData } from "../lib/hooks";
import type { TopologyNode } from "../lib/models";
import { appRoutes } from "../routes";

const SVG_WIDTH = 920;
const SVG_HEIGHT = 560;

function projectNodes(nodes: TopologyNode[]) {
  const positionedNodes = nodes.filter(node => node.position && node.position.length >= 3);
  if (!positionedNodes.length) {
    return new Map<string, { x: number; y: number }>();
  }

  const xs = positionedNodes.map(node => node.position![0]);
  const ys = positionedNodes.map(node => node.position![2]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);

  return new Map(
    positionedNodes.map(node => [
      node.name,
      {
        x: 60 + ((node.position![0] - minX) / spanX) * (SVG_WIDTH - 120),
        y: 60 + ((node.position![2] - minY) / spanY) * (SVG_HEIGHT - 120)
      }
    ])
  );
}

function nodeColor(nodeType: string): string {
  if (nodeType === "sat") {
    return "#205493";
  }
  if (nodeType === "gs") {
    return "#d97706";
  }
  if (nodeType === "extra") {
    return "#7c3aed";
  }
  return "#5b6b7d";
}

export function RunTopologyPage() {
  const { runId = "" } = useParams();
  const [time, setTime] = useState(0);
  const [selectedNodeName, setSelectedNodeName] = useState<string | null>(null);
  const runState = useAsyncData(() => apiClient.getRun(runId), [runId]);
  const topologyState = useAsyncData(() => apiClient.getTopology(runId, time), [runId, time]);
  const experimentId = runState.data?.experiment_id;

  const summary = useMemo(() => {
    const nodes = topologyState.data?.nodes ?? [];
    const satellites = nodes.filter(node => node.node_type === "sat").length;
    const groundStations = nodes.filter(node => node.node_type === "gs").length;
    const extras = nodes.filter(node => node.node_type === "extra").length;
    const links = topologyState.data?.links.length ?? 0;
    return { satellites, groundStations, extras, links };
  }, [topologyState.data]);

  const nodePositions = useMemo(() => projectNodes(topologyState.data?.nodes ?? []), [topologyState.data]);
  const selectedNode = useMemo(
    () => (topologyState.data?.nodes ?? []).find(node => node.name === selectedNodeName) ?? null,
    [selectedNodeName, topologyState.data]
  );

  return (
    <section className="page-stack">
      <PageHeader
        tone="topology"
        breadcrumbs={[
          { label: "Experiments", to: appRoutes.experiments() },
          experimentId
            ? { label: experimentId, to: appRoutes.experimentDetailPath(experimentId) }
            : { label: "Experiment" },
          { label: runId, to: appRoutes.runDetailPath(runId) },
          { label: "Topology" }
        ]}
        title="Topology"
        actions={
          <label className="time-control">
            <span>Time</span>
            <input
              type="number"
              min={0}
              value={time}
              onChange={event => setTime(Number(event.target.value) || 0)}
            />
          </label>
        }
      />

      {topologyState.loading ? <LoadingBlock /> : null}
      {runState.loading ? <LoadingBlock /> : null}
      {topologyState.error ? <ErrorPanel message={topologyState.error.message} /> : null}
      {runState.error ? <ErrorPanel message={runState.error.message} /> : null}

      {topologyState.data ? (
        <>
          <section className="metric-grid">
            <div className="metric-card">
              <p className="metric-label">Nodes</p>
              <p className="metric-value">{topologyState.data.nodes.length}</p>
            </div>
            <div className="metric-card">
              <p className="metric-label">Satellites</p>
              <p className="metric-value">{summary.satellites}</p>
            </div>
            <div className="metric-card">
              <p className="metric-label">Ground stations</p>
              <p className="metric-value">{summary.groundStations}</p>
            </div>
            <div className="metric-card">
              <p className="metric-label">Extra nodes</p>
              <p className="metric-value">{summary.extras}</p>
            </div>
            <div className="metric-card">
              <p className="metric-label">Links</p>
              <p className="metric-value">{summary.links}</p>
            </div>
          </section>

          {topologyState.data.nodes.length ? (
            <div className="topology-workbench">
              <section className="topology-canvas-panel">
                <div className="topology-legend">
                  <span><i className="legend-dot legend-sat" /> Sat</span>
                  <span><i className="legend-dot legend-gs" /> GS</span>
                  <span><i className="legend-dot legend-extra" /> Extra</span>
                </div>
                <svg viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`} className="topology-canvas" role="img">
                  {topologyState.data.links.map(link => {
                    const source = nodePositions.get(link.source);
                    const target = nodePositions.get(link.target);
                    if (!source || !target) {
                      return null;
                    }
                    return (
                      <line
                        key={`${link.source}-${link.target}`}
                        x1={source.x}
                        y1={source.y}
                        x2={target.x}
                        y2={target.y}
                        className={`topology-link topology-link-${link.link_type}`}
                      />
                    );
                  })}
                  {topologyState.data.nodes.map(node => {
                    const projected = nodePositions.get(node.name);
                    if (!projected) {
                      return null;
                    }
                    const active = selectedNodeName === node.name;
                    return (
                      <g
                        key={node.name}
                        className={active ? "topology-node topology-node-active" : "topology-node"}
                        onClick={() => setSelectedNodeName(node.name)}
                      >
                        <circle
                          cx={projected.x}
                          cy={projected.y}
                          r={node.node_type === "sat" ? 7 : 10}
                          fill={nodeColor(node.node_type)}
                        />
                        <text x={projected.x + 10} y={projected.y - 10}>
                          {node.name}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              </section>

              <aside className="inspector-panel">
                <h3>Node detail</h3>
                {selectedNode ? (
                  <dl className="detail-grid">
                    <div>
                      <dt>Name</dt>
                      <dd>{selectedNode.name}</dd>
                    </div>
                    <div>
                      <dt>Type</dt>
                      <dd>{selectedNode.node_type}</dd>
                    </div>
                    <div>
                      <dt>Neighbors</dt>
                      <dd>{selectedNode.neighbors.join(", ") || "-"}</dd>
                    </div>
                    <div>
                      <dt>Ground stations</dt>
                      <dd>{selectedNode.ground_stations.join(", ") || "-"}</dd>
                    </div>
                    <div>
                      <dt>IPv4</dt>
                      <dd>{selectedNode.ipv4 ?? "-"}</dd>
                    </div>
                    <div>
                      <dt>IPv6</dt>
                      <dd>{selectedNode.ipv6 ?? "-"}</dd>
                    </div>
                    <div>
                      <dt>Position</dt>
                      <dd>{selectedNode.position?.map(item => item.toFixed(2)).join(", ") ?? "-"}</dd>
                    </div>
                  </dl>
                ) : (
                  <p className="page-description">Select a node in the graph to inspect its current state.</p>
                )}
              </aside>

              <section className="data-section topology-links-table">
                <div className="section-title-row">
                  <div>
                    <p className="eyebrow">Links</p>
                    <h3>Link inventory</h3>
                  </div>
                </div>
                <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th>Target</th>
                      <th>Type</th>
                      <th>IPv4 pair</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topologyState.data.links.map(link => (
                      <tr key={`${link.source}-${link.target}`}>
                        <td>{link.source}</td>
                        <td>{link.target}</td>
                        <td>{link.link_type}</td>
                        <td>{`${link.source_ipv4 ?? "-"} <-> ${link.target_ipv4 ?? "-"}`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
              </section>
            </div>
          ) : (
            <EmptyState
              title="No topology data"
              body="The run exists, but the runtime has not exposed any nodes for the selected time."
            />
          )}
        </>
      ) : null}
    </section>
  );
}
