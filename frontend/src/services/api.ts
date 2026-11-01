import axios, { AxiosError } from "axios";
import type {
  Application, AuditEvent, AuditStats, DocumentRec, ExceptionAnalytics, ExceptionDetail, ExceptionRec, Extraction, FieldRec, Overview,
  RuleRec, Transactions, UploadResult, Verification,
} from "../types";

const TOKEN_KEY = "lc_token";
export const tokenStore = {
  get: () => { try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set: (t: string) => { try { sessionStorage.setItem(TOKEN_KEY, t); } catch { /* storage unavailable */ } },
  clear: () => { try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ } },
};

export const http = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? "" });
http.interceptors.request.use((cfg) => {
  const t = tokenStore.get();
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});
http.interceptors.response.use((r) => r, (err: AxiosError) => {
  if (err.response?.status === 401 && !err.config?.url?.includes("/auth/login")) {
    tokenStore.clear();
    window.dispatchEvent(new Event("lc-unauthorized"));
  }
  return Promise.reject(err);
});

export function errorMessage(e: unknown): string {
  const ae = e as AxiosError<{ detail?: unknown }>;
  const d = ae.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x: { msg?: string }) => x.msg ?? "invalid input").join("; ");
  return ae.message || "Request failed";
}

const get = async <T,>(url: string, params?: object) => (await http.get<T>(url, { params })).data;

export const api = {
  login: async (username: string, password: string) => {
    const body = new URLSearchParams({ username, password });
    return (await http.post<{ access_token: string; role: string; username: string }>("/api/auth/login", body)).data;
  },
  reviewers: () => get<string[]>("/api/auth/reviewers"),
  overview: () => get<Overview>("/api/analytics/overview"),
  exceptionAnalytics: () => get<ExceptionAnalytics>("/api/analytics/exceptions"),
  auditStats: () => get<AuditStats>("/api/analytics/audit"),
  applications: (params?: { status?: string; q?: string }) => get<Application[]>("/api/applications", params),
  application: (id: string) => get<{ application: Application; documents: DocumentRec[] }>(`/api/applications/${id}`),
  createApplication: async (body: object) => (await http.post<Application>("/api/applications", body)).data,
  upload: async (id: string, files: File[], onProgress?: (pct: number) => void) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return (await http.post<{ application_id: string; results: UploadResult[] }>(`/api/applications/${id}/documents`, fd, {
      onUploadProgress: (e) => onProgress?.(e.total ? Math.round((e.loaded / e.total) * 100) : 0),
    })).data;
  },
  extraction: (docId: string) => get<Extraction>(`/api/documents/${docId}/extraction`),
  correctField: async (docId: string, field: string, value: string | null, reason: string) =>
    (await http.put<FieldRec>(`/api/documents/${docId}/fields/${field}`, { value, reason })).data,
  verify: async (id: string) => (await http.post<Verification>(`/api/applications/${id}/verify`)).data,
  verification: (id: string) => get<Verification>(`/api/applications/${id}/verification`),
  transactions: (id: string, onlyAnomalous = false) => get<Transactions>(`/api/applications/${id}/transactions`, { only_anomalous: onlyAnomalous }),
  exceptions: (params?: object) => get<ExceptionRec[]>("/api/exceptions", params),
  exception: (id: string) => get<ExceptionDetail>(`/api/exceptions/${id}`),
  setStatus: async (id: string, status: string, comment?: string) => (await http.patch<ExceptionRec>(`/api/exceptions/${id}/status`, { status, comment })).data,
  comment: async (id: string, comment: string) => (await http.post(`/api/exceptions/${id}/comments`, { comment })).data,
  assign: async (id: string, reviewer: string | null) => (await http.post<ExceptionRec>(`/api/exceptions/${id}/assign`, { reviewer })).data,
  rules: () => get<RuleRec[]>("/api/rules"),
  rulesNotice: () => get<{ notice: string }>("/api/rules/notice"),
  createRule: async (body: object) => (await http.post<RuleRec>("/api/rules", body)).data,
  patchRule: async (id: string, body: object) => (await http.patch<RuleRec>(`/api/rules/${id}`, body)).data,
  ruleHistory: (id: string) => get<AuditEvent[]>(`/api/rules/${id}/history`),
  audit: (params?: object) => get<AuditEvent[]>("/api/audit", params),
  auditCsv: async (params?: object) => (await http.get<string>("/api/audit/export.csv", { params, responseType: "text" })).data,
  documentBlobUrl: async (docId: string) => URL.createObjectURL((await http.get<Blob>(`/api/documents/${docId}/file`, { responseType: "blob" })).data),
};
