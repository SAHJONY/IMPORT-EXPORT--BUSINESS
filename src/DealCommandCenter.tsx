import { useEffect, useMemo, useState } from "react";

type Stage =
  | "LEAD"
  | "QUALIFICATION"
  | "SOURCING"
  | "FIRM_QUOTE"
  | "MARGIN_PROTECTION"
  | "BUYER_ACCEPTANCE"
  | "CONTRACT_PO"
  | "PAYMENT_INSTRUMENT"
  | "FULFILLMENT"
  | "REVENUE"
  | "BLOCKED";
type PossibleProfit = {
  status:
    | "EVIDENCED_ESTIMATE"
    | "UNCONFIRMED_TARGET"
    | "TARGET_ONLY"
    | "INPUTS_REQUIRED";
  minUsd?: number;
  maxUsd?: number;
  ratePct?: number;
  period?: string;
  basis: string;
  recurringUsd?: number;
  recurringPeriod?: string;
};
type Deal = {
  id: string;
  title: string;
  market: string;
  stage: Stage;
  priority: "A" | "B" | "C";
  buyer: string;
  supplier: string;
  sahjonyPosition: string;
  economics: string;
  possibleProfit?: PossibleProfit;
  payment: string;
  blocker: string;
  nextAction: string;
  lastActivity: string;
  confidence: number;
  value?: string;
  expectedRevenue?: string;
  source: string;
  evidence: string[];
  documents: string[];
  timeline: { at: string; event: string; status: string }[];
};

const STAGES: Stage[] = [
  "LEAD",
  "QUALIFICATION",
  "SOURCING",
  "FIRM_QUOTE",
  "MARGIN_PROTECTION",
  "BUYER_ACCEPTANCE",
  "CONTRACT_PO",
  "PAYMENT_INSTRUMENT",
  "FULFILLMENT",
  "REVENUE",
];
const LABEL: Record<Stage, string> = {
  LEAD: "Lead",
  QUALIFICATION: "Qualification",
  SOURCING: "Sourcing",
  FIRM_QUOTE: "Firm quote",
  MARGIN_PROTECTION: "Margin protection",
  BUYER_ACCEPTANCE: "Buyer acceptance",
  CONTRACT_PO: "Contract / PO",
  PAYMENT_INSTRUMENT: "Payment instrument",
  FULFILLMENT: "Fulfillment",
  REVENUE: "Revenue",
  BLOCKED: "Blocked",
};

function authHeaders(): Record<string, string> {
  const token = sessionStorage.getItem("sahjony.owner.token") || "";
  const headers: Record<string, string> = { "X-Role": "owner" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}
async function collection(path: string) {
  try {
    const r = await fetch(path, { cache: "no-store", headers: authHeaders() });
    if (!r.ok) return [];
    const body = await r.json();
    return (Object.values(body).find((v) => Array.isArray(v)) || []) as any[];
  } catch {
    return [];
  }
}
async function canonical() {
  try {
    const r = await fetch("/canonical-deals.json", { cache: "no-store" });
    if (!r.ok) return [];
    const body = await r.json();
    return Array.isArray(body.deals) ? (body.deals as Deal[]) : [];
  } catch {
    return [];
  }
}

const usd = (value: number) =>
  `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
function possibleProfitLabel(profit?: PossibleProfit) {
  if (!profit) return "Needs pricing";
  const low = Number(profit.minUsd),
    high = Number(profit.maxUsd);
  if (Number.isFinite(low) && Number.isFinite(high) && high > 0)
    return low === high ? usd(high) : `${usd(low)}–${usd(high)}`;
  if (Number.isFinite(high) && high > 0) return usd(high);
  if (Number.isFinite(profit.ratePct) && Number(profit.ratePct) > 0)
    return `${profit.ratePct}% target`;
  return "Needs pricing";
}
function possibleProfitStatus(profit?: PossibleProfit) {
  return (
    {
      EVIDENCED_ESTIMATE: "Evidenced estimate",
      UNCONFIRMED_TARGET: "Unconfirmed target",
      TARGET_ONLY: "Target only",
      INPUTS_REQUIRED: "Inputs required",
    } as Record<string, string>
  )[profit?.status || "INPUTS_REQUIRED"];
}
function profitFromRows(rows: any[]): PossibleProfit {
  const pick = (...keys: string[]) => {
    for (const row of rows)
      for (const key of keys) {
        const n = Number(row?.[key]);
        if (Number.isFinite(n) && n > 0) return n;
      }
    return undefined;
  };
  const min = pick(
    "possible_profit_min_usd",
    "expected_fee_usd",
    "possible_profit_usd",
  );
  const max = pick(
    "possible_profit_max_usd",
    "expected_fee_usd",
    "possible_profit_usd",
  );
  const rate = pick("possible_profit_rate_pct");
  const source = rows.find(
    (row) =>
      row?.possible_profit_basis ||
      row?.fee_rate_or_amount ||
      row?.expected_fee_usd,
  );
  return {
    status: String(
      source?.possible_profit_status ||
        (min || max
          ? "UNCONFIRMED_TARGET"
          : rate
            ? "TARGET_ONLY"
            : "INPUTS_REQUIRED"),
    ) as PossibleProfit["status"],
    minUsd: min,
    maxUsd: max,
    ratePct: rate,
    period: source?.possible_profit_period,
    basis: String(
      source?.possible_profit_basis ||
        source?.fee_rate_or_amount ||
        "Supplier cost, buyer price and protected SAHJONY compensation are not yet evidenced.",
    ),
    recurringUsd: pick("possible_profit_recurring_usd"),
    recurringPeriod: source?.possible_profit_recurring_period,
  };
}

const css = `
:root{background:#050b13}.deal-os{max-width:1720px;margin:auto;padding:24px;color:#eef6fb;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.deal-os *{box-sizing:border-box}.top{display:flex;gap:18px;justify-content:space-between;align-items:flex-start}.kicker{font-size:10px;font-weight:900;letter-spacing:.17em;color:#5ad8ff}.top h1{font-size:clamp(34px,5vw,64px);line-height:.95;letter-spacing:-.05em;margin:8px 0 10px}.top p{margin:0;color:#93a9ba;max-width:890px;line-height:1.55}.actions{display:flex;gap:8px;flex-wrap:wrap}.btn{border:1px solid rgba(255,255,255,.12);background:#0c1721;color:#eef6fb;border-radius:11px;padding:10px 13px;font-weight:800;cursor:pointer;text-decoration:none}.btn.primary{background:#5ad8ff;color:#03121a}.metrics{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:20px 0}.metric{padding:14px;border:1px solid rgba(255,255,255,.08);border-radius:14px;background:#0a151f}.metric small{color:#7890a4;text-transform:uppercase;font-size:9px;letter-spacing:.12em;font-weight:900}.metric strong{display:block;font-size:25px;margin-top:6px}.metric.profit{border-color:rgba(105,239,170,.24);background:linear-gradient(145deg,rgba(105,239,170,.08),#0a151f)}.metric.profit strong,.profit-value{color:#69efaa}.sync{padding:11px 13px;border:1px solid rgba(90,216,255,.18);border-radius:11px;background:#081925;color:#9dcfe0;margin-bottom:12px;font-size:12px}.controls{display:flex;gap:9px;flex-wrap:wrap;margin:12px 0}.search,.filter{background:#08131d;border:1px solid rgba(255,255,255,.1);color:#edf6fb;border-radius:10px;padding:11px 12px;font-size:14px}.search{flex:1;min-width:250px}.table-wrap{overflow:auto;border:1px solid rgba(255,255,255,.08);border-radius:14px;background:#07111a}.table{border-collapse:collapse;width:100%;min-width:1380px}.table th{position:sticky;top:0;background:#101b26;text-align:left;padding:11px;color:#768da1;font-size:9px;letter-spacing:.11em;text-transform:uppercase}.table td{padding:13px 11px;border-top:1px solid rgba(255,255,255,.065);vertical-align:top}.row{cursor:pointer}.row:hover,.row.selected{background:#0d1924}.title{font-weight:900}.sub{display:block;color:#7890a2;font-size:11px;margin-top:4px}.profit-cell strong{display:block;color:#69efaa;white-space:nowrap}.profit-cell small{display:block;color:#7890a2;margin-top:4px}.pill{display:inline-block;border-radius:999px;padding:5px 8px;background:#152535;font-size:10px;font-weight:900}.pill.a{background:#163326;color:#9be9b6}.pill.blocked{background:#351b23;color:#ff9aad}.detail{margin-top:18px;border:1px solid rgba(255,255,255,.09);border-radius:16px;overflow:hidden;background:#08121c}.detail-head{display:flex;justify-content:space-between;gap:14px;padding:18px;background:#101b26}.detail-head h2{font-size:30px;margin:5px 0}.detail-head p{color:#879eaf;margin:0}.detail-grid{display:grid;grid-template-columns:1.15fr .85fr}.main,.side{padding:18px}.side{border-left:1px solid rgba(255,255,255,.08);background:#061019}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.field{padding:12px;border:1px solid rgba(255,255,255,.07);border-radius:11px}.field small,.section{display:block;color:#758ca0;font-size:9px;text-transform:uppercase;letter-spacing:.11em;font-weight:900}.field strong{display:block;margin-top:6px;line-height:1.4}.field .basis{display:block;color:#8ba1b1;font-size:11px;line-height:1.45;margin-top:6px}.section{color:#5ad8ff;margin:20px 0 9px}.rail{display:grid;grid-template-columns:repeat(10,minmax(86px,1fr));gap:6px;overflow:auto}.step{padding:8px;border:1px solid rgba(255,255,255,.08);border-radius:8px;color:#708699;font-size:9px}.step.done{background:#123024;color:#9ae5b3}.step.current{background:#123041;color:#7de0ff;border-color:#285977}.timeline{display:grid;gap:5px}.event{display:grid;grid-template-columns:90px 1fr auto;gap:9px;padding:9px;border-bottom:1px solid rgba(255,255,255,.06)}.event small{color:#7890a2}.list{padding-left:18px;color:#cad7df}.list li{margin:7px 0}.governance{margin-top:15px;border-left:3px solid #d8b24a;background:#18150d;padding:12px;color:#dacb93;font-size:12px;line-height:1.5}.empty{padding:30px;color:#8fa5b6;text-align:center}@media(max-width:1100px){.metrics{grid-template-columns:repeat(3,1fr)}}@media(max-width:900px){.deal-os{padding:16px}.top{display:block}.actions{margin-top:12px}.metrics{grid-template-columns:repeat(2,1fr)}.detail-grid{grid-template-columns:1fr}.side{border-left:0;border-top:1px solid rgba(255,255,255,.08)}.fields{grid-template-columns:1fr}}
`;

const premiumCss = `
:root{background:#030405}.deal-os{position:relative;max-width:1780px;padding:28px 32px 70px;color:#f5f6f6;background:radial-gradient(circle at 82% -5%,rgba(91,198,229,.11),transparent 25%),#030405;min-height:100vh}.deal-os:before{content:'';position:fixed;inset:0;pointer-events:none;background:linear-gradient(rgba(255,255,255,.012) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.012) 1px,transparent 1px);background-size:54px 54px;mask-image:linear-gradient(#000,transparent 78%)}.deal-os>*{position:relative;z-index:1}.top{min-height:190px;align-items:center;padding:20px 0 25px;border-bottom:1px solid rgba(255,255,255,.09)}.kicker{color:#9aeaff;font-size:8px;letter-spacing:.2em}.top h1{font-size:clamp(48px,6vw,88px);font-weight:650;letter-spacing:-.065em;margin:14px 0 15px}.top p{max-width:850px;color:#8f979f;font-size:13px;line-height:1.7}.actions{justify-content:flex-end}.btn{border-color:rgba(255,255,255,.12);background:rgba(255,255,255,.035);border-radius:999px;padding:11px 15px;font-size:10px;letter-spacing:.02em}.btn:hover{border-color:rgba(255,255,255,.25);background:rgba(255,255,255,.06)}.btn.primary{background:#f4f5f2;color:#050607;border-color:#fff}.metrics{gap:7px;margin:12px 0}.metric{min-height:108px;display:flex;flex-direction:column;justify-content:flex-end;padding:15px;border-color:rgba(255,255,255,.095);border-radius:17px;background:linear-gradient(155deg,rgba(19,23,28,.96),rgba(7,9,12,.97))}.metric small{font-size:7px;color:#69727b;letter-spacing:.15em}.metric strong{font-size:27px;font-weight:650;letter-spacing:-.04em}.metric.profit{border-color:rgba(132,226,173,.18);background:linear-gradient(145deg,rgba(105,239,170,.055),#090d10)}.metric.profit strong,.profit-value{color:#a5edc2}.sync{border-color:rgba(125,232,255,.13);border-radius:13px;background:rgba(90,198,230,.045);color:#7f9da7;font-size:9px;letter-spacing:.025em}.controls{align-items:center;margin:13px 0}.search,.filter{min-height:44px;border-color:rgba(255,255,255,.1);border-radius:999px;background:rgba(255,255,255,.028);font-size:11px;padding:11px 15px;outline:0}.search:focus,.filter:focus{border-color:rgba(125,232,255,.38);box-shadow:0 0 0 3px rgba(125,232,255,.07)}.table-wrap{border-color:rgba(255,255,255,.095);border-radius:19px;background:#07090c;box-shadow:0 26px 80px rgba(0,0,0,.26)}.table th{height:45px;background:rgba(15,18,22,.96);color:#69727b;font-size:7px;letter-spacing:.15em}.table td{padding-top:15px;padding-bottom:15px;border-color:rgba(255,255,255,.055)}.row:hover,.row.selected{background:rgba(125,232,255,.035)}.row:focus-visible{outline:2px solid #9aeaff;outline-offset:-2px}.row.selected{box-shadow:inset 3px 0 #8de8ff}.title{font-size:11px}.sub{color:#6f7881;font-size:9px}.pill{background:#141a20;color:#abb3ba;border:1px solid rgba(255,255,255,.07);font-size:8px;padding:5px 8px}.pill.a{background:rgba(88,196,133,.09);color:#a9e8c0;border-color:rgba(117,220,158,.14)}.pill.blocked{background:rgba(255,99,122,.08);color:#ffabb7;border-color:rgba(255,99,122,.14)}.detail{margin-top:14px;border-color:rgba(255,255,255,.1);border-radius:22px;background:#080b0e;box-shadow:0 28px 85px rgba(0,0,0,.3)}.detail-head{padding:23px;background:linear-gradient(125deg,#151a1f,#0b0e11)}.detail-head h2{font-size:37px;letter-spacing:-.045em}.detail-head p{font-size:11px;color:#7d868e}.main,.side{padding:22px}.side{border-color:rgba(255,255,255,.075);background:#06080a}.fields{gap:7px}.field{min-height:83px;padding:13px;border-color:rgba(255,255,255,.075);border-radius:13px;background:rgba(255,255,255,.015)}.field small,.section{color:#68727a;font-size:7px;letter-spacing:.15em}.field strong{font-size:11px}.field .basis{font-size:9px;color:#737c84}.section{color:#9aeaff;margin-top:23px}.rail{gap:5px}.step{border-color:rgba(255,255,255,.075);border-radius:10px;background:rgba(255,255,255,.018)}.step.done{background:rgba(96,212,145,.09);color:#a4e2bb}.step.current{background:rgba(90,198,230,.1);color:#9aeaff;border-color:rgba(125,232,255,.23)}.event{border-color:rgba(255,255,255,.055)}.governance{border-left-color:#9aeaff;background:rgba(125,232,255,.045);color:#9eb4bc;border-radius:0 12px 12px 0}@media(max-width:900px){.deal-os{padding:16px 13px 50px}.top{min-height:0;padding-top:28px}.top h1{font-size:52px}.actions{justify-content:flex-start}.metrics{margin-top:18px}.metric{min-height:92px}}
`;

export default function DealCommandCenter() {
  const [saved, setSaved] = useState<Deal[]>([]);
  const [liveRows, setLiveRows] = useState<any[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState("ALL");
  const [loading, setLoading] = useState(false);
  const [syncedAt, setSyncedAt] = useState("");
  useEffect(() => {
    if (!sessionStorage.getItem("sahjony.owner.token")) {
      location.replace("/owner-login");
      return;
    }
    refresh();
  }, []);
  async function refresh() {
    setLoading(true);
    const paths = [
      "/crm/intakes",
      "/managed-trade/requests",
      "/managed-trade/cases",
      "/global-sourcing/requests",
      "/intermediary/engagements",
      "/documents",
      "/shipments",
      "/communications/timeline",
      "/finance/journals",
    ];
    const [base, ...all] = await Promise.all([
      canonical(),
      ...paths.map(collection),
    ]);
    setSaved(base);
    setLiveRows(
      all.flatMap((rows, pi) =>
        rows.map((row: any) => ({ ...row, __source: paths[pi] })),
      ),
    );
    setSelectedId((id) => id || base[0]?.id || "");
    setSyncedAt(new Date().toLocaleString());
    setLoading(false);
  }
  const platformDeals = useMemo<Deal[]>(() => {
    const groups = new Map<string, any[]>();
    for (const row of liveRows) {
      const id = String(
        row.deal_id ||
          row.managed_case_id ||
          row.case_id ||
          row.request_id ||
          row.intake_id ||
          row.engagement_id ||
          row.id ||
          "",
      ).trim();
      if (!id) continue;
      groups.set(id, [...(groups.get(id) || []), row]);
    }
    return [...groups.entries()].map(([id, rows], i) => {
      const first = rows[0];
      const raw = String(
        first.status || first.state || "QUALIFICATION",
      ).toUpperCase();
      const mapped = STAGES.includes(raw as Stage)
        ? (raw as Stage)
        : "QUALIFICATION";
      return {
        id,
        title: String(
          first.product_need ||
            first.title ||
            first.legal_name ||
            `Platform deal ${i + 1}`,
        ),
        market: String(
          first.destination_country ||
            first.country_code ||
            first.destination ||
            "—",
        ),
        stage: mapped,
        priority: "C",
        buyer: String(
          first.buyer_name ||
            first.customer_name ||
            first.legal_name ||
            "Platform record",
        ),
        supplier: String(first.supplier_name || "Not linked"),
        sahjonyPosition: String(
          first.sahjony_role ||
            first.role ||
            first.engagement_role ||
            "Platform-controlled transaction",
        ),
        economics: String(
          first.commission || first.margin || first.fee || "Not established",
        ),
        possibleProfit: profitFromRows(rows),
        payment: String(first.payment_terms || "Not established"),
        blocker: String(
          first.blocker || first.hold_reason || "No explicit blocker recorded",
        ),
        nextAction: String(
          first.next_action || "Review linked operating records",
        ),
        lastActivity: String(
          first.updated_at || first.created_at || "Platform record",
        ),
        confidence: Number(first.confidence || 25),
        source: "Live platform aggregation",
        evidence: rows.map(
          (r) => `${r.__source}: ${r.status || r.state || "record present"}`,
        ),
        documents: rows
          .filter((r) => String(r.__source).includes("documents"))
          .map((r) => String(r.filename || r.title || r.id || "Document")),
        timeline: rows.map((r) => ({
          at: String(r.updated_at || r.created_at || "—"),
          event: String(r.event || r.title || r.status || r.__source),
          status: String(r.status || r.state || "record"),
        })),
      };
    });
  }, [liveRows]);
  const deals = useMemo(
    () => [
      ...saved,
      ...platformDeals.filter((p) => !saved.some((s) => s.id === p.id)),
    ],
    [saved, platformDeals],
  );
  const filtered = deals.filter(
    (d) =>
      (stage === "ALL" || d.stage === stage) &&
      `${d.id} ${d.title} ${d.market} ${d.buyer} ${d.supplier}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const selected = deals.find((d) => d.id === selectedId) || filtered[0];
  const nearClose = deals.filter((d) =>
    [
      "FIRM_QUOTE",
      "MARGIN_PROTECTION",
      "BUYER_ACCEPTANCE",
      "CONTRACT_PO",
    ].includes(d.stage),
  ).length;
  const protectedCount = deals.filter((d) =>
    /protect|confirmed|accepted/i.test(`${d.sahjonyPosition} ${d.economics}`),
  ).length;
  const closed = deals.filter((d) => d.stage === "REVENUE").length;
  const blocked = deals.filter((d) => d.stage === "BLOCKED").length;
  const quantifiedProfits = deals
    .map((d) => d.possibleProfit)
    .filter((p): p is PossibleProfit =>
      Boolean(p && (Number(p.minUsd) > 0 || Number(p.maxUsd) > 0)),
    );
  const possibleProfitMin = quantifiedProfits.reduce(
    (sum, p) => sum + Number(p.minUsd || p.maxUsd || 0),
    0,
  );
  const possibleProfitMax = quantifiedProfits.reduce(
    (sum, p) => sum + Number(p.maxUsd || p.minUsd || 0),
    0,
  );
  const possibleProfitTotal =
    possibleProfitMax > 0
      ? possibleProfitMin === possibleProfitMax
        ? usd(possibleProfitMax)
        : `${usd(possibleProfitMin)}–${usd(possibleProfitMax)}`
      : "Needs pricing";
  function stageIndex(d: Deal) {
    return d.stage === "BLOCKED"
      ? Math.max(0, STAGES.indexOf("QUALIFICATION"))
      : STAGES.indexOf(d.stage);
  }
  return (
    <main className="deal-os">
      <style>{css}</style>
      <style>{premiumCss}</style>
      <header className="top">
        <div>
          <div className="kicker">SAHJONY LLC · OWNER REVENUE CONTROL</div>
          <h1>Deal Command Center</h1>
          <p>
            One screen from live demand to final revenue. Click any deal to see
            counterparties, SAHJONY position, economics, evidence, payment path,
            blockers, documents, timeline and every closing gate.
          </p>
        </div>
        <div className="actions">
          <a className="btn" href="/owner/dashboard">
            Executive dashboard
          </a>
          <a className="btn" href="/owner/execution-priority">
            Execution priorities
          </a>
          <button className="btn primary" onClick={refresh}>
            {loading ? "Syncing…" : "Sync live data"}
          </button>
        </div>
      </header>
      <section className="metrics">
        <div className="metric">
          <small>Total deals</small>
          <strong>{deals.length}</strong>
        </div>
        <div className="metric">
          <small>Near close</small>
          <strong>{nearClose}</strong>
        </div>
        <div className="metric">
          <small>Protection signals</small>
          <strong>{protectedCount}</strong>
        </div>
        <div className="metric">
          <small>Blocked</small>
          <strong>{blocked}</strong>
        </div>
        <div className="metric profit">
          <small>Possible profit*</small>
          <strong>{possibleProfitTotal}</strong>
        </div>
        <div className="metric">
          <small>Revenue closed</small>
          <strong>{closed}</strong>
        </div>
      </section>
      <div className="sync">
        Canonical records: {saved.length} · Live platform records:{" "}
        {platformDeals.length} · *Projected, not contracted or collected · Last
        sync: {syncedAt || "waiting"}
      </div>
      <section className="controls">
        <input
          className="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search deal, buyer, supplier, market or ID"
          aria-label="Search deals"
        />
        <select
          className="filter"
          value={stage}
          onChange={(e) => setStage(e.target.value)}
          aria-label="Filter deals by stage"
        >
          <option value="ALL">All stages</option>
          <option value="BLOCKED">Blocked</option>
          {STAGES.map((s) => (
            <option value={s} key={s}>
              {LABEL[s]}
            </option>
          ))}
        </select>
      </section>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Deal</th>
              <th>Stage</th>
              <th>Priority</th>
              <th>Buyer</th>
              <th>Supplier</th>
              <th>SAHJONY position</th>
              <th>Economics</th>
              <th>Possible profit*</th>
              <th>Blocker</th>
              <th>Next action</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((d) => (
              <tr
                key={d.id}
                className={`row ${selected?.id === d.id ? "selected" : ""}`}
                onClick={() => setSelectedId(d.id)}
                tabIndex={0}
                aria-selected={selected?.id === d.id}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelectedId(d.id);
                  }
                }}
              >
                <td>
                  <span className="title">{d.title}</span>
                  <span className="sub">
                    {d.id} · {d.market}
                  </span>
                </td>
                <td>
                  <span
                    className={`pill ${d.stage === "BLOCKED" ? "blocked" : ""}`}
                  >
                    {LABEL[d.stage]}
                  </span>
                </td>
                <td>
                  <span className={`pill ${d.priority === "A" ? "a" : ""}`}>
                    {d.priority}
                  </span>
                </td>
                <td>{d.buyer}</td>
                <td>{d.supplier}</td>
                <td>{d.sahjonyPosition}</td>
                <td>{d.economics}</td>
                <td className="profit-cell">
                  <strong>{possibleProfitLabel(d.possibleProfit)}</strong>
                  <small>{possibleProfitStatus(d.possibleProfit)}</small>
                </td>
                <td>{d.blocker}</td>
                <td>{d.nextAction}</td>
                <td>{d.confidence}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length && (
          <div className="empty">No deals match this filter.</div>
        )}
      </div>
      {selected && (
        <section className="detail">
          <div className="detail-head">
            <div>
              <div className="kicker">LIVE DEAL STRUCTURE · {selected.id}</div>
              <h2>{selected.title}</h2>
              <p>
                {selected.market} · {LABEL[selected.stage]} · Priority{" "}
                {selected.priority} · Confidence {selected.confidence}%
              </p>
            </div>
            <div className="actions">
              <span className="pill">{selected.source}</span>
            </div>
          </div>
          <div className="detail-grid">
            <div className="main">
              <div className="fields">
                <div className="field">
                  <small>Buyer</small>
                  <strong>{selected.buyer}</strong>
                </div>
                <div className="field">
                  <small>Supplier</small>
                  <strong>{selected.supplier}</strong>
                </div>
                <div className="field">
                  <small>SAHJONY position</small>
                  <strong>{selected.sahjonyPosition}</strong>
                </div>
                <div className="field">
                  <small>Economics</small>
                  <strong>{selected.economics}</strong>
                </div>
                <div className="field">
                  <small>Possible profit · projected</small>
                  <strong className="profit-value">
                    {possibleProfitLabel(selected.possibleProfit)}
                    {selected.possibleProfit?.period
                      ? ` · ${selected.possibleProfit.period}`
                      : ""}
                  </strong>
                  <span className="basis">
                    {possibleProfitStatus(selected.possibleProfit)} ·{" "}
                    {selected.possibleProfit?.basis ||
                      "Supplier cost, buyer price and protected SAHJONY compensation are not yet evidenced."}
                    {selected.possibleProfit?.recurringUsd
                      ? ` Recurring scenario: ${usd(selected.possibleProfit.recurringUsd)} · ${selected.possibleProfit.recurringPeriod || "period pending"}.`
                      : ""}
                  </span>
                </div>
                <div className="field">
                  <small>Payment path</small>
                  <strong>{selected.payment}</strong>
                </div>
                <div className="field">
                  <small>Current blocker</small>
                  <strong>{selected.blocker}</strong>
                </div>
                <div className="field">
                  <small>Next close action</small>
                  <strong>{selected.nextAction}</strong>
                </div>
                <div className="field">
                  <small>Last activity</small>
                  <strong>{selected.lastActivity}</strong>
                </div>
              </div>
              <div className="section">Closing lifecycle</div>
              <div className="rail">
                {STAGES.map((s, i) => {
                  const current = stageIndex(selected);
                  return (
                    <div
                      key={s}
                      className={`step ${selected.stage !== "BLOCKED" && i < current ? "done" : ""} ${selected.stage !== "BLOCKED" && i === current ? "current" : ""}`}
                    >
                      {String(i + 1).padStart(2, "0")}
                      <br />
                      {LABEL[s]}
                    </div>
                  );
                })}
              </div>
              <div className="section">Timeline</div>
              <div className="timeline">
                {selected.timeline.map((t, i) => (
                  <div className="event" key={`${t.at}-${i}`}>
                    <small>{t.at}</small>
                    <span>{t.event}</span>
                    <span className="pill">{t.status}</span>
                  </div>
                ))}
              </div>
            </div>
            <aside className="side">
              <div className="section">Evidence</div>
              <ul className="list">
                {selected.evidence.length ? (
                  selected.evidence.map((x, i) => <li key={i}>{x}</li>)
                ) : (
                  <li>No evidence attached yet.</li>
                )}
              </ul>
              <div className="section">Documents / artifacts</div>
              <ul className="list">
                {selected.documents.length ? (
                  selected.documents.map((x, i) => <li key={i}>{x}</li>)
                ) : (
                  <li>No document records linked yet.</li>
                )}
              </ul>
              <div className="governance">
                <strong>Governance gate</strong>
                <br />
                This screen never upgrades a deal to QUALIFIED, CONTRACTED,
                FUNDED, CLOSING_READY or REVENUE without evidence.
                Buyer/supplier introductions remain controlled until SAHJONY
                economics are protected.
              </div>
            </aside>
          </div>
        </section>
      )}
    </main>
  );
}
