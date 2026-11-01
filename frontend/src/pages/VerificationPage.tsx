import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Cell } from "recharts";
import { api, errorMessage } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { Empty, ErrorBox, Loading, Notice, PageHeader, SeverityBadge, StatusBadge, Table, inr } from "../components/ui";

export default function VerificationPage() {
  const { id = "" } = useParams();
  const v = useAsync(() => api.verification(id), [id]);
  const t = useAsync(() => api.transactions(id), [id]);
  const [running, setRunning] = useState(false); const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<"issues" | "all">("issues");
  const run = async () => { setRunning(true); setErr(null); try { v.setData(await api.verify(id)); await t.reload(); } catch (x) { setErr(errorMessage(x)); } finally { setRunning(false); } };
  if (v.loading) return <Loading />;
  if (v.error || !v.data) return <ErrorBox message={v.error ?? "Not found"} />;
  const d = v.data;
  const rows = d.results.filter((r) => filter === "all" || r.outcome === "FAIL" || r.outcome === "WARN");
  const monthly = Object.values((t.data?.transactions ?? []).reduce<Record<string, { month: string; credits: number }>>((acc, x) => {
    const m = x.txn_date.slice(0, 7); acc[m] = acc[m] ?? { month: m, credits: 0 }; acc[m].credits += x.credit; return acc;
  }, {})).sort((a, b) => a.month.localeCompare(b.month));
  const flagged = new Set((t.data?.transactions ?? []).filter((x) => x.is_anomalous).map((x) => x.txn_date.slice(0, 7)));
  const findingMonths = new Set((t.data?.account_findings ?? []).flatMap((f) => (f as { months?: string[] }).months ?? []));
  return (
    <>
      <PageHeader title="Verification results" subtitle={`Application ${id}`}
        actions={<><Link className="btn-ghost" to={`/applications/${id}`}>Back to application</Link><button className="btn-primary" disabled={running} onClick={run}>{running ? "Running…" : "Run verification"}</button></>} />
      {err && <div className="mb-4"><ErrorBox message={err} /></div>}
      <div className="card mb-6">
        <div className="text-sm font-medium">{d.summary.headline}</div>
        <div className="mt-3 flex flex-wrap gap-4 text-sm">{Object.entries(d.summary.counts).map(([k, n]) => <span key={k}><StatusBadge value={k} /> <b className="ml-1 tabular-nums">{n}</b></span>)}</div>
        {d.ai_summary && <div className="mt-4 rounded border border-line bg-canvas p-3 text-sm"><div className="mb-1 text-xs font-semibold uppercase text-ink-soft">AI-written summary</div>{d.ai_summary}<div className="mt-2 text-xs text-ink-soft">{d.ai_summary_notice}</div></div>}
        <div className="mt-4"><Notice>{d.summary.notice ?? "Run verification to evaluate the rules."}</Notice></div>
      </div>
      <section className="card mb-6 p-0">
        <div className="flex items-center justify-between px-5 pt-4"><h2 className="text-sm font-semibold">Rule results</h2>
          <select className="input w-40" value={filter} onChange={(e) => setFilter(e.target.value as "issues" | "all")} aria-label="Filter results"><option value="issues">Issues only</option><option value="all">All results</option></select></div>
        {!rows.length ? <Empty>{d.results.length ? "No failed or warning results." : "Verification has not been run."}</Empty> : (
          <Table head={["Rule", "Outcome", "Severity", "Expected", "Observed", "Explanation"]}>
            {rows.map((r) => <tr key={r.id}><td className="td font-mono text-xs">{r.rule_id} <span className="text-ink-soft">v{r.rule_version}</span></td><td className="td"><StatusBadge value={r.outcome} /></td>
              <td className="td"><SeverityBadge value={r.severity} /></td><td className="td text-xs">{r.expected ?? "—"}</td><td className="td text-xs">{r.observed ?? "—"}</td><td className="td max-w-md">{r.explanation}</td></tr>)}
          </Table>)}
      </section>
      {t.data && t.data.total > 0 && (
        <section className="card">
          <h2 className="text-sm font-semibold">Transaction anomaly screening</h2>
          <p className="mb-3 mt-1 text-xs text-ink-soft">{t.data.notice} Detector flags: {Object.entries(t.data.detector_comparison).map(([k, n]) => `${k.replace(/_/g, " ")} ${n}`).join(" · ")}</p>
          <ResponsiveContainer width="100%" height={200}><BarChart data={monthly}><CartesianGrid stroke="#e3e7ee" vertical={false} /><XAxis dataKey="month" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} tickFormatter={(x) => `${Math.round(x / 1000)}k`} /><Tooltip formatter={(x) => inr(x as number)} />
            <Bar dataKey="credits" radius={[4, 4, 0, 0]}>{monthly.map((m) => <Cell key={m.month} fill={flagged.has(m.month) || findingMonths.has(m.month) ? "#d97706" : "#1d4ed8"} />)}</Bar></BarChart></ResponsiveContainer>
          <div className="text-xs text-ink-soft">Monthly credits; amber months contain a flagged transaction or account-level finding.</div>
          {t.data.account_findings.map((f, i) => <div key={i} className="mt-2 rounded border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-900">{f.message}</div>)}
          {t.data.transactions.some((x) => x.is_anomalous) && (
            <div className="mt-4"><Table head={["Date", "Description", "Credit", "Debit", "Why flagged"]}>
              {t.data.transactions.filter((x) => x.is_anomalous).map((x) => <tr key={x.id}><td className="td">{x.txn_date}</td><td className="td">{x.description}</td><td className="td tabular-nums">{x.credit ? inr(x.credit) : "—"}</td><td className="td tabular-nums">{x.debit ? inr(x.debit) : "—"}</td><td className="td text-xs">{x.anomaly_reasons?.join("; ")}</td></tr>)}
            </Table></div>)}
        </section>)}
    </>
  );
}
