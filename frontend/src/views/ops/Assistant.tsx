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
        Ask anything about the shift, or tell it what to do. Each answer combines a computed analysis of the live station
        (root causes, the decisions taken and their simulated impact), retrieval over the shift record (truckfile, GTDRs,
        VET/VTO offers, agent decisions, notifications, events — cited as sources), and an optional local-LLM summary
        whose numbers are checked against the facts. Requests go to the specialist agents or straight to the simulated
        station.
      </PageHeader>
      <div className="assistant-grid">
        <Card title="Conversation">
          <ChatBox height={620} autoFocus />
        </Card>
        <Card title="What it can do">
          <ul className="cc-how" style={{ listStyle: "disc" }}>
            <li><strong>Explain the shift</strong> — “how did the shift go?”, “why did DEA drop?”, “what caused the late departures?”, “what did the agents do?”, then follow up with “why?” or “what did you do about it?”</li>
            <li><strong>Trucks & ferries</strong> — “status of the trucks and ferries”, “any truckfile changes after the final?”, “GTDRs today?”</li>
            <li><strong>People</strong> — “how many VETs were accepted for tomorrow?”, “who called out?”, “VTO offers?”, “labor today”</li>
            <li><strong>Tomorrow</strong> — “volume for tomorrow”, “is tomorrow's plan on the latest truckfile?”</li>
            <li><strong>Anything else</strong> — free questions are answered from the shift record with sources, e.g. “what happened with R-042?”, “any grounded vans?”</li>
            <li><strong>Goals for the agents</strong> — “fix stow WIP”, “protect DEA”, “protect OTD”</li>
            <li><strong>Floor & dispatch</strong> — “restage R-012”, “sweep aisle A05”, “replacement van for R-031”, “move R-031 to the next wave”, “notify late drivers”</li>
            <li><strong>Close-out</strong> — “check ferry”, “re-plan tomorrow”, “offer VET to 3”, “offer VTO to 2”, “draft GTDRs”</li>
            <li><strong>What-if (nothing applied)</strong> — “what if we VET 4 stowers?”</li>
            <li><strong>Session</strong> — “pause”, “speed 10”, “copilot mode”, “approve all”</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
