import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { CommandCenter } from "./views/CommandCenter";
import { AiInvestigationDetail } from "./views/AiInvestigationDetail";
import { AiInvestigations } from "./views/AiInvestigations";
import { DecisionDetail } from "./views/DecisionDetail";
import { DecisionHistory } from "./views/DecisionHistory";
import { DigitalTwinRunner } from "./views/DigitalTwinRunner";
import { LiveOperations } from "./views/LiveOperations";
import { RlComparison } from "./views/RlComparison";
import { StationOverview } from "./views/StationOverview";
import { StationAgent } from "./views/StationAgent";
import { AgentConsole } from "./views/ops/AgentConsole";
import { Assistant } from "./views/ops/Assistant";
import { Dispatch } from "./views/ops/Dispatch";
import { HighValue } from "./views/ops/HighValue";
import { Inbound } from "./views/ops/Inbound";
import { OutboundOverview, Pick, Stage } from "./views/ops/Outbound";
import { Packages } from "./views/ops/Packages";
import { Associates, Labor } from "./views/ops/People";
import { SortOverview } from "./views/ops/Sort";
import { StationResources, WorkItems } from "./views/ops/Station";
import { ProblemSolve, StowBuffers } from "./views/ops/Stow";
import { StationAgentExecution } from "./views/StationAgentExecution";
import { Truckfile } from "./views/Truckfile";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<StationOverview />} />
        <Route path="/command" element={<CommandCenter />} />
        <Route path="/truckfile" element={<Truckfile />} />
        <Route path="/agent" element={<AgentConsole />} />
        <Route path="/agent/investigations" element={<StationAgent />} />
        <Route path="/agent/executions/:id" element={<StationAgentExecution />} />
        <Route path="/live" element={<LiveOperations />} />
        <Route path="/induct" element={<SortOverview />} />
        <Route path="/stow" element={<StowBuffers />} />
        <Route path="/problem-solve" element={<ProblemSolve />} />
        <Route path="/inbound" element={<Inbound />} />
        <Route path="/packages" element={<Packages />} />
        <Route path="/outbound" element={<OutboundOverview />} />
        <Route path="/pick" element={<Pick />} />
        <Route path="/stage" element={<Stage />} />
        <Route path="/dispatch" element={<Dispatch />} />
        <Route path="/high-value" element={<HighValue />} />
        <Route path="/associates" element={<Associates />} />
        <Route path="/labor" element={<Labor />} />
        <Route path="/station" element={<StationResources />} />
        <Route path="/work-items" element={<WorkItems />} />
        <Route path="/assistant" element={<Assistant />} />
        <Route path="/investigations" element={<AiInvestigations />} />
        <Route path="/investigations/:id" element={<AiInvestigationDetail />} />
        <Route path="/simulation" element={<DigitalTwinRunner />} />
        <Route path="/rl" element={<RlComparison />} />
        <Route path="/decisions" element={<DecisionHistory />} />
        <Route path="/decisions/:id" element={<DecisionDetail />} />
      </Routes>
    </Layout>
  );
}
