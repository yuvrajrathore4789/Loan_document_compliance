import { ReactNode } from "react";

const sevStyle: Record<string, string> = {
  HIGH: "bg-red-50 text-red-700 ring-red-200", MEDIUM: "bg-amber-50 text-amber-800 ring-amber-200", LOW: "bg-slate-100 text-slate-700 ring-slate-200",
};
const statusStyle: Record<string, string> = {
  Verified: "bg-emerald-50 text-emerald-700 ring-emerald-200", RESOLVED: "bg-emerald-50 text-emerald-700 ring-emerald-200", PASS: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  "Exception Detected": "bg-red-50 text-red-700 ring-red-200", FAIL: "bg-red-50 text-red-700 ring-red-200", ESCALATED: "bg-red-50 text-red-700 ring-red-200",
  WARN: "bg-amber-50 text-amber-800 ring-amber-200", OPEN: "bg-amber-50 text-amber-800 ring-amber-200", REOPENED: "bg-amber-50 text-amber-800 ring-amber-200",
  IN_REVIEW: "bg-blue-50 text-blue-700 ring-blue-200", AWAITING_DOCUMENTS: "bg-violet-50 text-violet-700 ring-violet-200",
};
const pill = "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap";

export const SeverityBadge = ({ value }: { value: string }) => <span className={`${pill} ${sevStyle[value] ?? sevStyle.LOW}`}>{value}</span>;
export const StatusBadge = ({ value }: { value: string }) => (
  <span className={`${pill} ${statusStyle[value] ?? "bg-slate-100 text-slate-700 ring-slate-200"}`}>{value.replace(/_/g, " ")}</span>
);

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink-soft">{subtitle}</p>}
      </div>
      <div className="flex gap-2">{actions}</div>
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: "danger" | "ok" }) {
  return (
    <div className="card">
      <div className="text-xs font-medium uppercase tracking-wide text-ink-soft">{label}</div>
      <div className={`mt-2 text-3xl font-semibold tabular-nums ${tone === "danger" ? "text-red-700" : tone === "ok" ? "text-emerald-700" : ""}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-ink-soft">{hint}</div>}
    </div>
  );
}

export const Notice = ({ children }: { children: ReactNode }) => (
  <div className="rounded-md border border-blue-200 bg-brand-tint px-3 py-2 text-xs text-blue-900">{children}</div>
);
export const ErrorBox = ({ message }: { message: string }) => <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{message}</div>;
export const Loading = () => <div className="py-10 text-center text-sm text-ink-soft">Loading…</div>;
export const Empty = ({ children }: { children: ReactNode }) => <div className="py-10 text-center text-sm text-ink-soft">{children}</div>;

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-line">
        <thead><tr>{head.map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

export const fmtDate = (s: string | null) => (s ? new Date(s + (s.endsWith("Z") ? "" : "Z")).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—");
export const inr = (n: number | null | undefined) => (n == null ? "—" : new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(n));
export const pct = (n: number | null | undefined, d = 0) => (n == null ? "—" : `${(n * 100).toFixed(d)}%`);
