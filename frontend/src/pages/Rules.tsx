import { FormEvent, useState } from "react";
import { api, errorMessage } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { useAuth } from "../hooks/AuthContext";
import { ErrorBox, Loading, Notice, PageHeader, SeverityBadge, Table, fmtDate } from "../components/ui";
import type { AuditEvent, RuleRec, Severity } from "../types";

const CATEGORIES = ["PAN", "AADHAAR", "SALARY_SLIP", "BANK_STATEMENT", "ITR", "GST_CERTIFICATE", "BUSINESS_REGISTRATION", "LOAN_APPLICATION"];

export default function Rules() {
  const { user } = useAuth(); const isAdmin = user?.role === "admin";
  const rules = useAsync(api.rules); const notice = useAsync(api.rulesNotice);
  const [edit, setEdit] = useState<RuleRec | null>(null);
  const [form, setForm] = useState({ severity: "MEDIUM" as Severity, enabled: true, reason: "", params: "" });
  const [hist, setHist] = useState<{ id: string; events: AuditEvent[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [nr, setNr] = useState({ id: "", name: "", kind: "required_document", category: "PAN", field: "name", severity: "MEDIUM" });

  const startEdit = (r: RuleRec) => { setEdit(r); setForm({ severity: r.severity, enabled: r.enabled, reason: "", params: JSON.stringify(r.params ?? {}, null, 2) }); setErr(null); };
  const save = async (e: FormEvent) => {
    e.preventDefault(); if (!edit) return;
    try {
      await api.patchRule(edit.id, { severity: form.severity, enabled: form.enabled, reason: form.reason, params: JSON.parse(form.params || "{}") });
      setEdit(null); setErr(null); await rules.reload();
    } catch (x) { setErr(x instanceof SyntaxError ? "Params must be valid JSON." : errorMessage(x)); }
  };
  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.createRule({ id: nr.id, name: nr.name, kind: nr.kind, severity: nr.severity, params: nr.kind === "field_present" ? { category: nr.category, field: nr.field } : { category: nr.category } });
      setNr({ ...nr, id: "", name: "" }); setErr(null); await rules.reload();
    } catch (x) { setErr(errorMessage(x)); }
  };
  const showHist = async (id: string) => setHist({ id, events: await api.ruleHistory(id) });

  if (rules.loading) return <Loading />;
  if (rules.error || !rules.data) return <ErrorBox message={rules.error ?? "No data"} />;
  return (
    <>
      <PageHeader title="Verification rules" subtitle={isAdmin ? "Administrators can change severity, thresholds and enablement. Every change is versioned and audited." : "Read-only for reviewers. Only administrators can change rules."} />
      <div className="mb-4"><Notice>{notice.data?.notice}</Notice></div>
      {err && <div className="mb-4"><ErrorBox message={err} /></div>}
      <div className="card mb-6 p-0">
        <Table head={["Rule", "Name", "Type", "Severity", "Enabled", "Version", "Updated", ""]}>
          {rules.data.map((r) => (
            <tr key={r.id} className={r.enabled ? "" : "opacity-60"}>
              <td className="td font-mono text-xs">{r.id}</td><td className="td">{r.name}<div className="text-xs text-ink-soft">{r.description}</div></td><td className="td text-xs">{r.kind}</td>
              <td className="td"><SeverityBadge value={r.severity} /></td><td className="td">{r.enabled ? "Yes" : "No"}</td><td className="td tabular-nums">v{r.version}</td>
              <td className="td text-xs text-ink-soft">{fmtDate(r.updated_at)}<br />{r.updated_by}</td>
              <td className="td whitespace-nowrap text-xs"><button className="text-brand hover:underline" onClick={() => showHist(r.id)}>History</button>{isAdmin && <button className="ml-3 text-brand hover:underline" onClick={() => startEdit(r)}>Edit</button>}</td>
            </tr>))}
        </Table>
      </div>
      {edit && (
        <form onSubmit={save} className="card mb-6 space-y-3"><h2 className="text-sm font-semibold">Edit {edit.id}: {edit.name}</h2>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-sm">Severity<select className="input mt-1" value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value as Severity })}><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select></label>
            <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> Enabled</label>
          </div>
          <label className="block text-sm">Parameters (JSON)<textarea className="input mt-1 font-mono text-xs" rows={5} value={form.params} onChange={(e) => setForm({ ...form, params: e.target.value })} /></label>
          <label className="block text-sm">Reason for change (required, audited)<input className="input mt-1" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} required minLength={3} /></label>
          <div className="flex gap-2"><button className="btn-primary">Save new version</button><button type="button" className="btn-ghost" onClick={() => setEdit(null)}>Cancel</button></div></form>)}
      {hist && <section className="card mb-6"><div className="flex justify-between"><h2 className="text-sm font-semibold">Change history · {hist.id}</h2><button className="text-sm text-ink-soft" onClick={() => setHist(null)}>Close</button></div>
        <ul className="mt-3 space-y-2 text-sm">{hist.events.map((e) => <li key={e.event_id} className="rounded bg-canvas px-3 py-2"><div className="text-xs text-ink-soft">{fmtDate(e.created_at)} · {e.actor} · {e.action}</div>
          {e.details && "reason" in e.details && <div>Reason: {String(e.details.reason)}</div>}<div className="text-xs">v{String(e.previous_state?.version ?? "—")} → v{String(e.new_state?.version ?? "—")}</div></li>)}</ul></section>}
      {isAdmin && (
        <form onSubmit={create} className="card space-y-3"><h2 className="text-sm font-semibold">Add a simple rule</h2>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-sm">ID (e.g. R101)<input className="input mt-1" pattern="R\d{3,4}" required value={nr.id} onChange={(e) => setNr({ ...nr, id: e.target.value })} /></label>
            <label className="text-sm sm:col-span-2">Name<input className="input mt-1" required minLength={3} value={nr.name} onChange={(e) => setNr({ ...nr, name: e.target.value })} /></label>
            <label className="text-sm">Kind<select className="input mt-1" value={nr.kind} onChange={(e) => setNr({ ...nr, kind: e.target.value })}><option value="required_document">Required document</option><option value="field_present">Field present</option></select></label>
            <label className="text-sm">Document category<select className="input mt-1" value={nr.category} onChange={(e) => setNr({ ...nr, category: e.target.value })}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></label>
            {nr.kind === "field_present" && <label className="text-sm">Field name<input className="input mt-1" value={nr.field} onChange={(e) => setNr({ ...nr, field: e.target.value })} /></label>}
            <label className="text-sm">Severity<select className="input mt-1" value={nr.severity} onChange={(e) => setNr({ ...nr, severity: e.target.value })}><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select></label>
          </div>
          <button className="btn-primary">Create rule</button></form>)}
    </>
  );
}
