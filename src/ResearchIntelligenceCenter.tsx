import { useEffect, useMemo, useState } from "react";

type RawDeal = Record<string, any>;
type IntelligenceRow = {
  id: string;
  title: string;
  market: string;
  sourceStage: string;
  intelligenceStage: string;
  priority: "A" | "B" | "C";
  buyer: string;
  supplier: string;
  score: number;
  confidence: number;
  possibleProfit: number;
  evidenceCount: number;
  blocker: string;
  nextAction: string;
};

const DATA_ENDPOINTS = ["/canonical-deals.json", "/api/deals"] as const;

function authHeaders(): Record<string, string> {
  const token = sessionStorage.getItem("sahjony.owner.token") || "";
  const headers: Record<string, string> = { "X-Role": "owner" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

function text(value: unknown, fallback = "—") {
  const normalized = String(value ?? "").trim();
  return normalized || fallback;
}

function numberFrom(...values: unknown[]) {
  for (const value of values) {
    const n = Number(value);
    if (Number.isFinite(n) && n > 0) return n;
  }
  return 0;
}

function known(value: string) {
  return Boolean(value && value !== "—" && !/not linked|not established|platform record|unknown|pending/i.test(value));
}

function stageFor(row: RawDeal, score: number, buyerKnown: boolean, supplierKnown: boolean, profitKnown: boolean) {
  const raw = text(row.stage || row.status || "LEAD").toUpperCase();
  if (/REVENUE|COLLECTED/.test(raw)) return "Collected revenue";
  if (/INVOICE/.test(raw)) return "Invoiced";
  if (/CONTRACT|PO/.test(raw)) return "Contracted transaction";
  if (/FIRM_QUOTE/.test(raw)) return "Firm quotation";
  if (/RFQ/.test(raw)) return "RFQ ready";
  if (score >= 75 && buyerKnown && supplierKnown && profitKnown) return "RFQ ready";
  if (score >= 55 && buyerKnown) return "Qualified demand";
  return "Research lead";
}

function nextBestAction(input: {
  buyerKnown: boolean;
  supplierKnown: boolean;
  profitKnown: boolean;
  evidenceCount: number;
  score: number;
  blocker: string;
}) {
  if (!input.buyerKnown) return "Verify buyer identity, authority and credible purchase intent.";
  if (input.evidenceCount < 2) return "Attach source evidence and verify the commercial facts before escalation.";
  if (!input.supplierKnown) return "Source U.S. suppliers first, then global alternatives; compare landed economics and terms.";
  if (!input.profitKnown) return "Establish evidenced supplier cost, buyer price and protected SAHJONY gross profit.";
  if (input.blocker !== "—" && !/no explicit blocker|none/i.test(input.blocker)) return `Resolve blocker: ${input.blocker}`;
  if (input.score < 75) return "Close the remaining qualification gaps and convert the demand into an RFQ-ready package.";
  return "Issue/solicit a firm RFQ package, protect SAHJONY economics, and advance toward a firm quotation.";
}

function normalize(row: RawDeal, index: number): IntelligenceRow {
  const buyer = text(row.buyer || row.buyer_name || row.customer_name || row.legal_name || row.counterparty);
  const supplier = text(row.supplier || row.supplier_name || row.vendor_name || "Not linked");
  const evidence = Array.isArray(row.evidence) ? row.evidence.filter(Boolean) : [];
  const documents = Array.isArray(row.documents) ? row.documents.filter(Boolean) : [];
  const evidenceCount = evidence.length + documents.length;
  const confidence = Math.max(0, Math.min(100, numberFrom(row.confidence, row.confidence_score) || 25));
  const possibleProfit = numberFrom(
    row?.possibleProfit?.maxUsd,
    row?.possibleProfit?.minUsd,
    row.possible_profit_max_usd,
    row.possible_profit_min_usd,
    row.possible_profit_usd,
    row.expected_fee_usd,
  );
  const blocker = text(row.blocker || row.hold_reason || "No explicit blocker recorded");
  const buyerKnown = known(buyer);
  const supplierKnown = known(supplier);
  const profitKnown = possibleProfit > 0;
  let score = 0;
  score += buyerKnown ? 22 : 0;
  score += supplierKnown ? 18 : 0;
  score += Math.min(20, evidenceCount * 7);
  score += Math.round(confidence * 0.2);
  score += profitKnown ? 15 : 0;
  score += /no explicit blocker|none/i.test(blocker) ? 5 : 0;
  score = Math.max(0, Math.min(100, score));
  const priority: "A" | "B" | "C" = score >= 75 && profitKnown ? "A" : score >= 55 ? "B" : "C";
  return {
    id: text(row.id || row.deal_id || row.opportunity_id || `INT-${index + 1}`),
    title: text(row.title || row.product_need || row.product || row.legal_name || `Opportunity ${index + 1}`),
    market: text(row.market || row.destination_country || row.country_code || row.destination),
    sourceStage: text(row.stage || row.status || "LEAD"),
    intelligenceStage: stageFor(row, score, buyerKnown, supplierKnown, profitKnown),
    priority,
    buyer,
    supplier,
    score,
    confidence,
    possibleProfit,
    evidenceCount,
    blocker,
    nextAction: nextBestAction({ buyerKnown, supplierKnown, profitKnown, evidenceCount, score, blocker }),
  };
}

async function readRows(response: Response): Promise<RawDeal[]> {
  if (!response.ok) return [];
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.toLowerCase().includes("application/json")) return [];
  try {
    const body = await response.json();
    if (Array.isArray(body)) return body;
    if (Array.isArray(body?.deals)) return body.deals;
    const firstArray = Object.values(body || {}).find((value) => Array.isArray(value));
    return Array.isArray(firstArray) ? (firstArray as RawDeal[]) : [];
  } catch {
    return [];
  }
}

const usd = (n: number) => (n > 0 ? `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "Needs pricing");

const css = `
:root{background:#030405}.intel{min-height:100vh;background:radial-gradient(circle at 82% -8%,rgba(74,198,230,.12),transparent 26%),#030405;color:#f5f7f8;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:28px 32px 72px}.intel *{box-sizing:border-box}.shell{max-width:1780px;margin:auto}.hero{display:flex;justify-content:space-between;gap:28px;align-items:flex-end;padding:24px 0 28px;border-bottom:1px solid rgba(255,255,255,.09)}.kicker{font-size:9px;font-weight:900;letter-spacing:.18em;color:#8be8ff;text-transform:uppercase}.hero h1{font-size:clamp(46px,6vw,86px);line-height:.92;letter-spacing:-.065em;margin:12px 0 15px;font-weight:650}.hero p{max-width:900px;color:#8f99a2;line-height:1.65;font-size:13px}.actions{display:flex;gap:8px;flex-wrap:wrap}.btn{border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.035);color:#f5f7f8;border-radius:999px;padding:11px 15px;font-weight:800;font-size:10px;text-decoration:none;cursor:pointer}.btn.primary{background:#f4f5f2;color:#050607}.metrics{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin:14px 0}.metric{min-height:104px;padding:15px;border:1px solid rgba(255,255,255,.09);border-radius:17px;background:linear-gradient(155deg,rgba(18,22,26,.96),rgba(7,9,12,.97));display:flex;flex-direction:column;justify-content:flex-end}.metric small,.card small{font-size:8px;letter-spacing:.14em;text-transform:uppercase;color:#707b84;font-weight:900}.metric strong{display:block;font-size:27px;letter-spacing:-.04em;margin-top:7px}.metric.good strong{color:#a6edc3}.metric.warn strong{color:#ffd28b}.doctrine{display:grid;grid-template-columns:1.25fr .75fr;gap:9px;margin:10px 0 14px}.card{border:1px solid rgba(255,255,255,.09);border-radius:17px;background:#080b0f;padding:16px}.flow{display:flex;gap:7px;flex-wrap:wrap;margin-top:11px}.step{padding:8px 10px;border:1px solid rgba(139,232,255,.14);border-radius:999px;background:rgba(139,232,255,.035);font-size:9px;color:#a7c5ce}.rules{margin:10px 0 0;padding-left:18px;color:#aab4bc;font-size:11px;line-height:1.55}.controls{display:flex;gap:8px;align-items:center;margin:10px 0}.search,.filter{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.1);color:#f3f5f6;border-radius:999px;padding:11px 14px;font-size:11px}.search{flex:1;min-width:260px}.table-wrap{overflow:auto;border:1px solid rgba(255,255,255,.09);border-radius:18px;background:#07090c}.table{border-collapse:collapse;width:100%;min-width:1420px}.table th{position:sticky;top:0;background:#0f1216;text-align:left;padding:11px;color:#6e7881;font-size:7px;letter-spacing:.14em;text-transform:uppercase}.table td{padding:13px 11px;border-top:1px solid rgba(255,255,255,.055);font-size:11px;vertical-align:top}.title{font-weight:900}.sub{display:block;color:#6f7881;font-size:9px;margin-top:4px}.pill{display:inline-block;border:1px solid rgba(255,255,255,.08);border-radius:999px;background:#131920;padding:5px 8px;font-size:8px;font-weight:900}.pill.a{background:#143025;color:#a7efc4}.pill.b{background:#302713;color:#f2d697}.score{font-weight:900;color:#8be8ff}.profit{color:#a7efc4;font-weight:900}.foot{margin-top:10px;padding:11px 13px;border:1px solid rgba(255,210,139,.13);background:rgba(255,210,139,.035);border-radius:13px;color:#9f967f;font-size:10px;line-height:1.5}@media(max-width:1100px){.metrics{grid-template-columns:repeat(3,1fr)}.doctrine{grid-template-columns:1fr}}@media(max-width:700px){.intel{padding:18px}.hero{display:block}.actions{margin-top:16px}.metrics{grid-template-columns:repeat(2,1fr)}}
`;

export default function ResearchIntelligenceCenter() {
  const [rows, setRows] = useState<RawDeal[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncedAt, setSyncedAt] = useState("");
  const [query, setQuery] = useState("");
  const [priority, setPriority] = useState("ALL");

  async function refresh() {
    setLoading(true);
    const requests = DATA_ENDPOINTS.map((endpoint) =>
      fetch(endpoint, {
        cache: "no-store",
        ...(endpoint === "/api/deals" ? { headers: authHeaders() } : {}),
      }),
    );
    const responses = await Promise.allSettled(requests);
    const merged: RawDeal[] = [];
    for (const result of responses) {
      if (result.status !== "fulfilled") continue;
      merged.push(...(await readRows(result.value)));
    }
    const unique = new Map<string, RawDeal>();
    merged.forEach((row, index) => unique.set(text(row.id || row.deal_id || row.opportunity_id || `row-${index}`), row));
    setRows([...unique.values()]);
    setSyncedAt(new Date().toLocaleString());
    setLoading(false);
  }

  useEffect(() => { void refresh(); }, []);

  const intelligence = useMemo(() => rows.map(normalize), [rows]);
  const filtered = intelligence.filter((row) => {
    const matchesPriority = priority === "ALL" || row.priority === priority;
    const haystack = `${row.id} ${row.title} ${row.market} ${row.buyer} ${row.supplier}`.toLowerCase();
    return matchesPriority && haystack.includes(query.toLowerCase());
  });
  const priorityA = intelligence.filter((row) => row.priority === "A").length;
  const rfqReady = intelligence.filter((row) => row.intelligenceStage === "RFQ ready").length;
  const evidenceGaps = intelligence.filter((row) => row.evidenceCount < 2).length;
  const possibleProfit = intelligence.reduce((sum, row) => sum + row.possibleProfit, 0);
  const qualityAdjustedProxy = intelligence.reduce(
    (sum, row) => sum + row.possibleProfit * (row.confidence / 100) * (row.score / 100),
    0,
  );

  return (
    <main className="intel">
      <style>{css}</style>
      <div className="shell">
        <header className="hero">
          <div>
            <div className="kicker">SAHJONY LLC · 10X COMMERCIAL INTELLIGENCE</div>
            <h1>Research Intelligence Center</h1>
            <p>Prioritize evidence-backed demand by commercial quality, profit visibility, counterparty readiness and conversion probability. Research activity is not revenue: every opportunity stays separated until it becomes qualified demand, RFQ ready, firmly quoted, contracted, invoiced and collected.</p>
          </div>
          <div className="actions">
            <a className="btn" href="/owner/dashboard">Executive dashboard</a>
            <a className="btn" href="/owner/deals">Deal Command Center</a>
            <button className="btn primary" onClick={refresh}>{loading ? "Syncing…" : "Sync intelligence"}</button>
          </div>
        </header>

        <section className="metrics">
          <div className="metric"><small>Research opportunities</small><strong>{intelligence.length}</strong></div>
          <div className="metric good"><small>Priority A</small><strong>{priorityA}</strong></div>
          <div className="metric good"><small>RFQ ready</small><strong>{rfqReady}</strong></div>
          <div className="metric warn"><small>Evidence gaps</small><strong>{evidenceGaps}</strong></div>
          <div className="metric good"><small>Quantified possible profit*</small><strong>{usd(possibleProfit)}</strong></div>
          <div className="metric"><small>Quality-adjusted proxy*</small><strong>{usd(qualityAdjustedProxy)}</strong></div>
        </section>

        <section className="doctrine">
          <div className="card">
            <small>Evidence-gated commercial lifecycle</small>
            <div className="flow">
              {["Research lead","Qualified demand","RFQ ready","Sourcing","Firm quotation","Margin protection","Contracted transaction","Invoiced","Fulfillment","Collected revenue"].map((item) => <span className="step" key={item}>{item}</span>)}
            </div>
          </div>
          <div className="card">
            <small>10X allocation rule</small>
            <ul className="rules">
              <li>Spend research time where verified demand, gross-profit potential and close probability are highest.</li>
              <li>Prefer U.S. supply first when commercially competitive and compliant; benchmark global alternatives.</li>
              <li>Protect SAHJONY economics before exposing counterparties or enabling bypass.</li>
              <li>Minimize SAHJONY capital exposure and optimize for legitimate collected gross profit, not activity volume.</li>
            </ul>
          </div>
        </section>

        <section className="controls">
          <input className="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search opportunity, buyer, supplier, market or ID" aria-label="Search intelligence" />
          <select className="filter" value={priority} onChange={(event) => setPriority(event.target.value)} aria-label="Filter by research priority">
            <option value="ALL">All priorities</option><option value="A">Priority A</option><option value="B">Priority B</option><option value="C">Priority C</option>
          </select>
        </section>

        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Opportunity</th><th>Intelligence stage</th><th>Priority</th><th>Research score</th><th>Buyer</th><th>Supplier</th><th>Possible profit*</th><th>Evidence</th><th>Next best action</th></tr></thead>
            <tbody>{filtered.map((row) => (
              <tr key={row.id}>
                <td><span className="title">{row.title}</span><span className="sub">{row.id} · {row.market} · source: {row.sourceStage}</span></td>
                <td><span className="pill">{row.intelligenceStage}</span></td>
                <td><span className={`pill ${row.priority.toLowerCase()}`}>{row.priority}</span></td>
                <td><span className="score">{row.score}%</span><span className="sub">confidence {row.confidence}%</span></td>
                <td>{row.buyer}</td><td>{row.supplier}</td><td className="profit">{usd(row.possibleProfit)}</td>
                <td>{row.evidenceCount} artifact{row.evidenceCount === 1 ? "" : "s"}</td><td>{row.nextAction}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>

        <div className="foot">*Possible profit and quality-adjusted opportunity are planning signals, not contracted or collected revenue. The quality-adjusted proxy multiplies quantified possible profit by recorded confidence and research score; it must not be represented to customers or management as guaranteed revenue. Last sync: {syncedAt || "waiting"}.</div>
      </div>
    </main>
  );
}
