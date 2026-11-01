import { DragEvent, FormEvent, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage } from "../services/api";
import { ErrorBox, Notice, PageHeader, StatusBadge } from "../components/ui";
import type { UploadResult } from "../types";

const ACCEPT = ".pdf,.png,.jpg,.jpeg";
const MAX_MB = 10;

export default function NewApplication() {
  const [form, setForm] = useState({ applicant_name: "", application_type: "SALARIED", loan_amount: "", declared_monthly_income: "" });
  const [files, setFiles] = useState<File[]>([]);
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [appId, setAppId] = useState<string | null>(null);
  const [results, setResults] = useState<UploadResult[]>([]);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    const bad: string[] = []; const ok: File[] = [];
    Array.from(list).forEach((f) => {
      if (!/\.(pdf|png|jpe?g)$/i.test(f.name)) bad.push(`${f.name}: only PDF, PNG or JPEG`);
      else if (f.size > MAX_MB * 1024 * 1024) bad.push(`${f.name}: larger than ${MAX_MB} MB`);
      else ok.push(f);
    });
    setErr(bad.length ? bad.join("; ") : null);
    setFiles((cur) => [...cur, ...ok].slice(0, 10));
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); };

  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null); setResults([]);
    try {
      let id = appId;
      if (!id) {
        const a = await api.createApplication({
          applicant_name: form.applicant_name, application_type: form.application_type,
          loan_amount: form.loan_amount ? Number(form.loan_amount) : null, declared_monthly_income: form.declared_monthly_income ? Number(form.declared_monthly_income) : null,
        });
        id = a.id; setAppId(id);
      }
      if (files.length) {
        setProgress(0);
        const r = await api.upload(id, files, setProgress);
        setResults(r.results); setFiles([]);
      }
    } catch (x) { setErr(errorMessage(x)); } finally { setBusy(false); setProgress(null); }
  };

  return (
    <>
      <PageHeader title="New application" subtitle="Create an application and upload its documents for automated pre-checks" />
      <div className="mb-4"><Notice>Upload synthetic documents only. Do not upload real identity documents or personal financial records. Aadhaar numbers are redacted on ingest.</Notice></div>
      <form onSubmit={submit} className="grid gap-6 lg:grid-cols-2">
        <section className="card space-y-4">
          <h2 className="text-sm font-semibold">Applicant</h2>
          <label className="block text-sm">Applicant name<input className="input mt-1" required minLength={2} disabled={!!appId} value={form.applicant_name} onChange={(e) => setForm({ ...form, applicant_name: e.target.value })} /></label>
          <label className="block text-sm">Application type
            <select className="input mt-1" disabled={!!appId} value={form.application_type} onChange={(e) => setForm({ ...form, application_type: e.target.value })}>
              <option value="SALARIED">Salaried</option><option value="SELF_EMPLOYED">Self-employed</option></select></label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">Loan amount (INR)<input className="input mt-1" type="number" min={0} disabled={!!appId} value={form.loan_amount} onChange={(e) => setForm({ ...form, loan_amount: e.target.value })} /></label>
            <label className="block text-sm">Monthly income (INR)<input className="input mt-1" type="number" min={0} disabled={!!appId} value={form.declared_monthly_income} onChange={(e) => setForm({ ...form, declared_monthly_income: e.target.value })} /></label>
          </div>
        </section>
        <section className="card space-y-4">
          <h2 className="text-sm font-semibold">Documents</h2>
          <div role="button" tabIndex={0} aria-label="Drop files here or press Enter to browse"
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
            onClick={() => inputRef.current?.click()} onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
            className={`flex h-36 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed text-sm ${drag ? "border-brand bg-brand-tint" : "border-line bg-canvas"}`}>
            <div className="font-medium">Drag and drop files, or click to browse</div>
            <div className="mt-1 text-xs text-ink-soft">PDF, PNG or JPEG · up to {MAX_MB} MB each · max 10 files</div>
          </div>
          <input ref={inputRef} type="file" hidden multiple accept={ACCEPT} onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
          {files.length > 0 && <ul className="divide-y divide-line rounded-md border border-line text-sm">
            {files.map((f, i) => <li key={i} className="flex items-center justify-between px-3 py-2"><span className="truncate">{f.name}</span>
              <button type="button" className="text-xs text-red-700 hover:underline" onClick={() => setFiles(files.filter((_, j) => j !== i))}>Remove</button></li>)}
          </ul>}
          {progress !== null && <div className="h-2 overflow-hidden rounded bg-line" role="progressbar" aria-valuenow={progress}><div className="h-full bg-brand transition-all" style={{ width: `${progress}%` }} /></div>}
          {err && <ErrorBox message={err} />}
          <button className="btn-primary w-full" disabled={busy || !form.applicant_name}>{busy ? "Working…" : appId ? "Upload more documents" : files.length ? "Create application and upload" : "Create application"}</button>
        </section>
      </form>
      {appId && (
        <section className="card mt-6">
          <div className="flex items-center justify-between"><h2 className="text-sm font-semibold">Application {appId}</h2>
            <div className="flex gap-2"><Link className="btn-ghost" to={`/applications/${appId}`}>Open application</Link><Link className="btn-primary" to={`/applications/${appId}/verification`}>Go to verification</Link></div></div>
          {results.length > 0 && <ul className="mt-3 divide-y divide-line text-sm">{results.map((r, i) => (
            <li key={i} className="flex flex-wrap items-center justify-between gap-2 py-2"><span>{r.filename}</span>
              {r.accepted ? <span className="flex items-center gap-2 text-ink-soft">{r.category}{r.status && <StatusBadge value={r.status} />}{r.error && <span className="text-amber-800">processing exception: {r.error}</span>}</span>
                : <span className="text-red-700">Rejected: {r.error}</span>}</li>))}</ul>}
        </section>
      )}
    </>
  );
}
