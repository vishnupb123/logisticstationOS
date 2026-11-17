// Settings (HANDOFF_V2 E1/E2): the metric engine's editable thresholds, each
// with its provenance, plus the read-only site profile and break schedule.
// Changes apply to the current simulated session only.
import { useState } from "react";
import { ApiError } from "../../api/client";
import { type SettingsView, useUpdateSettings } from "../../api/runtimeV2";
import { Card } from "../../components/Card";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { DataTable } from "../../components/DataTable";
import { DataUpdated, ProvenanceBadge } from "../../components/MetricDrawer";
import { PageHeader } from "../../components/PageHeader";
import { LiveGate } from "../../components/live";
import { clockOf } from "../../api/stationOps";

type EditableKey = "stow_wip_lower_min" | "stow_wip_upper_min" | "stow_wip_compliance_target" | "induct_dwell_minutes";

const FIELD: Record<string, { label: string; unit: string; step: number; help: string }> = {
  stow_wip_lower_min: { label: "Stow WIP lower threshold", unit: "min", step: 1, help: "Below this, stowers are starved." },
  stow_wip_upper_min: { label: "Stow WIP upper threshold", unit: "min", step: 1, help: "Above this, induct is outrunning stow." },
  stow_wip_compliance_target: { label: "Stow WIP compliance target", unit: "ratio (0–1)", step: 0.01, help: "Share of 15-min intervals inside the band." },
  induct_dwell_minutes: { label: "Induct dwell threshold", unit: "min", step: 5, help: "Inducted but not stowed for longer than this." },
};

const label = (k: string) => k.replace(/_/g, " ");

function provKind(text: string | undefined): string {
  if (!text) return "proposed";
  if (text.startsWith("documented")) return "documented";
  if (text.startsWith("observed")) return "observed";
  return "proposed";
}

function errText(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as unknown;
    if (typeof d === "string") return `${e.status}: ${d}`;
    if (Array.isArray(d)) {
      return `${e.status}: ${d.map((x: { loc?: unknown[]; msg?: string }) => `${String(x.loc?.[x.loc.length - 1] ?? "")} — ${x.msg ?? ""}`).join("; ")}`;
    }
    return `${e.status}: ${JSON.stringify(d)}`;
  }
  return e instanceof Error ? e.message : String(e);
}

function fmtVal(v: unknown): string {
  if (Array.isArray(v)) return v.map(fmtVal).join(" – ");
  if (typeof v === "number") return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (v && typeof v === "object") return JSON.stringify(v);
  return v === null || v === undefined ? "—" : String(v);
}

function Editor({ st }: { st: SettingsView }) {
  const update = useUpdateSettings();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<string | null>(null);
  const dirty = Object.keys(draft).length > 0;
  const save = () => {
    const body: Partial<Record<EditableKey, number>> = {};
    for (const [k, v] of Object.entries(draft)) body[k as EditableKey] = Number(v);
    setSaved(null);
    update.mutate(body, {
      onSuccess: () => {
        setDraft({});
        setSaved("Saved — applies to the current simulated session.");
      },
    });
  };
  return (
    <form
      className="settings-form"
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
    >
      <div className="settings-grid">
        {st.editable.map((k) => {
          const f = FIELD[k] ?? { label: label(k), unit: "", step: 1, help: "" };
          const current = st.values[k];
          return (
            <div key={k} className="settings-field">
              <label htmlFor={`set-${k}`}>{f.label}</label>
              <div className="settings-field__row">
                <input
                  id={`set-${k}`}
                  type="number"
                  step={f.step}
                  value={draft[k] ?? String(current ?? "")}
                  onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))}
                  data-testid={`setting-${k}`}
                />
                <span className="muted">{f.unit}</span>
              </div>
              <div className="settings-field__meta">
                <ProvenanceBadge status={provKind(st.provenance[k])} />
                <span className="muted">{st.provenance[k]}</span>
              </div>
              {f.help && <div className="muted settings-field__help">{f.help}</div>}
            </div>
          );
        })}
      </div>
      <div className="settings-actions">
        <button type="submit" className="button button--primary button--sm" disabled={!dirty || update.isPending} data-testid="settings-save">
          {update.isPending ? "Saving…" : "Save"}
        </button>
        <button type="button" className="button button--sm" disabled={!dirty} onClick={() => setDraft({})}>
          Reset
        </button>
        {update.error && (
          <span className="settings-error" role="alert" data-testid="settings-error">
            ✕ {errText(update.error)}
          </span>
        )}
        {saved && !update.error && (
          <span className="settings-saved" role="status" data-testid="settings-saved">
            ✓ {saved}
          </span>
        )}
      </div>
    </form>
  );
}

export function Settings() {
  return (
    <div>
      <PageHeader eyebrow="Analyze & govern" title="Settings" badges={<DataSourceBadge kind="simulated" />}>
        Thresholds the metric engine uses, with where each default comes from. Edits apply to the current simulated
        session; documented defaults are the station owner's, proposed ones are StationOS assumptions.
      </PageHeader>
      <style>{SETTINGS_CSS}</style>
      <LiveGate>
        {(s) => {
          const st = s.views.settings;
          const readOnly = Object.entries(st.values).filter(([k]) => !st.editable.includes(k) && k !== "breaks");
          return (
            <div className="stack">
              <Card title="Editable thresholds">
                <Editor st={st} />
              </Card>
              <div className="grid-2">
                <Card title="Other metric settings (read-only)">
                  <DataTable
                    columns={[
                      { key: "k", label: "Setting", value: (r) => label(r[0]) },
                      { key: "v", label: "Value", num: true, value: (r) => fmtVal(r[1]) },
                      { key: "p", label: "Provenance", render: (r) => <ProvenanceBadge status={provKind(st.provenance[r[0]])} /> },
                    ]}
                    rows={readOnly}
                    rowKey={(r) => r[0]}
                    maxHeight={360}
                  />
                </Card>
                <Card title="Site profile (read-only)">
                  <dl className="settings-kv" data-testid="site-profile">
                    {Object.entries(st.site_profile).map(([k, v]) => (
                      <div key={k}>
                        <dt>{label(k)}</dt>
                        <dd className="tabular">{fmtVal(v)}</dd>
                      </div>
                    ))}
                  </dl>
                </Card>
              </div>
              <Card title="Break schedule (read-only)">
                <DataTable
                  columns={[
                    { key: "label", label: "Break", value: (b) => b.label },
                    { key: "start", label: "Starts", value: (b) => clockOf(b.start_minute) },
                    { key: "minutes", label: "Minutes", num: true, value: (b) => b.minutes },
                    { key: "prov", label: "Provenance", render: () => <ProvenanceBadge status={provKind(st.provenance.breaks)} /> },
                  ]}
                  rows={st.values.breaks ?? []}
                  rowKey={(b) => `${b.label}-${b.start_minute}`}
                  maxHeight={240}
                />
                <DataUpdated />
              </Card>
            </div>
          );
        }}
      </LiveGate>
    </div>
  );
}

const SETTINGS_CSS = `
.settings-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }
.settings-field { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.settings-field label { font-weight: 600; font-size: 13px; }
.settings-field__row { display: flex; gap: 6px; align-items: center; }
.settings-field__row input { font: inherit; width: 110px; padding: 4px 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-1); color: var(--text-primary); }
.settings-field__meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 12px; }
.settings-field__help { font-size: 12px; }
.settings-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 16px; }
.settings-error { color: var(--status-critical); font-size: 13px; overflow-wrap: anywhere; }
.settings-saved { color: var(--text-secondary); font-size: 13px; }
.settings-kv { display: grid; grid-template-columns: 1fr; gap: 4px; margin: 0; }
.settings-kv > div { display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--gridline); padding: 4px 0; }
.settings-kv dt { color: var(--text-secondary); text-transform: capitalize; }
.settings-kv dd { margin: 0; text-align: right; overflow-wrap: anywhere; }
`;
