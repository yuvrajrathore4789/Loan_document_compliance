import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, errorMessage } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { Empty, ErrorBox, Loading, Notice, PageHeader, Table, fmtDate } from "../components/ui";

export default function AuditPage() {
  const [f, setF] = useState({ resource_type: "", resource_id: "", action: "", actor: "" });
  const [open, setOpen] = useState<string | null>(null); const [err, setErr] = useState<string | null>(null);
  const params = Object.fromEntries(Object.entries(f).filter(([, v]) => v));
  const ev = useAsync(() => api.audit({ ...params, limit: 200 }), [JSON.stringify(f)]);
  const stats = useAsync(api.auditStats);
  const exportCsv = async () => {
    try {
      const csv = await api.auditCsv(params);
      const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = "audit_log.csv"; a.click(); URL.revokeObjectURL(a.href);
      void ev.reload();
    } catch (x) { setErr(errorMessage(x)); }
  };
  return (
    <>
      <PageHeader title="Audit & compliance" subtitle="Append-only application event log" actions={<button className="btn-primary" onClick={exportCsv}>Export CSV</button>} />
      <div className="mb-4"><Notice>{stats.data?.notice ?? "Application-level append-only logging is not equivalent to independently tamper-proof regulatory storage."}</Notice></div>
      {err && <div className="mb-4"><ErrorBox message={err} /></div>}
      {stats.data && <section className="card mb-6"><h2 className="mb-3 text-sm font-semibold">Events by action ({stats.data.total_events} total)</h2>
        <ResponsiveContainer width="100%" height={220}><BarChart data={stats.data.by_action.slice(0, 12)}><CartesianGrid stroke="#e3e7ee" vertical={false} /><XAxis dataKey="action" tick={{ fontSize: 10 }} interval={0} angle={-25} textAnchor="end" height={70} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Bar dataKey="count" fill="#1d4ed8" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></section>}
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(["resource_type", "resource_id", "action", "actor"] as const).map((k) => <input key={k} className="input" placeholder={k.replace("_", " ")} aria-label={k} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} />)}
      </div>
      <div className="card p-0">
        {ev.loading ? <Loading /> : ev.error ? <div className="p-4"><ErrorBox message={ev.error} /></div> : !ev.data?.length ? <Empty>No events match.</Empty> : (
          <Table head={["Time", "Actor", "Action", "Resource", "Details"]}>
            {ev.data.map((e) => (
              <tr key={e.event_id}><td className="td whitespace-nowrap text-ink-soft">{fmtDate(e.created_at)}</td><td className="td">{e.actor}</td><td className="td font-mono text-xs">{e.action}</td>
                <td className="td font-mono text-xs">{e.resource_type}:{e.resource_id}</td>
                <td className="td text-xs"><button className="text-brand hover:underline" onClick={() => setOpen(open === e.event_id ? null : e.event_id)}>{open === e.event_id ? "Hide" : "Show"}</button>
                  {open === e.event_id && <pre className="mt-2 max-w-xl overflow-auto rounded bg-canvas p-2">{JSON.stringify({ previous: e.previous_state, new: e.new_state, details: e.details }, null, 2)}</pre>}</td></tr>))}
          </Table>)}
      </div>
    </>
  );
}
