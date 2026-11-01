import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, tokenStore } from "../services/api";
import type { Role } from "../types";

interface Auth { user: { username: string; role: Role } | null; login: (u: string, p: string) => Promise<void>; logout: () => void }
const Ctx = createContext<Auth>(null as unknown as Auth);
export const useAuth = () => useContext(Ctx);

const USER_KEY = "lc_user";
function readUser() {
  try { const raw = sessionStorage.getItem(USER_KEY); return raw && tokenStore.get() ? (JSON.parse(raw) as { username: string; role: Role }) : null; } catch { return null; }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Auth["user"]>(readUser);
  const logout = useCallback(() => { tokenStore.clear(); try { sessionStorage.removeItem(USER_KEY); } catch { /* ignore */ } setUser(null); }, []);
  const login = useCallback(async (u: string, p: string) => {
    const r = await api.login(u, p);
    tokenStore.set(r.access_token);
    const next = { username: r.username, role: r.role as Role };
    try { sessionStorage.setItem(USER_KEY, JSON.stringify(next)); } catch { /* ignore */ }
    setUser(next);
  }, []);
  useEffect(() => { window.addEventListener("lc-unauthorized", logout); return () => window.removeEventListener("lc-unauthorized", logout); }, [logout]);
  const value = useMemo(() => ({ user, login, logout }), [user, login, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
