// Live session control strip shown on every page: sim clock, phase, scenario,
// play/pause, speed, agent mode, and "start a new day". Always badged as a
// simulated day — there is no live operational feed behind it.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { type Mode, runtimeApi, useControl, useStation } from "../api/runtime";
import { stationOpsApi } from "../api/stationOps";
import "./SessionBar.css";

const SPEEDS = [0.5, 1, 2, 5, 10, 30];
const PHASE: Record<string, string> = {
  pre_shift: "Pre-shift",
  inbound_induct_stow: "Inbound · induct · stow",
  pick_stage: "Pick & stage",
  depart: "Departures",
  on_road: "On road",
  complete: "Day complete",
};

export function SessionBar() {
  const q = useStation();
  const control = useControl();
  const qc = useQueryClient();
  const presets = useQuery({ queryKey: ["so-presets"], queryFn: stationOpsApi.presets });
  const [open, setOpen] = useState(false);
  const [preset, setPreset] = useState("normal_day");
  const [seed, setSeed] = useState("");
  const create = useMutation({
    mutationFn: () =>
      runtimeApi.create({
        preset,
        seed: seed.trim() ? Number(seed) : null,
        mode: q.data?.session.mode ?? "autopilot",
        speed: q.data?.session.speed ?? 2,
      }),
    onSuccess: () => {
      setOpen(false);
      qc.invalidateQueries();
    },
  });
  const s = q.data?.session;
  const snap = q.data?.snapshot;
  if (!s || !snap) {
    return (
      <div className="sbar sbar--loading" data-testid="session-bar">
        {q.error ? "Live station unavailable" : "Starting live station…"}
      </div>
    );
  }
  return (
    <div className="sbar" data-testid="session-bar">
      <span className={`sbar__dot${s.paused ? " sbar__dot--paused" : s.complete ? " sbar__dot--done" : ""}`} aria-hidden />
      <span className="sbar__clock tabular" data-testid="sim-clock-global">
        {snap.clock}
      </span>
      <span className="sbar__phase">{PHASE[snap.phase]}</span>
      <span className="sbar__scenario" title={s.description}>
        {s.preset.replace(/_/g, " ")} · seed {s.seed}
      </span>
      <span className="sbar__sim">SIMULATED</span>
      {q.data?.agents.busy && (
        <span className="sbar__thinking" title="The station waits (max 5 sim-min) while agents simulate plans">
          agents planning…
        </span>
      )}
      <div className="sbar__spacer" />
      <button
        className="button button--sm"
        onClick={() => control.mutate({ paused: !s.paused })}
        data-testid="session-pause"
        aria-label={s.paused ? "Resume" : "Pause"}
      >
        {s.paused ? "▶ Resume" : "❚❚ Pause"}
      </button>
      <select
        aria-label="Simulation speed"
        value={s.speed}
        onChange={(e) => control.mutate({ speed: Number(e.target.value) })}
      >
        {SPEEDS.map((v) => (
          <option key={v} value={v}>
            {v}× sim-min/s
          </option>
        ))}
        {!SPEEDS.includes(s.speed) && <option value={s.speed}>{s.speed}×</option>}
      </select>
      <select
        aria-label="Agent mode"
        value={s.mode}
        onChange={(e) => control.mutate({ mode: e.target.value as Mode })}
        title="Autopilot acts on the simulated station; Copilot queues recommendations for approval"
      >
        <option value="autopilot">Agents: autopilot</option>
        <option value="advise">Agents: copilot</option>
        <option value="observe">Agents: observe</option>
      </select>
      <button className="button button--sm" onClick={() => setOpen((o) => !o)} data-testid="new-day">
        New day
      </button>
      {open && (
        <div className="sbar__popover" role="dialog" aria-label="Start a new day">
          <label>
            Scenario
            <select value={preset} onChange={(e) => setPreset(e.target.value)} aria-label="New day scenario">
              {(presets.data ?? []).map((p) => (
                <option key={p.name} value={p.name} title={p.description}>
                  {p.name.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>
          <label>
            Seed
            <input
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              placeholder="random"
              aria-label="New day seed"
              style={{ width: 90 }}
            />
          </label>
          <p className="muted" style={{ fontSize: 12, margin: 0 }}>
            {presets.data?.find((p) => p.name === preset)?.description}
          </p>
          <button
            className="button button--primary button--sm"
            onClick={() => create.mutate()}
            disabled={create.isPending}
            data-testid="start-new-day"
          >
            {create.isPending ? "Starting…" : "Start day"}
          </button>
        </div>
      )}
    </div>
  );
}
