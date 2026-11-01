import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { Empty, ErrorBox, Loading, PageHeader, SeverityBadge, StatusBadge, Table, fmtDate, inr } from "../components/ui";

export default function Applications() {
  const [q, setQ] = useState(""); const [status, setStatus] = useState("");
  const { data, loading, error } = useAsync(() => api.applications({ q: q || undefined, status: status || undefined }), [q, status]);
  return (
    <>
      <PageHeader title="Applications" subtitle="All loan applications (synthetic)" actions={<Link to="/upload" className="btn-primary">New application</Link>} />
      <div className="mb-4 flex flex-wrap gap-3">
        <input className="input max-w-xs" placeholder="Search name or ID" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search applications" />
        <select className="input max-w-[14rem]" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
          <option value="">All statuses</option>
          {["Draft", "Documents Uploaded", "Verification Pending", "Verified", "Exception Detected"].map((s) => <option key={s}>{s}</option>)}
        </select>
      </div>
      <div className="card p-0">
        {loading ? <Loading /> : error ? <div className="p-4"><ErrorBox message={error} /></div> : !data?.length ? <Empty>No applications match.</Empty> : (
          <Table head={["Application", "Applicant", "Type", "Loan amount", "Status", "Docs", "Open exceptions", "Created"]}>
            {data.map((a) => (
              <tr key={a.id} className="hover:bg-canvas">
                <td className="td font-mono text-xs"><Link className="text-brand hover:underline" to={`/applications/${a.id}`}>{a.id}</Link></td>
                <td className="td">{a.applicant_name}</td>
                <td className="td text-ink-soft">{a.application_type.replace("_", " ").toLowerCase()}</td>
                <td className="td tabular-nums">{inr(a.loan_amount)}</td>
                <td className="td"><StatusBadge value={a.status} /></td>
                <td className="td tabular-nums">{a.documents_count}</td>
                <td className="td">{a.open_exceptions ? <span className="flex items-center gap-2">{a.open_exceptions}{a.high_open_exceptions > 0 && <SeverityBadge value="HIGH" />}</span> : "—"}</td>
                <td className="td text-ink-soft">{fmtDate(a.created_at)}</td>
              </tr>
            ))}
          </Table>
        )}
      </div>
    </>
  );
}
