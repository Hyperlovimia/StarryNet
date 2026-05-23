import { FormEvent, useMemo, useState } from "react";

import { ErrorPanel } from "../components/ErrorPanel";
import { apiClient } from "../lib/api/client";
import type { CoreEventType, EventPayload, EventRecord } from "../lib/models";

const NODE_NAME_PATTERN = /^(SH\d+O\d+S\d+|GS\d+)$/;

const EVENT_OPTIONS: Array<{ value: CoreEventType; label: string }> = [
  { value: "ping", label: "Ping" },
  { value: "iperf", label: "Iperf" },
  { value: "damage", label: "Damage" },
  { value: "recovery", label: "Recovery" },
  { value: "check_routing_table", label: "Routing table check" },
  { value: "check_utility", label: "Utility check" },
  { value: "static_route", label: "Static route" }
];

type EventFormState = {
  event_id?: string;
  time: string;
  event_type: CoreEventType;
  node: string;
  src: string;
  dst: string;
  next_hop: string;
  damaging_ratio: string;
  extra_args: string;
  src_args: string;
  dst_args: string;
};

const emptyForm: EventFormState = {
  time: "0",
  event_type: "ping",
  node: "",
  src: "",
  dst: "",
  next_hop: "",
  damaging_ratio: "0.1",
  extra_args: "",
  src_args: "",
  dst_args: ""
};

function eventTypeOf(event: EventRecord): string {
  return event.event_type ?? event.type ?? "event";
}

function splitArgs(value: string): string[] {
  return value
    .split(/[,\s]+/)
    .map(item => item.trim())
    .filter(Boolean);
}

function stringifyArgs(value: unknown): string {
  return Array.isArray(value) ? value.filter(item => typeof item === "string").join(" ") : "";
}

function readStringParam(params: Record<string, unknown>, key: string): string {
  const value = params[key];
  return typeof value === "string" ? value : "";
}

function eventLabel(eventType: string): string {
  return EVENT_OPTIONS.find(option => option.value === eventType)?.label ?? eventType;
}

function isCoreEventType(eventType: string): eventType is CoreEventType {
  return EVENT_OPTIONS.some(option => option.value === eventType);
}

function summarizeParams(event: EventRecord): string {
  const params = event.params;
  switch (eventTypeOf(event)) {
    case "check_utility":
    case "recovery":
      return "No parameters";
    case "check_routing_table":
      return `node=${readStringParam(params, "node")}`;
    case "damage":
      return `ratio=${String(params.damaging_ratio ?? "")}`;
    case "static_route":
      return `src=${readStringParam(params, "src")}, dst=${readStringParam(params, "dst")}, next_hop=${readStringParam(params, "next_hop")}`;
    case "ping":
      return `src=${readStringParam(params, "src")}, dst=${readStringParam(params, "dst")}`;
    case "iperf":
      return `src=${readStringParam(params, "src")}, dst=${readStringParam(params, "dst")}`;
    default:
      return JSON.stringify(params);
  }
}

function formFromEvent(event: EventRecord): EventFormState {
  const eventType = eventTypeOf(event);
  return {
    event_id: event.event_id,
    time: String(event.time),
    event_type: isCoreEventType(eventType) ? eventType : "ping",
    node: readStringParam(event.params, "node"),
    src: readStringParam(event.params, "src"),
    dst: readStringParam(event.params, "dst"),
    next_hop: readStringParam(event.params, "next_hop"),
    damaging_ratio: String(event.params.damaging_ratio ?? "0.1"),
    extra_args: stringifyArgs(event.params.extra_args),
    src_args: stringifyArgs(event.params.src_args),
    dst_args: stringifyArgs(event.params.dst_args)
  };
}

function validateNode(value: string, label: string): string | null {
  if (!value.trim()) {
    return `${label} is required.`;
  }
  if (!NODE_NAME_PATTERN.test(value.trim())) {
    return `${label} must look like SH1O1S1 or GS0.`;
  }
  return null;
}

function buildEventPayload(form: EventFormState, duration: number): EventPayload {
  const time = Number(form.time);
  if (!Number.isInteger(time) || time < 0 || time > duration) {
    throw new Error(`Time must be an integer from 0 to ${duration}.`);
  }

  const params: Record<string, unknown> = {};
  const requireNode = (value: string, label: string) => {
    const error = validateNode(value, label);
    if (error) {
      throw new Error(error);
    }
    return value.trim();
  };

  if (form.event_type === "check_routing_table") {
    params.node = requireNode(form.node, "Node");
  } else if (form.event_type === "damage") {
    const ratio = Number(form.damaging_ratio);
    if (!Number.isFinite(ratio) || ratio < 0 || ratio > 1) {
      throw new Error("Damage ratio must be between 0 and 1.");
    }
    params.damaging_ratio = ratio;
  } else if (form.event_type === "static_route") {
    params.src = requireNode(form.src, "Source");
    params.dst = requireNode(form.dst, "Destination");
    params.next_hop = requireNode(form.next_hop, "Next hop");
  } else if (form.event_type === "ping") {
    params.src = requireNode(form.src, "Source");
    params.dst = requireNode(form.dst, "Destination");
    params.extra_args = splitArgs(form.extra_args);
  } else if (form.event_type === "iperf") {
    params.src = requireNode(form.src, "Source");
    params.dst = requireNode(form.dst, "Destination");
    params.src_args = splitArgs(form.src_args);
    params.dst_args = splitArgs(form.dst_args);
  }

  return {
    time,
    event_type: form.event_type,
    params
  };
}

type Props = {
  runId: string;
  events: EventRecord[];
  duration: number;
  onChanged: () => Promise<unknown>;
};

export function RunEventsEditor({ runId, events, duration, onChanged }: Props) {
  const [form, setForm] = useState<EventFormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const sortedEvents = useMemo(
    () => [...events].sort((left, right) => left.time - right.time || eventTypeOf(left).localeCompare(eventTypeOf(right))),
    [events]
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setSaveError(null);
    setSaving(true);
    try {
      const payload = buildEventPayload(form, duration);
      if (form.event_id) {
        await apiClient.updateEvent(runId, form.event_id, payload);
      } else {
        await apiClient.createEvent(runId, payload);
      }
      await onChanged();
      setForm(emptyForm);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to save event");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(eventId: string | undefined) {
    if (!eventId) {
      return;
    }
    setSaveError(null);
    setDeletingId(eventId);
    try {
      await apiClient.deleteEvent(runId, eventId);
      await onChanged();
      if (form.event_id === eventId) {
        setForm(emptyForm);
      }
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to delete event");
    } finally {
      setDeletingId(null);
    }
  }

  const showNode = form.event_type === "check_routing_table";
  const showDamage = form.event_type === "damage";
  const showRoute = form.event_type === "static_route";
  const showEndpoints = form.event_type === "ping" || form.event_type === "iperf" || showRoute;
  const showPingArgs = form.event_type === "ping";
  const showIperfArgs = form.event_type === "iperf";

  return (
    <section className="data-section event-editor-section">
      <div className="section-title-row">
        <div>
          <h3>Event list</h3>
        </div>
      </div>

      {saveError ? <ErrorPanel message={saveError} /> : null}

      {sortedEvents.length ? (
        <div className="table-wrap event-template-table">
          <table className="data-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Type</th>
                <th>Status</th>
                <th>Parameters</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sortedEvents.map((event, index) => {
                const eventType = eventTypeOf(event);
                const eventId = event.event_id;
                const canEdit = isCoreEventType(eventType) && (event.status === undefined || event.status === "queuing");
                return (
                  <tr key={eventId ?? `${eventType}-${event.time}-${index}`}>
                    <td>{event.time}s</td>
                    <td>{eventLabel(eventType)}</td>
                    <td>{event.status ?? "queued"}</td>
                    <td><code>{summarizeParams(event)}</code></td>
                    <td>
                      <div className="table-actions">
                        <button
                          type="button"
                          className="inline-button"
                          onClick={() => setForm(formFromEvent(event))}
                          disabled={!canEdit}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="danger-inline-button"
                          onClick={() => handleDelete(eventId)}
                          disabled={!canEdit || deletingId === eventId}
                        >
                          {deletingId === eventId ? "Deleting..." : "Delete"}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="empty-inline">No event settings saved for this run.</p>
      )}

      <form className="event-template-form" onSubmit={handleSubmit}>
        <div className="form-grid">
          <label>
            <span>Event type</span>
            <select
              value={form.event_type}
              onChange={event => setForm(current => ({ ...emptyForm, event_id: current.event_id, time: current.time, event_type: event.target.value as CoreEventType }))}
            >
              {EVENT_OPTIONS.map(option => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Time (s)</span>
            <input
              type="number"
              min={0}
              max={duration}
              value={form.time}
              onChange={event => setForm(current => ({ ...current, time: event.target.value }))}
            />
          </label>
          {showNode ? (
            <label>
              <span>Node</span>
              <input value={form.node} onChange={event => setForm(current => ({ ...current, node: event.target.value }))} />
            </label>
          ) : null}
          {showDamage ? (
            <label>
              <span>Damage ratio</span>
              <input
                type="number"
                min={0}
                max={1}
                step="0.01"
                value={form.damaging_ratio}
                onChange={event => setForm(current => ({ ...current, damaging_ratio: event.target.value }))}
              />
            </label>
          ) : null}
          {showEndpoints ? (
            <>
              <label>
                <span>Source</span>
                <input value={form.src} onChange={event => setForm(current => ({ ...current, src: event.target.value }))} />
              </label>
              <label>
                <span>Destination</span>
                <input value={form.dst} onChange={event => setForm(current => ({ ...current, dst: event.target.value }))} />
              </label>
            </>
          ) : null}
          {showRoute ? (
            <label>
              <span>Next hop</span>
              <input value={form.next_hop} onChange={event => setForm(current => ({ ...current, next_hop: event.target.value }))} />
            </label>
          ) : null}
          {showPingArgs ? (
            <label>
              <span>Ping args</span>
              <input value={form.extra_args} onChange={event => setForm(current => ({ ...current, extra_args: event.target.value }))} />
            </label>
          ) : null}
          {showIperfArgs ? (
            <>
              <label>
                <span>Source args</span>
                <input value={form.src_args} onChange={event => setForm(current => ({ ...current, src_args: event.target.value }))} />
              </label>
              <label>
                <span>Destination args</span>
                <input value={form.dst_args} onChange={event => setForm(current => ({ ...current, dst_args: event.target.value }))} />
              </label>
            </>
          ) : null}
        </div>

        {formError ? <p className="inline-validation">{formError}</p> : null}

        <div className="button-row">
          <button type="submit" className="primary-button" disabled={saving}>
            {saving ? "Saving..." : form.event_id ? "Save changes" : "Add event"}
          </button>
          {form.event_id ? (
            <button type="button" className="ghost-button" onClick={() => setForm(emptyForm)} disabled={saving}>
              Cancel edit
            </button>
          ) : null}
        </div>
      </form>
    </section>
  );
}
