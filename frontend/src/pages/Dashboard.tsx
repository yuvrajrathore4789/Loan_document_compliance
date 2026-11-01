import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { ErrorBox, Loading, Notice, PageHeader, Stat, pct } from "../components/ui";

const COLORS = ["#1d4ed8", "#0e7490", "#7c3aed", "#b45309", "#be123c", "#4d7c0f", "#475569", "#0f766e", "#a21caf"];
const SEV = { HIGH: "#b91c1c", MEDIUM: "#d97706", LOW: "#64748b" };

export default function Dashboard() {
  const ov = useAsync(api.overview);
  const ex = useAsync(api.exceptionAnalytics);
  if (ov.loading || ex.loading) return <Loading />;
  if (ov.error || ex.error || !ov.data || !ex.data) return <ErrorBox message={ov.error ?? ex.error ?? "No data"} />;
  const o = ov.data, e = ex.data;
  const daily = o.applications_over_time.reduce<{ week: string; applications: number }[]>((acc, r) => {
    const d = new Date(r.date); d.setDate(d.getDate() - d.getDay());
    const k = d.toISOString().slice(0, 10);
    const last = acc.find((x) => x.week === k);
    if (last) last.applications += r.applications; else acc.push({ week: k, applications: r.applications });
    return acc;
  }, []).sort((a, b) => a.week.localeCompare(b.week));
  return (
    <>
      <PageHeader title="Overview" subtitle="Document processing and exception review across all applications" />
      <div className="mb-6"><Notice>{o.notice}</Notice></div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Applications" value={o.total_applications} hint={`${o.documents_total} documents, ${o.documents_processed} processed`} />
        <Stat label="Verification completion" value={pct(o.verification_completion_rate)} hint="Applications with a verification run" />
        <Stat label="Pending reviews" value={o.pending_reviews} hint="Unresolved exceptions" />
        <Stat label="High severity open" value={o.high_severity_open} tone={o.high_severity_open ? "danger" : "ok"} hint={`${o.resolved_exceptions} resolved so far`} />
      </div>
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <section className="card"><h2 className="mb-3 text-sm font-semibold">Applications per week</h2>
          <ResponsiveContainer width="100%" height={240}><LineChart data={daily}><CartesianGrid stroke="#e3e7ee" vertical={false} /><XAxis dataKey="week" tick={{ fontSize: 11 }} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} /><Tooltip />
            <Line dataKey="applications" stroke="#1d4ed8" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></section>
        <section className="card"><h2 className="mb-3 text-sm font-semibold">Exceptions by category and severity</h2>
          <ResponsiveContainer width="100%" height={240}><BarChart data={e.by_category} layout="vertical" margin={{ left: 40 }}><CartesianGrid stroke="#e3e7ee" horizontal={false} /><XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} /><YAxis type="category" dataKey="category" width={150} interval={0} tick={{ fontSize: 11 }} /><Tooltip /><Legend />
            {(["HIGH", "MEDIUM", "LOW"] as const).map((s) => <Bar key={s} dataKey={s} stackId="a" fill={SEV[s]} isAnimationActive={false} />)}</BarChart></ResponsiveContainer></section>
        <section className="card"><h2 className="mb-3 text-sm font-semibold">Documents by type</h2>
          <ResponsiveContainer width="100%" height={240}><PieChart><Pie data={o.documents_by_type} dataKey="documents" nameKey="category" innerRadius={50} outerRadius={85} paddingAngle={2} isAnimationActive={false}>
            {o.documents_by_type.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}</Pie><Tooltip /><Legend wrapperStyle={{ fontSize: 11 }} /></PieChart></ResponsiveContainer></section>
        <section className="card"><h2 className="mb-3 text-sm font-semibold">Application status</h2>
          <ResponsiveContainer width="100%" height={240}><BarChart data={o.verification_status}><CartesianGrid stroke="#e3e7ee" vertical={false} /><XAxis dataKey="status" tick={{ fontSize: 11 }} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} /><Tooltip />
            <Bar dataKey="count" fill="#1d4ed8" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></section>
        <section className="card lg:col-span-2"><h2 className="mb-3 text-sm font-semibold">Most frequent exceptions by rule</h2>
          <ResponsiveContainer width="100%" height={260}><BarChart data={e.by_rule.filter((r) => r.exceptions > 0).slice(0, 10)}><CartesianGrid stroke="#e3e7ee" vertical={false} /><XAxis dataKey="rule_id" tick={{ fontSize: 11 }} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v, _n, p) => [v as number, (p.payload as { rule_name: string }).rule_name]} /><Bar dataKey="exceptions" fill="#0e7490" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></section>
      </div>
    </>
  );
}
