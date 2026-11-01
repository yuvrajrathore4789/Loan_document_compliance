export type Severity = "HIGH" | "MEDIUM" | "LOW";
export type Role = "admin" | "reviewer";
export type ExcStatus = "OPEN" | "IN_REVIEW" | "AWAITING_DOCUMENTS" | "ESCALATED" | "RESOLVED" | "REOPENED";

export interface Application {
  id: string; applicant_name: string; application_type: "SALARIED" | "SELF_EMPLOYED"; loan_amount: number | null;
  declared_monthly_income: number | null; status: string; is_synthetic: boolean; scenario_label: string | null;
  created_at: string; last_verified_at: string | null; documents_count: number; open_exceptions: number; high_open_exceptions: number;
}
export interface DocumentRec {
  id: string; application_id: string; original_filename: string; content_type: string; size_bytes: number; sha256: string;
  category: string; classification_confidence: number | null; status: string; page_count: number | null; text_method: string | null;
  ocr_confidence: number | null; extraction_method: string | null; warnings: string[] | null; processing_error: string | null;
  duplicate_of: string | null; uploaded_at: string; processed_at: string | null; processing_seconds: number | null;
}
export interface FieldRec { field_name: string; value: string | null; confidence: number | null; page_number: number | null; method: string; is_verified: boolean; verified_by: string | null }
export interface Extraction { document: DocumentRec; fields: FieldRec[]; transactions_count: number; notice: string }
export interface UploadResult { filename: string; accepted: boolean; document_id: string | null; category: string | null; status: string | null; error: string | null }
export interface VerificationResult {
  id: number; run_id: string; rule_id: string; rule_version: number; document_ids: string[] | null; field: string | null;
  expected: string | null; observed: string | null; outcome: "PASS" | "FAIL" | "WARN" | "SKIPPED"; severity: Severity; explanation: string; created_at: string;
}
export interface Verification {
  application_id: string; summary: { run_id: string | null; headline: string; counts: Record<string, number>; notice?: string; top_issues?: { rule_id: string; severity: Severity; explanation: string }[] };
  results: VerificationResult[]; ai_summary: string | null; ai_summary_notice: string | null;
}
export interface ExceptionRec {
  id: string; application_id: string; rule_id: string; category: string; severity: Severity; description: string; status: ExcStatus;
  assigned_reviewer: string | null; created_at: string; resolved_at: string | null;
}
export interface Review { id: number; reviewer: string; action: string; comment: string | null; created_at: string }
export interface ExceptionDetail extends ExceptionRec { evidence: Record<string, unknown> | null; reviews: Review[]; documents: DocumentRec[] }
export interface RuleRec {
  id: string; name: string; description: string | null; kind: string; severity: Severity; enabled: boolean; params: Record<string, unknown> | null;
  version: number; is_demo_rule: boolean; updated_by: string | null; updated_at: string;
}
export interface AuditEvent {
  event_id: string; actor: string; action: string; resource_type: string; resource_id: string;
  previous_state: Record<string, unknown> | null; new_state: Record<string, unknown> | null; details: Record<string, unknown> | null; created_at: string;
}
export interface Txn {
  id: number; document_id: string; txn_date: string; description: string | null; credit: number; debit: number; balance: number | null;
  is_salary_like: boolean; anomaly_score: number | null; robust_z: number | null; is_anomalous: boolean; anomaly_reasons: string[] | null;
}
export interface Transactions {
  application_id: string; total: number; flagged: number; detector_comparison: Record<string, number>;
  account_findings: { kind: string; message: string }[]; transactions: Txn[]; notice: string;
}
export interface Overview {
  total_applications: number; documents_total: number; documents_processed: number; verification_completion_rate: number;
  pending_reviews: number; high_severity_open: number; resolved_exceptions: number; avg_processing_seconds: number | null;
  applications_over_time: { date: string; applications: number }[]; verification_status: { status: string; count: number }[];
  documents_by_type: { category: string; documents: number; share_pct: number; avg_ocr_confidence: number | null; processing_failures: number }[];
  notice: string;
}
export interface ExceptionAnalytics {
  by_category: { category: string; HIGH: number; MEDIUM: number; LOW: number; total: number }[];
  by_rule: { rule_id: string; rule_name: string; rule_severity: Severity; exceptions: number; share_pct: number | null }[];
  resolved_vs_unresolved: { severity: Severity; resolved: number; unresolved: number; total: number }[];
  reviewer_workload: { reviewer: string; assigned_total: number; open_items: number; resolved_items: number; avg_resolution_seconds: number | null }[];
}
export interface AuditStats { total_events: number; by_action: { action: string; count: number }[]; by_actor: { actor: string; count: number }[]; notice: string }
