import { FormEvent, useState } from "react";
import { useAuth } from "../hooks/AuthContext";
import { errorMessage } from "../services/api";
import { ErrorBox } from "../components/ui";

export default function Login() {
  const { login } = useAuth();
  const [u, setU] = useState(""); const [p, setP] = useState(""); const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try { await login(u, p); } catch (x) { setErr(errorMessage(x)); } finally { setBusy(false); }
  };
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4">
        <div>
          <h1 className="text-xl font-semibold">Loan Compliance Monitor</h1>
          <p className="mt-1 text-xs text-ink-soft">Portfolio demo using synthetic documents only. Demo credentials are listed in the README.</p>
        </div>
        {err && <ErrorBox message={err} />}
        <label className="block text-sm">Username<input className="input mt-1" value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" required /></label>
        <label className="block text-sm">Password<input className="input mt-1" type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" required /></label>
        <button className="btn-primary w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}
