export type UserRole = "admin" | "direction" | "faculty";

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  researcher_id: string | null;
  permissions: string[];
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: UserProfile;
}

export interface SourceCitation {
  source_type: string;
  label: string;
  endpoint_or_filename: string;
  snapshot_id: string;
  version: string;
  content_hash: string;
  record_count: number;
  synced_at: string;
}

export interface ReportBundle {
  report_id: string;
  title: string;
  reproducibility_id: string;
  pdf_url: string;
  excel_url: string;
  pdf_size_bytes: number;
  excel_size_bytes: number;
}

export interface AnnualPoint {
  year: number;
  publications: number;
  scopus: number;
  wos: number;
  indexed_scopus_or_wos: number;
  q1: number;
  q2: number;
  q3: number;
  q4: number;
  citations: number;
  open_access: number;
}

export interface AnalyticsSummary {
  kpis: {
    publications: number;
    scopus: number;
    scopus_pct: number;
    wos: number;
    wos_pct: number;
    indexed_scopus_or_wos: number;
    indexed_pct: number;
    q1: number;
    q2: number;
    q3: number;
    q4: number;
    citations: number;
    avg_citations: number;
    open_access: number;
    open_access_pct: number;
    scoped_researchers_count: number;
  };
  annual_evolution: AnnualPoint[];
  top_researchers?: Array<{
    researcher_id: string;
    name: string;
    school_code: string | null;
    publications: number;
    scopus: number;
    wos: number;
    q1: number;
    citations: number;
  }>;
  year_comparison?: {
    year_a: number;
    year_b: number;
    deltas: Record<string, { year_a: number; year_b: number; delta: number; delta_pct: number }>;
  } | null;
  reproducibility_id: string;
}

export interface ChatResponse {
  conversation_id: string;
  message_id: string;
  answer: string;
  needs_clarification: boolean;
  plan: string[];
  tool_calls: Array<Record<string, unknown>>;
  sources: SourceCitation[];
  report_bundle: ReportBundle | null;
  analytics_summary: AnalyticsSummary | null;
}

export interface ConversationItem {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface MessageItem {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  sources_json: SourceCitation[];
  tool_calls_json: Array<Record<string, unknown>>;
  created_at: string;
  // Campos enriquecidos em memória durante a sessão ativa
  plan?: string[];
  report_bundle?: ReportBundle | null;
  analytics_summary?: AnalyticsSummary | null;
  needs_clarification?: boolean;
}

export interface SourceSnapshot {
  id: string;
  source_type: string;
  source_version: string | null;
  endpoint_or_filename: string;
  content_hash: string;
  record_count: number;
  records_created: number;
  records_updated: number;
  records_unchanged: number;
  records_removed: number;
  cache_ttl_minutes: number | null;
  forced_nocache: boolean;
  diff_summary: Record<string, unknown>;
  synced_at: string;
}

export interface ExcelPreviewResponse {
  filename: string;
  file_sha256: string;
  sheet_names: string[];
  selected_sheet: string;
  detected_headers: string[];
  column_mapping: Record<string, string>;
  inferred_types: Record<string, string>;
  total_rows: number;
  with_ciencia_vitae_id: number;
  distinct_ciencia_vitae_ids: number;
  duplicates: Array<{ field: string; value: string; rows: number[] }>;
  warnings: Array<{ row: number; code: string; message: string }>;
  errors: Array<{ row: number; code: string; message: string }>;
  unconfirmed_code_distributions: Record<string, Record<string, number>>;
  sample_rows: Array<Record<string, unknown>>;
}

export interface ExcelImportRecord {
  id: string;
  filename: string;
  file_sha256: string;
  sheet_names: string[];
  selected_sheet: string;
  total_rows: number;
  imported_rows: number;
  created_rows: number;
  updated_rows: number;
  duplicate_count: number;
  warning_count: number;
  error_count: number;
  status: string;
  imported_at: string;
}

export interface AuditLogItem {
  id: string;
  user_id: string | null;
  user_role: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  status: string;
  details: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}
