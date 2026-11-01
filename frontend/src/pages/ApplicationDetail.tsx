import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorMessage } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { Empty, ErrorBox, Loading, Notice, PageHeader, SeverityBadge, StatusBadge, Table, fmtDate, inr, pct } from "../components/ui";
import type { DocumentRec, Extraction } from "../types";

function ExtractionPanel({ doc, onChanged }: { doc: DocumentRec; onChanged: () => void }) {
  const { data, loading, error, reload } = useAsync(() => api.extraction(doc.id), [doc.id]);
  const [edit, setEdit] = useState<{ field: string; value: string; reason: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    if (!edit) return;
    try { await api.correctField(doc.id, edit.field, edit.value || null, edit.reason); setEdit(null); setErr(null); await reload(); onChanged(); } catch (x) { setErr(errorMessage(x)); }
  };
  const view = async () => { try { window.open(await api.documentBlobUrl(doc.id), "_blank", "noopener"); } catch (x) { setErr(errorMessage(x)); } };
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox message={error ?? "Failed to load"} />;
  const ex: Extraction = data;
  return (
    <div className="space-y-3 border-t border-line bg-canvas px-4 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-soft">
        <span>{ex.document.text_method ?? "no text"} · OCR confidence {pct(ex.document.ocr_confidence)} · {ex.transactions_count} transactions · extraction: {ex.document.extraction_method ?? "—"}</span>
        <button className="btn-ghost" onClick={view}>View original file</button>
      </div>
      {ex.document.processing_error && <ErrorBox message={`Processing exception: ${ex.document.processing_error}`} />}
      {ex.document.warnings?.map((w, i) => <div key={i} className="rounded border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-900">{w}</div>)}
      {err && <ErrorBox message={err} />}
      {ex.fields.length === 0 ? <Empty>No fields extracted.</Empty> : (
        <Table head={["Field", "Value", "Confidence", "Page", "Source", ""]}>
          {ex.fields.map((f) => (
            <tr key={f.field_name}>
              <td className="td font-mono text-xs">{f.field_name}</td>
              <td className="td">{f.value ?? <span className="text-ink-soft">not found</span>}</td>
              <td className="td tabular-nums">{pct(f.confidence)}</td><td className="td">{f.page_number ?? "—"}</td>
              <td className="td text-xs">{f.is_verified ? <span className="text-emerald-700">verified by {f.verified_by}</span> : <span className="text-ink-soft">{f.method} · unverified</span>}</td>
              <td className="td"><button className="text-xs text-brand hover:underline" onClick={() => setEdit({ field: f.field_name, value: f.value ?? "", reason: "" })}>Correct</button></td>
            </tr>))}
        </Table>)}
      {edit && (
        <div className="card space-y-3">
          <div className="text-sm font-medium">Correct <span className="font-mono">{edit.field}</span></div>
          <input className="input" aria-label="Corrected value" value={edit.value} onChange={(e) => setEdit({ ...edit, value: e.target.value })} />
          <input className="input" aria-label="Reason" placeholder="Reason for correction (required)" value={edit.reason} onChange={(e) => setEdit({ ...edit, reason: e.target.value })} />
          <div className="flex gap-2"><button className="btn-primary" disabled={edit.reason.trim().length < 3} onClick={save}>Save correction</button><button className="btn-ghost" onClick={() => setEdit(null)}>Cancel</button></div>
        </div>)}
    </div>
  );
}

export default function ApplicationDetail() {
  const { id = "" } = useParams();
  const { data, loading, error, reload } = useAsync(() => api.application(id), [id]);
  const exc = useAsync(() => api.exceptions({ application_id: id }), [id]);
  const [open, setOpen] = useState<string | null>(null);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox message={error ?? "Not found"} />;
  const { application: a, documents } = data;
  return (
    <>
      <PageHeader title={a.applicant_name} subtitle={`${a.id} · ${a.application_type.replace("_", " ").toLowerCase()} · created ${fmtDate(a.created_at)}`}
        actions={<><Link className="btn-ghost" to="/upload">Upload more</Link><Link className="btn-primary" to={`/applications/${a.id}/verification`}>Verification results</Link></>} />
      <div className="mb-6 grid gap-4 sm:grid-cols-4">
        <div className="card"><div className="text-xs uppercase text-ink-soft">Status</div><div className="mt-2"><StatusBadge value={a.status} /></div></div>
        <div className="card"><div className="text-xs uppercase text-ink-soft">Loan amount</div><div className="mt-2 text-lg font-semibold tabular-nums">{inr(a.loan_amount)}</div></div>
        <div className="card"><div className="text-xs uppercase text-ink-soft">Declared monthly income</div><div className="mt-2 text-lg font-semibold tabular-nums">{inr(a.declared_monthly_income)}</div></div>
        <div className="card"><div className="text-xs uppercase text-ink-soft">Open exceptions</div><div className="mt-2 text-lg font-semibold tabular-nums">{a.open_exceptions}</div></div>
      </div>
      <section className="card mb-6 p-0">
        <h2 className="px-5 pt-4 text-sm font-semibold">Documents</h2>
        {documents.length === 0 ? <Empty>No documents uploaded yet.</Empty> : documents.map((d) => (
          <div key={d.id} className="border-t border-line first:mt-3">
            <button className="flex w-full flex-wrap items-center justify-between gap-2 px-5 py-3 text-left hover:bg-canvas" onClick={() => setOpen(open === d.id ? null : d.id)} aria-expanded={open === d.id}>
              <span className="text-sm"><b>{d.original_filename}</b> <span className="ml-2 text-ink-soft">{d.category}{d.classification_confidence != null && ` (${pct(d.classification_confidence)})`}</span></span>
              <span className="flex items-center gap-2">{d.duplicate_of && <span className="text-xs text-amber-800">duplicate of {d.duplicate_of}</span>}<StatusBadge value={d.status} /></span>
            </button>
            {open === d.id && <ExtractionPanel doc={d} onChanged={reload} />}
          </div>))}
      </section>
      <section className="card p-0">
        <h2 className="px-5 pt-4 text-sm font-semibold">Exceptions</h2>
        {exc.loading ? <Loading /> : !exc.data?.length ? <Empty>No exceptions. A human decision is still required.</Empty> : (
          <Table head={["ID", "Category", "Severity", "Status", "Description"]}>
            {exc.data.map((e) => <tr key={e.id}><td className="td font-mono text-xs">{e.id}</td><td className="td">{e.category}</td><td className="td"><SeverityBadge value={e.severity} /></td>
              <td className="td"><StatusBadge value={e.status} /></td><td className="td max-w-md">{e.description}</td></tr>)}
          </Table>)}
      </section>
      <div className="mt-4"><Notice>Extracted values are machine-read and unverified until a reviewer corrects or confirms them.</Notice></div>
    </>
  );
}
