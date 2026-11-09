// Station Overview's live sections: today's simulated day end to end (the
// shared runtime session), and the Cycle-1 hamper-level twin running
// continuously beside it — the detailed sortation physics (per-aisle hamper
// fill, jackpot divert/clear) that the full-day twin abstracts.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useLiveTwin } from "../../api/live";
import { pctv, useStation } from "../../api/runtime";
import { Card } from "../../components/Card";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { Funnel } from "../../components/Funnel";
import { HamperGrid } from "../../components/HamperGrid";
import { Kpi, KpiGrid } from "../../components/Kpi";
import { formatDuration } from "../../lib/format";

export function LiveDayPanel() {
  const q = useStation();
  const s = q.data;
  if (!s) return null;
  const snap = s.snapshot;
  const m = snap.metrics;
  const ps = snap.package_status;
  return (
    <Card
      title={
        <>
          Today, live — {snap.clock} · {snap.scenario.replace(/_/g, " ")} <DataSourceBadge kind="simulated" />
        </>
      }
      actions={<Link className="button button--sm" to="/command">Command Center →</Link>}
    >
      <KpiGrid>
        <Kpi testId="live-dea" label="DEA" value={snap.done ? pctv(m.dea.value, 2) : pctv(m.dea_ceiling.value, 2)} caption={snap.done ? "final" : "best case so far"} />
        <Kpi label="OTD" value={pctv(m.otd.value)} caption={`${snap.outbound.departed}/${snap.outbound.routes_total} departed`} />
        <Kpi label="Stow WIP" value={`${snap.stow.wip_minutes.toFixed(1)}m`} caption={`band ${snap.stow.wip_target_min}–${snap.stow.wip_target_max}`} />
        <Kpi label="Rolled over" value={ps.rolled_over.toLocaleString()} status={ps.rolled_over ? "critical" : "good"} />
        <Kpi label="Open risks" value={s.agents.risks.length} caption={`${s.agents.actions.filter((a) => a.applied).length} agent actions applied`} />
        <Kpi label="Associates" value={snap.labor.present} caption={`${snap.labor.absent} absent · flex ${snap.labor.flex_remaining}`} />
      </KpiGrid>
      <Funnel
        stages={[
          { key: "live-planned", label: "Planned", value: snap.delivery.promised },
          { key: "live-arrived", label: "Arrived", value: snap.inbound.arrived_volume },
          { key: "live-inducted", label: "Inducted", value: snap.induct.inducted },
          { key: "live-stowed", label: "Stowed / caged", value: snap.stow.stowed },
          { key: "live-dispatched", label: "Dispatched", value: snap.delivery.dispatched },
          { key: "live-delivered", label: "Delivered so far", value: snap.delivery.delivered_so_far },
        ]}
      />
    </Card>
  );
}

const SCENARIO = "normal_operations.yaml";

export function Cycle1Panel() {
  const live = useLiveTwin();
  const [seed, setSeed] = useState(1);
  const { start, status } = live;
  useEffect(() => {
    start({ scenario: SCENARIO, seed, stepSeconds: 30, frameIntervalMs: 250 });
  }, [start, seed]);
  useEffect(() => {
    if (status !== "complete") return;
    const id = setTimeout(() => setSeed((x) => x + 1), 4000);
    return () => clearTimeout(id);
  }, [status]);
  const s = live.latest;
  return (
    <Card
      title={
        <>
          Cycle-1 sortation detail — hamper-level twin <DataSourceBadge kind="simulated" />
        </>
      }
      actions={<Link className="button button--sm" to="/live">Open Cycle-1 twin →</Link>}
    >
      {!s ? (
        <p className="muted">Starting the Cycle-1 twin…</p>
      ) : (
        <div data-testid="cycle1-panel">
          <p className="muted" style={{ marginTop: 0, fontSize: 12 }}>
            Continuous replay (seed {seed}, {status}) of the Cycle-1 model: truck → induct → sort → hamper / jackpot → stow, with
            finite hamper capacity per aisle. Sim T+{Math.floor(s.sim_time_seconds / 60)}m · {s.funnel.parcels_stowed}/{s.planned_parcels} stowed.
          </p>
          <div className="grid-2">
            <div>
              <KpiGrid>
                <Kpi label="In jackpot" value={s.wip.in_jackpot} status={s.wip.in_jackpot ? "warning" : "good"} caption={`${s.funnel.jackpot_diverts} diverts`} />
                <Kpi label="Stowers busy" value={`${s.utilization.stowers_busy}/${s.utilization.stower_capacity}`} />
                <Kpi label="Dock→stow p50" value={formatDuration(s.cycle_times.dock_to_stow.p50_seconds)} />
              </KpiGrid>
            </div>
            <HamperGrid hampers={s.hampers} />
          </div>
        </div>
      )}
    </Card>
  );
}
