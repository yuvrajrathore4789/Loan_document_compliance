import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../hooks/AuthContext";

const nav = [
  { to: "/", label: "Overview", end: true }, { to: "/applications", label: "Applications" }, { to: "/upload", label: "New application" },
  { to: "/exceptions", label: "Exceptions" }, { to: "/audit", label: "Audit & compliance" }, { to: "/rules", label: "Rules" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="border-b border-line bg-white md:w-60 md:shrink-0 md:border-b-0 md:border-r">
        <div className="px-5 py-4">
          <div className="text-sm font-semibold leading-tight">Loan Document<br />Compliance Monitor</div>
          <div className="mt-1 text-xs text-ink-soft">Portfolio demo · synthetic data</div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:pb-0" aria-label="Main">
          {nav.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}
              className={({ isActive }) => `whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium ${isActive ? "bg-brand-tint text-brand" : "text-ink-soft hover:bg-canvas"}`}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="hidden px-5 pt-8 text-xs text-ink-soft md:block">
          Signed in as <b className="text-ink">{user?.username}</b> ({user?.role})
          <button onClick={logout} className="mt-2 block text-brand hover:underline">Sign out</button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 md:px-8">
        <div className="mb-4 flex justify-end md:hidden text-xs text-ink-soft">{user?.username} · <button onClick={logout} className="ml-1 text-brand">Sign out</button></div>
        <Outlet />
        <footer className="mt-10 border-t border-line pt-4 text-xs text-ink-soft">
          Synthetic demonstration data only. Automated checks are a pre-screen for human reviewers: this system never approves or rejects a loan,
          and its rules are demonstration rules, not legal or RBI compliance obligations.
        </footer>
      </main>
    </div>
  );
}
