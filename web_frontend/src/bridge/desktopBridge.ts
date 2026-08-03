export type ReviewStatus = "direct" | "review";
export type ApiEnvelope<T> = {
  ok: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
  meta: { request_id?: string; elapsed_ms: number; payload_bytes?: number };
};
export type AppStateDTO = { frontend_ready: boolean; case_loaded: boolean; loading: boolean; mode: string };
export type SourceReviewDTO = { source_name: string; reason: string };
export type CaseHeaderDTO = { case_name: string; period_start: string; period_end: string; source_count: number; transaction_count: number; analysis_status: string; evidence_status: string; schema_version: string; review_source_count: number; review_sources: SourceReviewDTO[] };
export type PurchaseSummaryDTO = { total_count: number; direct_count: number; deposit_count: number; prior_income_count: number; review_count: number; category_counts: Record<string, number>; boundary_note: string };
export type PurchaseFilters = { status: string };
export type TransactionDTO = { transaction_id: string; date: string; direction: string; amount: string; counterparty: string; matched_text: string; interpretation: string; source_name: string; category: string; review_status: ReviewStatus };
export type PagedTransactionsDTO = { items: TransactionDTO[]; page: number; page_size: number; total: number; total_pages: number; query_elapsed_ms: number; payload_bytes: number };
export type EvidenceDetailDTO = { transaction_id: string; transaction_id_short: string; date: string; direction: string; amount: string; counterparty: string; summary: string; purpose: string; source_name: string; page_no: number; row_no: number; evidence_locator: string; reference_reason: string; integrity_status: string; masked_original_fields: string[]; full_original_fields: string[] };

export interface DesktopBridge {
  getAppState(): Promise<ApiEnvelope<AppStateDTO>>;
  selectStandardResult(): Promise<ApiEnvelope<CaseHeaderDTO>>;
  loadStandardResult(path: string): Promise<ApiEnvelope<CaseHeaderDTO>>;
  getCaseHeader(): Promise<ApiEnvelope<CaseHeaderDTO>>;
  getPurchaseSummary(): Promise<ApiEnvelope<PurchaseSummaryDTO>>;
  listPurchaseTransactions(page: number, pageSize: number, filters: PurchaseFilters): Promise<ApiEnvelope<PagedTransactionsDTO>>;
  getEvidence(transactionId: string): Promise<ApiEnvelope<EvidenceDetailDTO>>;
  closeCase(): Promise<ApiEnvelope<null>>;
}

type RawApi = Record<string, (...args: unknown[]) => Promise<unknown>>;
type QWebChannelObject = Record<string, (...args: unknown[]) => void>;

declare global {
  interface Window {
    pywebview?: { api?: RawApi };
    qt?: { webChannelTransport: unknown };
    QWebChannel?: new (transport: unknown, callback: (channel: { objects: { bankflowBridge: QWebChannelObject } }) => void) => void;
  }
}

function envelope<T>(raw: unknown): ApiEnvelope<T> {
  const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
  if (!parsed || typeof parsed !== "object" || !("ok" in parsed)) throw new Error("Invalid desktop API envelope");
  return parsed as ApiEnvelope<T>;
}

export class PyWebviewBridgeAdapter implements DesktopBridge {
  constructor(private readonly api: RawApi) {}

  private async call<T>(method: string, ...args: unknown[]): Promise<ApiEnvelope<T>> {
    const callable = this.api[method];
    if (!callable) throw new Error(`Desktop API method missing: ${method}`);
    return envelope<T>(await callable(...args));
  }

  getAppState() { return this.call<AppStateDTO>("get_app_state"); }
  selectStandardResult() { return this.call<CaseHeaderDTO>("select_standard_result"); }
  loadStandardResult(path: string) { return this.call<CaseHeaderDTO>("load_standard_result", path); }
  getCaseHeader() { return this.call<CaseHeaderDTO>("get_case_header"); }
  getPurchaseSummary() { return this.call<PurchaseSummaryDTO>("get_purchase_summary"); }
  listPurchaseTransactions(page: number, pageSize: number, filters: PurchaseFilters) {
    return this.call<PagedTransactionsDTO>("list_purchase_transactions", page, pageSize, filters);
  }
  getEvidence(transactionId: string) { return this.call<EvidenceDetailDTO>("get_evidence", transactionId); }
  closeCase() { return this.call<null>("close_case"); }
}

export class QWebChannelAdapter implements DesktopBridge {
  constructor(private readonly bridge: QWebChannelObject) {}

  private call<T>(method: string, ...args: unknown[]): Promise<ApiEnvelope<T>> {
    return new Promise((resolve, reject) => {
      const callable = this.bridge[method];
      if (!callable) return reject(new Error(`QWebChannel method missing: ${method}`));
      callable(...args, (raw: unknown) => {
        try { resolve(envelope<T>(raw)); } catch (error) { reject(error); }
      });
    });
  }

  getAppState() { return this.call<AppStateDTO>("frontend_ready_event"); }
  selectStandardResult() { return this.call<CaseHeaderDTO>("select_standard_result"); }
  loadStandardResult(path: string) { return this.call<CaseHeaderDTO>("load_standard_result", path); }
  getCaseHeader() { return this.call<CaseHeaderDTO>("get_case_header"); }
  getPurchaseSummary() { return this.call<PurchaseSummaryDTO>("get_purchase_summary"); }
  listPurchaseTransactions(page: number, pageSize: number, filters: PurchaseFilters) {
    return this.call<PagedTransactionsDTO>("list_purchase_transactions", page, pageSize, JSON.stringify(filters));
  }
  getEvidence(transactionId: string) { return this.call<EvidenceDetailDTO>("get_evidence", transactionId); }
  closeCase() { return this.call<null>("close_case"); }
}

function waitForPywebviewApi(timeoutMs = 4000): Promise<RawApi> {
  if (window.pywebview?.api) return Promise.resolve(window.pywebview.api);
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error("pywebview API unavailable")), timeoutMs);
    window.addEventListener("pywebviewready", () => {
      window.clearTimeout(timer);
      if (window.pywebview?.api) resolve(window.pywebview.api);
      else reject(new Error("pywebview API unavailable"));
    }, { once: true });
  });
}

function loadQWebChannelScript(): Promise<void> {
  if (window.QWebChannel) return Promise.resolve();
  if (!window.qt?.webChannelTransport) return Promise.reject(new Error("QWebChannel transport unavailable"));
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "qrc:///qtwebchannel/qwebchannel.js";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("QWebChannel script failed"));
    document.head.appendChild(script);
  });
}

async function connectQWebChannel(): Promise<DesktopBridge> {
  await loadQWebChannelScript();
  return new Promise((resolve, reject) => {
    if (!window.qt?.webChannelTransport || !window.QWebChannel) return reject(new Error("QWebChannel unavailable"));
    new window.QWebChannel(window.qt.webChannelTransport, (channel) => resolve(new QWebChannelAdapter(channel.objects.bankflowBridge)));
  });
}

export async function connectDesktopBridge(): Promise<DesktopBridge> {
  if (new URLSearchParams(window.location.search).get("bridge") === "qwebchannel") return connectQWebChannel();
  return new PyWebviewBridgeAdapter(await waitForPywebviewApi());
}
