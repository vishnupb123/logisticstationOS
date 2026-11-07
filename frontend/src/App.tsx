import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AiInvestigationDetail } from "./views/AiInvestigationDetail";
import { AiInvestigations } from "./views/AiInvestigations";
import { DecisionDetail } from "./views/DecisionDetail";
import { DecisionHistory } from "./views/DecisionHistory";
import { DigitalTwinRunner } from "./views/DigitalTwinRunner";
import { InductSortation } from "./views/InductSortation";
import { LiveOperations } from "./views/LiveOperations";
import { RlComparison } from "./views/RlComparison";
import { StationOverview } from "./views/StationOverview";
import { StowJackpot } from "./views/StowJackpot";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<StationOverview />} />
        <Route path="/live" element={<LiveOperations />} />
        <Route path="/induct" element={<InductSortation />} />
        <Route path="/stow" element={<StowJackpot />} />
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
