import React, { useMemo, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import {
  AlertTriangle,
  CheckCircle2,
  Crown,
  GitBranch,
  LineChart,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Trophy,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  LineChart as ReLineChart,
  Line,
  CartesianGrid,
  ReferenceLine,
} from "recharts";

const sampleStage = {
  stage: 1,
  type: "TTT",
  distance_km: 13.7,
  snapshot_time: "awaiting snapshot",
  budget: 50000000,
  status: "pre-snapshot scaffold",
};

const sampleChecks = [
  {
    label: "Snapshot schema valid",
    status: "pending",
    detail: "Waiting for shared/data/snapshots/stage_1_snapshot.json",
  },
  { label: "Exactly 8 riders", status: "pass", detail: "Candidate-team validator scaffolded" },
  { label: "Max 2 per real-world team", status: "pass", detail: "Constraint encoded in optimizer stub" },
  { label: "Budget ≤ 50,000,000 kr", status: "pass", detail: "Payoff/rules module loaded" },
  { label: "No DNS selected", status: "pending", detail: "Requires stage snapshot is_out field" },
  { label: "Captain uses E[max(ΔV, 0)]", status: "pass", detail: "Captain EV direction encoded" },
];

const sampleRiders = [
  {
    name: "Rider A",
    team: "UAE",
    price: 10500000,
    tier: "A",
    win: 18,
    podium: 42,
    top15: 79,
    role: "stage-win equity",
  },
  {
    name: "Rider B",
    team: "IGD",
    price: 8200000,
    tier: "A",
    win: 11,
    podium: 31,
    top15: 70,
    role: "podium/depth",
  },
  {
    name: "Rider C",
    team: "TVL",
    price: 7600000,
    tier: "B",
    win: 3,
    podium: 13,
    top15: 58,
    role: "team bonus / value",
  },
  {
    name: "Rider D",
    team: "SOQ",
    price: 6100000,
    tier: "B",
    win: 1,
    podium: 7,
    top15: 41,
    role: "budget structure",
  },
];

const sampleTeams = [
  {
    label: "Stage-win maximal",
    ev: 742000,
    p90: 1160000,
    p50: 690000,
    p10: 310000,
    pressure: "medium",
    captain: "Rider A",
  },
  {
    label: "Depth-bonus exploitation",
    ev: 703000,
    p90: 990000,
    p50: 720000,
    p10: 410000,
    pressure: "low",
    captain: "Rider B",
  },
  {
    label: "GC insurance",
    ev: 681000,
    p90: 910000,
    p50: 700000,
    p10: 455000,
    pressure: "low",
    captain: "Rider A",
  },
  {
    label: "Transfer preservation",
    ev: 646000,
    p90: 850000,
    p50: 665000,
    p10: 470000,
    pressure: "very low",
    captain: "Rider C",
  },
];

const sampleCdf = [
  { percentile: "p05", value: 220000 },
  { percentile: "p10", value: 310000 },
  { percentile: "p25", value: 510000 },
  { percentile: "p50", value: 690000 },
  { percentile: "p75", value: 880000 },
  { percentile: "p90", value: 1160000 },
  { percentile: "p95", value: 1420000 },
];

function StatusBadge({ status }) {
  const label = status === "pass" ? "Pass" : status === "fail" ? "Fail" : "Pending";
  const classes =
    status === "pass"
      ? "bg-emerald-100 text-emerald-800"
      : status === "fail"
        ? "bg-red-100 text-red-800"
        : "bg-amber-100 text-amber-800";
  return <span className={`rounded-full px-2 py-1 text-xs font-medium ${classes}`}>{label}</span>;
}

function SectionTitle({ icon: Icon, title, subtitle }) {
  return (
    <div className="mb-4 flex items-start gap-3">
      <div className="rounded-2xl bg-slate-100 p-2">
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
        <p className="text-sm text-slate-500">{subtitle}</p>
      </div>
    </div>
  );
}

export default function HoldetV3ExpertDashboard() {
  const [selectedTeam, setSelectedTeam] = useState(sampleTeams[0]);
  const auditScore = useMemo(() => {
    const pass = sampleChecks.filter((c) => c.status === "pass").length;
    return Math.round((pass / sampleChecks.length) * 100);
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 p-6 text-slate-950">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-col gap-4 rounded-3xl bg-white p-6 shadow-sm md:flex-row md:items-center md:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <Badge className="rounded-full">Holdet v3</Badge>
              <Badge variant="outline" className="rounded-full">
                ChatGPT independent engine
              </Badge>
            </div>
            <h1 className="text-3xl font-bold tracking-tight">Giro 2026 Fantasy Optimizer Dashboard</h1>
            <p className="mt-2 max-w-3xl text-slate-600">
              Expert audit surface first: verify rules, data integrity, candidate-team logic,
              captain convexity, and forward transfer pressure before using it for top-1%
              optimization decisions.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm md:w-80">
            <Card className="rounded-2xl">
              <CardContent className="p-4">
                <div className="text-slate-500">Stage</div>
                <div className="text-2xl font-bold">{sampleStage.stage}</div>
              </CardContent>
            </Card>
            <Card className="rounded-2xl">
              <CardContent className="p-4">
                <div className="text-slate-500">Audit</div>
                <div className="text-2xl font-bold">{auditScore}%</div>
              </CardContent>
            </Card>
          </div>
        </header>

        <Tabs defaultValue="audit" className="space-y-6">
          <TabsList className="grid w-full grid-cols-2 rounded-2xl md:grid-cols-6">
            <TabsTrigger value="audit">Audit</TabsTrigger>
            <TabsTrigger value="riders">Riders</TabsTrigger>
            <TabsTrigger value="teams">Teams</TabsTrigger>
            <TabsTrigger value="captain">Captain</TabsTrigger>
            <TabsTrigger value="pressure">Forward</TabsTrigger>
            <TabsTrigger value="output">Output</TabsTrigger>
          </TabsList>

          <TabsContent value="audit">
            <div className="grid gap-6 lg:grid-cols-3">
              <Card className="rounded-3xl lg:col-span-2">
                <CardContent className="p-6">
                  <SectionTitle
                    icon={ShieldCheck}
                    title="Logic Verification"
                    subtitle="Checks that must pass before trusting any recommendation."
                  />
                  <div className="space-y-3">
                    {sampleChecks.map((check) => (
                      <div
                        key={check.label}
                        className="flex items-center justify-between rounded-2xl border bg-white p-4"
                      >
                        <div>
                          <div className="font-medium">{check.label}</div>
                          <div className="text-sm text-slate-500">{check.detail}</div>
                        </div>
                        <StatusBadge status={check.status} />
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
              <Card className="rounded-3xl">
                <CardContent className="p-6">
                  <SectionTitle
                    icon={AlertTriangle}
                    title="Critical Assumptions"
                    subtitle="Explicit assumptions to challenge before lock."
                  />
                  <ul className="space-y-3 text-sm text-slate-700">
                    <li>Stage snapshot is the frozen T0 input.</li>
                    <li>No historical performance priors.</li>
                    <li>Odds and expert intel remain ChatGPT-local.</li>
                    <li>Risk is shown as distribution shape, not hidden penalty.</li>
                    <li>DNS avoidance overrides all optimization.</li>
                  </ul>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="riders">
            <Card className="rounded-3xl">
              <CardContent className="p-6">
                <SectionTitle
                  icon={Search}
                  title="Tier-A / Tier-B Rider Review"
                  subtitle="Stage-specific rider classification from odds and expert intel."
                />
                <div className="overflow-hidden rounded-2xl border">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-100 text-slate-600">
                      <tr>
                        <th className="p-3">Rider</th>
                        <th>Team</th>
                        <th>Price</th>
                        <th>Tier</th>
                        <th>Win%</th>
                        <th>Podium%</th>
                        <th>Top15%</th>
                        <th>Role</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sampleRiders.map((r) => (
                        <tr key={r.name} className="border-t bg-white">
                          <td className="p-3 font-medium">{r.name}</td>
                          <td>{r.team}</td>
                          <td>{r.price.toLocaleString()} kr</td>
                          <td>
                            <Badge variant={r.tier === "A" ? "default" : "outline"}>{r.tier}</Badge>
                          </td>
                          <td>{r.win}</td>
                          <td>{r.podium}</td>
                          <td>{r.top15}</td>
                          <td>{r.role}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="teams">
            <div className="grid gap-6 lg:grid-cols-5">
              <Card className="rounded-3xl lg:col-span-2">
                <CardContent className="p-6">
                  <SectionTitle
                    icon={Trophy}
                    title="Candidate Teams"
                    subtitle="Structurally distinct alternatives, not one prescription."
                  />
                  <div className="space-y-3">
                    {sampleTeams.map((team) => (
                      <button
                        key={team.label}
                        onClick={() => setSelectedTeam(team)}
                        className={`w-full rounded-2xl border p-4 text-left transition hover:bg-slate-50 ${
                          selectedTeam.label === team.label ? "border-slate-900 bg-slate-50" : "bg-white"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="font-semibold">{team.label}</div>
                          <Badge variant="outline">{team.pressure}</Badge>
                        </div>
                        <div className="mt-2 grid grid-cols-4 gap-2 text-xs text-slate-600">
                          <span>EV {team.ev.toLocaleString()}</span>
                          <span>P90 {team.p90.toLocaleString()}</span>
                          <span>P50 {team.p50.toLocaleString()}</span>
                          <span>P10 {team.p10.toLocaleString()}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                </CardContent>
              </Card>
              <Card className="rounded-3xl lg:col-span-3">
                <CardContent className="p-6">
                  <SectionTitle
                    icon={LineChart}
                    title={`${selectedTeam.label} Distribution`}
                    subtitle="CDF/quantile view for expert risk preference."
                  />
                  <div className="h-80">
                    <ResponsiveContainer width="100%" height="100%">
                      <ReLineChart data={sampleCdf} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="percentile" />
                        <YAxis tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                        <Tooltip formatter={(v) => `${Number(v).toLocaleString()} kr`} />
                        <ReferenceLine y={selectedTeam.ev} label="EV" strokeDasharray="3 3" />
                        <Line type="monotone" dataKey="value" strokeWidth={3} dot />
                      </ReLineChart>
                    </ResponsiveContainer>
                  </div>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="captain">
            <Card className="rounded-3xl">
              <CardContent className="p-6">
                <SectionTitle
                  icon={Crown}
                  title="Captain Convexity"
                  subtitle="Rank by E[max(ΔV, 0)], not average stage points alone."
                />
                <div className="grid gap-4 md:grid-cols-3">
                  {sampleRiders.slice(0, 3).map((r, idx) => (
                    <div key={r.name} className="rounded-2xl border bg-white p-5">
                      <div className="mb-2 flex items-center justify-between">
                        <div className="font-semibold">{r.name}</div>
                        <Badge>{idx === 0 ? "Recommended" : "Alternative"}</Badge>
                      </div>
                      <div className="text-sm text-slate-600">Right-tail profile: {r.role}</div>
                      <div className="mt-4 h-24">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart
                            data={[
                              { k: "win", v: r.win },
                              { k: "podium", v: r.podium },
                              { k: "top15", v: r.top15 },
                            ]}
                          >
                            <XAxis dataKey="k" />
                            <YAxis hide />
                            <Tooltip />
                            <Bar dataKey="v" radius={[8, 8, 0, 0]} />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="pressure">
            <Card className="rounded-3xl">
              <CardContent className="p-6">
                <SectionTitle
                  icon={GitBranch}
                  title="Forward Transfer Pressure"
                  subtitle="Deterministic n+2 / n+3 scoring consequences, not simulated yet."
                />
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="rounded-2xl border bg-white p-5">
                    <div className="font-semibold">Stage n+2</div>
                    <p className="mt-2 text-sm text-slate-600">
                      Flag riders likely to become dead weight due to terrain mismatch, DNS risk, or low
                      depth-bonus relevance.
                    </p>
                  </div>
                  <div className="rounded-2xl border bg-white p-5">
                    <div className="font-semibold">Stage n+3</div>
                    <p className="mt-2 text-sm text-slate-600">
                      Estimate forced-transfer pressure and opportunity cost from holding specialists too long.
                    </p>
                  </div>
                  <div className="rounded-2xl border bg-white p-5">
                    <div className="font-semibold">Transfer friction</div>
                    <p className="mt-2 text-sm text-slate-600">
                      Show buy-cost transfer fee and budget lock-in effects explicitly.
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="output">
            <Card className="rounded-3xl">
              <CardContent className="p-6">
                <SectionTitle
                  icon={CheckCircle2}
                  title="Output Contract Preview"
                  subtitle="What should be written to chatgpt/output/stage_N_chatgpt.json."
                />
                <pre className="overflow-auto rounded-2xl bg-slate-950 p-5 text-xs text-slate-100">
                  {JSON.stringify(
                    {
                      stage: sampleStage.stage,
                      generated_by: "chatgpt",
                      tier_a_riders: sampleRiders.filter((r) => r.tier === "A"),
                      candidate_teams: sampleTeams,
                      captain_recommendation: selectedTeam.captain,
                      forward_transfer_pressure: { n_plus_2: "pending", n_plus_3: "pending" },
                      assumptions: [
                        "No historical priors",
                        "Snapshot is authoritative",
                        "Odds/intel not yet loaded",
                      ],
                    },
                    null,
                    2,
                  )}
                </pre>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        <footer className="flex flex-col gap-3 rounded-3xl bg-white p-5 text-sm text-slate-600 shadow-sm md:flex-row md:items-center md:justify-between">
          <div>
            Design intent: audit first, optimize second. Every recommendation should explain the payoff path and
            failure mode.
          </div>
          <Button className="rounded-2xl">
            <SlidersHorizontal className="mr-2 h-4 w-4" /> Expert Controls Placeholder
          </Button>
        </footer>
      </div>
    </div>
  );
}
