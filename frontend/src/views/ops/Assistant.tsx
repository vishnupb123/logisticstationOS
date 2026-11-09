import { ChatBox } from "../../components/ChatPanel";
import { Card } from "../../components/Card";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { LlmStatusBadge } from "../../components/LlmStatusBadge";
import { PageHeader } from "../../components/PageHeader";

export function Assistant() {
  return (
    <div>
      <PageHeader
        eyebrow="AI"
        title="Station Assistant"
        badges={
          <>
            <DataSourceBadge kind="simulated" />
            <LlmStatusBadge />
          </>
        }
      >
        Ask about the live station or tell it what to do. Questions are answered from live state (numbers are computed,
        never generated). Requests go to the specialist agents — e.g. “fix stow WIP” — or straight to the simulated
        station, and every reply says what actually happened. Messages are understood by a deterministic parser first;
        the local LLM only helps classify phrasing it doesn't recognise.
      </PageHeader>
      <div className="grid-2">
        <Card title="Conversation">
          <ChatBox height={480} autoFocus />
        </Card>
        <Card title="What it can do">
          <ul className="cc-how" style={{ listStyle: "disc" }}>
            <li><strong>Status & metrics</strong> — “status”, “DEA”, “OTD”, “how is stow WIP?”, “scan compliance”</li>
            <li><strong>Risks</strong> — “what's at risk?” (from all five agents)</li>
            <li><strong>Lookups</strong> — “where is R-012?”, “late drivers”, “late trucks”, “labor”, “high value”</li>
            <li><strong>Goals for the agents</strong> — “fix stow WIP”, “protect DEA”, “protect OTD”</li>
            <li><strong>Outbound & DSP</strong> — “prioritise R-012”, “sideline R-020”, “move R-031 to the next wave”, “notify late drivers”, “standby for R-045”, “remind drivers to swipe”</li>
            <li><strong>Labor</strong> — “VET 3 stowers”, “move 1 problem solve to stow”, “open spare line”, “extend pick start 15”</li>
            <li><strong>Packages</strong> — “start in-station scrub”</li>
            <li><strong>What-if (nothing applied)</strong> — “what if we VET 4 stowers?”</li>
            <li><strong>Drills</strong> — “simulate a jam on line 2 for 20 min”, “inject traffic incident south”, “simulate a surge of 500”</li>
            <li><strong>Session</strong> — “pause”, “resume”, “speed 10”, “copilot mode”, “approve all”</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
