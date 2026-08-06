export type ApiEnvelope<T> = {
  ok: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
  meta: { request_id?: string; elapsed_ms: number; payload_bytes?: number };
};

export type AppStateDTO = {
  frontend_ready: boolean;
  case_loaded: boolean;
  loading: boolean;
  mode: string;
  api_version: string;
  frontend_version: string;
  schema_versions_supported: string[];
  renderer: string;
  capabilities: string[];
  case_session_id: string | null;
  case_revision: number;
};

export type SourceReviewDTO = { source_name: string; reason: string };
export type SourceReviewItemDTO = { source_id: string; display_name: string; source_type: string; status: string; review_reason: string; parser_name: string | null; generated_transactions: boolean };
export type SourceReviewSummaryDTO = { case_session_id: string; total: number; items: SourceReviewItemDTO[] };
export type CaseHeaderDTO = { case_name: string; period_start: string; period_end: string; source_count: number; transaction_count: number; analysis_status: string; evidence_status: string; schema_version: string; case_session_id: string; case_revision: number; review_source_count: number; review_sources: SourceReviewDTO[] };
export type FilterOptionDTO = { value: string; label: string };
export type FilterDefinitionDTO = { key: string; label: string; kind: "select" | "text" | "date"; options: FilterOptionDTO[] };
export type ModuleAvailability = "available" | "empty" | "not_implemented" | "unavailable";
export type ModuleDescriptorDTO = { module_id: string; title: string; icon: string; availability: ModuleAvailability; display_kind: "transaction_list" | "summary" | "disabled"; total_count: number; review_count: number; status: string; description: string; supported_filters: FilterDefinitionDTO[]; evidence_supported: boolean };
export type ModuleRegistryDTO = { case_session_id: string; modules: ModuleDescriptorDTO[] };
export type ModuleSummaryDTO = { module_id: string; title: string; total_count: number; review_count: number; status: string; description: string; boundary_note: string; category_counts: Record<string, number>; source_count: number; case_session_id: string };
export type ReviewItemDTO = { item_id: string; transaction_id: string | null; date: string | null; direction: string | null; amount: string | null; primary_text: string; secondary_text: string | null; counterparty: string | null; matched_text: string | null; interpretation: string | null; category: string | null; review_status: string | null; source_name: string | null; evidence_available: boolean };
export type PagedModuleItemsDTO = { module_id: string; case_session_id: string; page: number; page_size: number; total: number; total_pages: number; items: ReviewItemDTO[]; available_filters: FilterDefinitionDTO[]; meta: { query_elapsed_ms?: number; sort?: string } };
export type EvidenceDetailDTO = { transaction_id: string; transaction_id_short: string; date: string; direction: string; amount: string; counterparty: string; summary: string; purpose: string; source_name: string; page_no: number; row_no: number; evidence_locator: string; reference_reason: string; integrity_status: string; masked_original_fields: string[]; full_original_fields: string[]; case_session_id: string };
export type CaseSelectionDTO = { case_handle: string; case_display_name: string };
export type PreflightSourceDTO = { source_ref: string; display_name: string; extension: string; detected_source_type: string; detected_bank_type: string; supported: boolean; initial_status: string; warning: string; size: number; may_use_generic_fallback: boolean };
export type CasePreflightDTO = { case_handle: string; case_display_name: string; source_count: number; supported_source_count: number; unsupported_source_count: number; sources: PreflightSourceDTO[]; warnings: string[]; can_start: boolean; elapsed_ms: number };
export type AnalysisSourceStatusDTO = { source_ref: string; display_name: string; source_type: string; status: string; transaction_count: number; message: string };
export type AnalysisState = "running" | "cancelling" | "completed" | "failed" | "cancelled";
export type AnalysisStatusDTO = { analysis_task_id: string; state: AnalysisState; case_display_name: string; current_stage: string; current_source_name: string; completed_sources: number; total_sources: number; success_sources: number; review_sources: number; failed_sources: number; warning_count: number; started_at: string; elapsed_ms: number; cancellation_requested: boolean; error_code: string | null; error_message: string | null; result_ready: boolean; sources: AnalysisSourceStatusDTO[]; case_session_id: string | null; case_revision: number | null; transaction_count: number; result_build_ms: number | null; result_bind_ms: number | null; diagnostic_id: string | null };
export type SaveResultDTO = { saved: boolean; display_name: string };
export type RecentCaseDTO = { record_id: string; case_name: string; updated_at: string; period_start: string; period_end: string; source_count: number; transaction_count: number; analysis_status: string; schema_version: string; available: boolean };
export type RecentCasesDTO = { cases: RecentCaseDTO[]; corrupt_index: boolean };
export type ManualContextDTO = { case_name: string; saved: boolean; has_file: boolean; company_name: string; declared_work_description: string; declared_work_status: string; work_units: string[]; work_locations: string[]; residence_locations: string[]; source_names: string[]; confirmed_primary_business: string; confirmed_products_or_services: string; confirmation_note: string; confirmation_status: string; enable_ai_business_analysis: boolean };
export type ManualContextSaveDTO = { saved: boolean; case_name: string; confirmation_status: string };
export type ExportReportDTO = { saved: boolean; display_name: string };
export type ManualContextInput = { company_name: string; confirmed_primary_business: string; confirmed_products_or_services: string; confirmation_note: string; confirmation_status: string };

export interface DesktopBridge {
  getAppState(): Promise<ApiEnvelope<AppStateDTO>>;
  selectStandardResult(): Promise<ApiEnvelope<CaseHeaderDTO>>;
  chooseCaseDirectory(): Promise<ApiEnvelope<CaseSelectionDTO>>;
  inspectCaseDirectory(caseHandle: string): Promise<ApiEnvelope<CasePreflightDTO>>;
  startCaseAnalysis(caseHandle: string, options: Record<string, never>): Promise<ApiEnvelope<AnalysisStatusDTO>>;
  getAnalysisStatus(taskId: string): Promise<ApiEnvelope<AnalysisStatusDTO>>;
  cancelAnalysis(taskId: string): Promise<ApiEnvelope<AnalysisStatusDTO>>;
  dismissAnalysisTask(taskId: string): Promise<ApiEnvelope<null>>;
  saveCurrentStandardResult(): Promise<ApiEnvelope<SaveResultDTO>>;
  loadStandardResult(path: string): Promise<ApiEnvelope<CaseHeaderDTO>>;
  getCaseHeader(): Promise<ApiEnvelope<CaseHeaderDTO>>;
  getReviewModules(caseSessionId: string): Promise<ApiEnvelope<ModuleRegistryDTO>>;
  getModuleSummary(moduleId: string, caseSessionId: string): Promise<ApiEnvelope<ModuleSummaryDTO>>;
  listModuleItems(moduleId: string, page: number, pageSize: number, filters: Record<string, string>, sort: string, caseSessionId: string): Promise<ApiEnvelope<PagedModuleItemsDTO>>;
  listSourceReviews(caseSessionId: string): Promise<ApiEnvelope<SourceReviewSummaryDTO>>;
  getEvidence(transactionId: string, caseSessionId: string): Promise<ApiEnvelope<EvidenceDetailDTO>>;
  closeCase(): Promise<ApiEnvelope<null>>;
  listRecentCases(): Promise<ApiEnvelope<RecentCasesDTO>>;
  openRecentCase(recordId: string): Promise<ApiEnvelope<CaseHeaderDTO>>;
  removeRecentCase(recordId: string): Promise<ApiEnvelope<{ removed: boolean }>>;
  getManualCaseContext(caseHandle: string): Promise<ApiEnvelope<ManualContextDTO>>;
  saveManualCaseContext(caseHandle: string, fields: ManualContextInput): Promise<ApiEnvelope<ManualContextSaveDTO>>;
  rebuildContextObservations(): Promise<ApiEnvelope<CaseHeaderDTO>>;
  exportReport(): Promise<ApiEnvelope<ExportReportDTO>>;
}
