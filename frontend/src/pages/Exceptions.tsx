import { useState } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { useAuth } from "../hooks/AuthContext";
import { Empty, ErrorBox, Loading, PageHeader, SeverityBadge, StatusBadge, Table, fmtDate } from "../components/ui";
import type { ExcStatus } from "../types";

const NEXT: Record<string, ExcStatus[]> = {
  OPEN: ["IN_REVIEW", "AWAITING_DOCUMENTS", "ESCALATED", "RESOLVED"], REOPENED: ["IN_REVIEW", "AWAITING_DOCUMENTS", "ESCALATED", "RESOLVED"],
  IN_REVIEW: ["AWAITING_DOCUMENTS", "ESCALATED", "RESOLVED"], AWAITING_DOCUMENTS: ["IN_REVIEW", "ESCALATED", "RESOLVED"],
  ESCALATED: ["IN_REVIEW", "RESOLVED"], RESOLVED: ["REOPENED"],
};
const LABEL: Record<string, string> = { IN_REVIEW: "start review", REOPENED: "reopen", RESOLVED: "resolve", ESCALATED: "escalate", AWAITING_DOCUMENTS: "awaiting documents" };
const NEEDS_COMMENT = new Set(["RESOLVED", "ESCALATED", "AWAITING_DOCUMENTS", "REOPENED"]);

function Detail({ id, onChanged, onClose }: { id: string; onChanged: () => void; onClose: () => void }) {
  const { user } = useAuth();
  const d = useAsync(() => api.exception(id), [id]);
  const reviewers = useAsync(api.reviewers);
  const [comment, setComment] = useState(""); const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<unknown>) => { setBusy(true); setErr(null); try { await fn(); setComment(""); await d.reload(); onChanged(); } catch (x) { setErr(errorMessage(x)); } finally { setBusy(false); } };
  if (d.loading) return <Loading />;
  if (d.error || !d.data) return <ErrorBox message={d.error ?? "Not found"} />;
  const e = d.data;
  return (
    <aside className="card space-y-4" aria-label="Exception detail">
      <div className="flex items-start justify-between"><div><div className="font-mono text-xs text-ink-soft">{e.id} · rule {e.rule_id}</div><div className="mt-1 font-semibold">{e.category}</div></div>
        <button className="text-sm text-ink-soft hover:text-ink" onClick={onClose} aria-label="Close detail">✕</button></div>
      <div className="flex gap-2"><SeverityBadge value={e.severity} /><StatusBadge value={e.status} /></div>
      <p className="text-sm">{e.description}</p>
      <Link className="text-sm text-brand hover:underline" to={`/applications/${e.application_id}`}>Open application {e.application_id}</Link>
      {e.evidence && <details className="text-xs"><summary className="cursor-pointer font-medium">Evidence</summary><pre className="mt-2 max-h-48 overflow-auto rounded bg-canvas p-2">{JSON.stringify(e.evidence, null, 2)}</pre></details>}
      {err && <ErrorBox message={err} />}
      <label className="block text-sm">Assigned reviewer
        <select className="input mt-1" value={e.assigned_reviewer ?? ""} disabled={busy} onChange={(ev) => act(() => api.assign(e.id, ev.target.value || null))}>
          <option value="">Unassigned</option>{reviewers.data?.map((r) => <option key={r}>{r}</option>)}</select></label>
      <label className="block text-sm">Comment<textarea className="input mt-1" rows={3} value={comment} onChange={(ev) => setComment(ev.target.value)} placeholder="Required for resolve, escalate, awaiting documents and reopen" /></label>
      <div className="flex flex-wrap gap-2">
        {(NEXT[e.status] ?? []).filter((s) => !(e.status === "ESCALATED" && s === "RESOLVED" && user?.role !== "admin")).map((s) => (
          <button key={s} className="btn-ghost" disabled={busy || (NEEDS_COMMENT.has(s) && comment.trim().length === 0)} onClick={() => act(() => api.setStatus(e.id, s, comment || undefined))}>{LABEL[s] ?? s.replace(/_/g, " ").toLowerCase()}</button>))}
        <button className="btn-ghost" disabled={busy || !comment.trim()} onClick={() => act(() => api.comment(e.id, comment))}>Add comment</button>
      </div>
      {e.status === "ESCALATED" && user?.role !== "admin" && <div className="text-xs text-ink-soft">Only an administrator can resolve an escalated exception.</div>}
      <div><div className="mb-2 text-xs font-semibold uppercase text-ink-soft">History</div>
        <ul className="space-y-2 text-sm">{e.reviews.map((r) => <li key={r.id} className="rounded bg-canvas px-3 py-2"><div className="text-xs text-ink-soft">{r.reviewer} · {r.action} · {fmtDate(r.created_at)}</div>{r.comment}</li>)}
          {!e.reviews.length && <li className="text-ink-soft">No activity yet.</li>}</ul></div>
    </aside>
  );
}

export default function Exceptions() {
  const [f, setF] = useState({ status: "", severity: "", category: "" });
  const [sel, setSel] = useState<string | null>(null);
  const list = useAsync(() => api.exceptions({ status: f.status || undefined, severity: f.severity || undefined, category: f.category || undefined }), [f.status, f.severity, f.category]);
  return (
    <>
      <PageHeader title="Exceptions" subtitle="Review queue. Resolving an exception records a human review decision; it does not approve or reject a loan." />
      <div className="mb-4 flex flex-wrap gap-3">
        <select className="input w-44" aria-label="Status" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All statuses</option>{["OPEN", "IN_REVIEW", "AWAITING_DOCUMENTS", "ESCALATED", "RESOLVED", "REOPENED"].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}</select>
        <select className="input w-40" aria-label="Severity" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })}><option value="">All severities</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select>
        <select className="input w-56" aria-label="Category" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}><option value="">All categories</option>
          {["Missing Document", "Identity Mismatch", "Financial Mismatch", "Duplicate Document", "Incomplete Statement", "Low OCR Confidence", "Invalid Document", "Anomalous Transaction", "Manual Verification Required"].map((c) => <option key={c}>{c}</option>)}</select>
      </div>
      <div className={`grid gap-4 ${sel ? "xl:grid-cols-[minmax(0,1fr)_24rem]" : ""}`}>
        <div className="card min-w-0 p-0">
          {list.loading ? <Loading /> : list.error ? <div className="p-4"><ErrorBox message={list.error} /></div> : !list.data?.length ? <Empty>No exceptions match these filters.</Empty> : (
            <Table head={["ID", "Application", "Category", "Severity", "Status", "Reviewer", "Raised"]}>
              {list.data.map((e) => (
                <tr key={e.id} className={`cursor-pointer hover:bg-canvas ${sel === e.id ? "bg-brand-tint" : ""}`} onClick={() => setSel(e.id)} tabIndex={0} onKeyDown={(k) => k.key === "Enter" && setSel(e.id)}>
                  <td className="td whitespace-nowrap font-mono text-xs">{e.id}</td><td className="td whitespace-nowrap font-mono text-xs">{e.application_id}</td><td className="td">{e.category}</td>
                  <td className="td"><SeverityBadge value={e.severity} /></td><td className="td"><StatusBadge value={e.status} /></td><td className="td">{e.assigned_reviewer ?? "—"}</td><td className="td whitespace-nowrap text-xs text-ink-soft">{fmtDate(e.created_at).replace(/, \d{4}/, "")}</td>
                </tr>))}
            </Table>)}
        </div>
        {sel && <Detail id={sel} onChanged={list.reload} onClose={() => setSel(null)} />}
      </div>
    </>
  );
}
