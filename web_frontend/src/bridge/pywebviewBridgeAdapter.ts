import type { AnalysisStatusDTO, ApiEnvelope, AppStateDTO, CaseHeaderDTO, CasePreflightDTO, CaseSelectionDTO, DesktopBridge, EvidenceDetailDTO, ModuleRegistryDTO, ModuleSummaryDTO, PagedModuleItemsDTO, SaveResultDTO, SourceReviewSummaryDTO } from "./contracts";
import type { ExportReportDTO, ManualContextDTO, ManualContextInput, ManualContextSaveDTO, RecentCasesDTO } from "./contracts";

type RawApi = Record<string, (...args: unknown[]) => Promise<unknown>>;
declare global { interface Window { pywebview?: { api?: RawApi } } }

function envelope<T>(raw: unknown): ApiEnvelope<T> {
  const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
  if (!parsed || typeof parsed !== "object" || !("ok" in parsed)) throw new Error("桌面 API 返回格式无效");
  return parsed as ApiEnvelope<T>;
}

export class PyWebviewBridgeAdapter implements DesktopBridge {
  private readonly api: RawApi;
  constructor(api: RawApi) { this.api = api; }
  private async call<T>(method: string, ...args: unknown[]): Promise<ApiEnvelope<T>> {
    const callable = this.api[method];
    if (!callable) throw new Error(`桌面 API 缺少方法：${method}`);
    return envelope<T>(await callable(...args));
  }
  getAppState = () => this.call<AppStateDTO>("get_app_state");
  selectStandardResult = () => this.call<CaseHeaderDTO>("select_standard_result");
  chooseCaseDirectory = () => this.call<CaseSelectionDTO>("choose_case_directory");
  inspectCaseDirectory = (handle: string) => this.call<CasePreflightDTO>("inspect_case_directory", handle);
  startCaseAnalysis = (handle: string, options: Record<string, never>) => this.call<AnalysisStatusDTO>("start_case_analysis", handle, options);
  getAnalysisStatus = (taskId: string) => this.call<AnalysisStatusDTO>("get_analysis_status", taskId);
  cancelAnalysis = (taskId: string) => this.call<AnalysisStatusDTO>("cancel_analysis", taskId);
  dismissAnalysisTask = (taskId: string) => this.call<null>("dismiss_analysis_task", taskId);
  saveCurrentStandardResult = () => this.call<SaveResultDTO>("save_current_standard_result");
  loadStandardResult = (path: string) => this.call<CaseHeaderDTO>("load_standard_result", path);
  getCaseHeader = () => this.call<CaseHeaderDTO>("get_case_header");
  getReviewModules = (id: string) => this.call<ModuleRegistryDTO>("get_review_modules", id);
  getModuleSummary = (moduleId: string, id: string) => this.call<ModuleSummaryDTO>("get_module_summary", moduleId, id);
  listModuleItems = (moduleId: string, page: number, pageSize: number, filters: Record<string, string>, sort: string, id: string) => this.call<PagedModuleItemsDTO>("list_module_items", moduleId, page, pageSize, filters, sort, id);
  listSourceReviews = (id: string) => this.call<SourceReviewSummaryDTO>("list_source_reviews", id);
  getEvidence = (transactionId: string, id: string) => this.call<EvidenceDetailDTO>("get_evidence", transactionId, id);
  closeCase = () => this.call<null>("close_case");
  listRecentCases = () => this.call<RecentCasesDTO>("list_recent_cases");
  openRecentCase = (recordId: string) => this.call<CaseHeaderDTO>("open_recent_case", recordId);
  removeRecentCase = (recordId: string) => this.call<{ removed: boolean }>("remove_recent_case", recordId);
  reanalyzeRecentCase = (recordId: string) => this.call<CaseSelectionDTO>("reanalyze_recent_case", recordId);
  getManualCaseContext = (caseHandle: string) => this.call<ManualContextDTO>("get_manual_case_context", caseHandle);
  saveManualCaseContext = (caseHandle: string, fields: ManualContextInput) => this.call<ManualContextSaveDTO>("save_manual_case_context", caseHandle, fields);
  getCurrentManualCaseContext = () => this.call<ManualContextDTO>("get_current_manual_case_context");
  saveCurrentManualCaseContext = (fields: ManualContextInput) => this.call<ManualContextSaveDTO>("save_current_manual_case_context", fields);
  clearCurrentManualCaseContext = () => this.call<ManualContextSaveDTO>("clear_current_manual_case_context");
  rebuildContextObservations = () => this.call<CaseHeaderDTO>("rebuild_context_observations");
  exportReport = () => this.call<ExportReportDTO>("export_report");
}

function waitForApi(timeoutMs = 5000): Promise<RawApi> {
  if (window.pywebview?.api) return Promise.resolve(window.pywebview.api);
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error("pywebview API unavailable")), timeoutMs);
    window.addEventListener("pywebviewready", () => {
      window.clearTimeout(timer);
      window.pywebview?.api ? resolve(window.pywebview.api) : reject(new Error("pywebview API unavailable"));
    }, { once: true });
  });
}

export async function connectDesktopBridge(): Promise<DesktopBridge> {
  return new PyWebviewBridgeAdapter(await waitForApi());
}
