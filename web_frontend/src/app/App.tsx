import { useCallback, useEffect, useMemo, useRef, useState, type WheelEvent as ReactWheelEvent } from "react";
import {
  Archive, BriefcaseBusiness, Car, CarFront, ChevronLeft, ChevronRight,
  CircleHelp, ClipboardCheck, Command, FileJson, FolderOpen, Landmark,
  FileText, FolderPlus, History, LoaderCircle, MapPin, Moon, RefreshCw, Save,
  Search, ShieldAlert, SlidersHorizontal, StopCircle, Sun, WalletCards, X, type LucideIcon,
} from "lucide-react";
import { connectDesktopBridge } from "../bridge/desktopBridge";
import type {
  AnalysisStatusDTO, AppStateDTO, CaseHeaderDTO, CasePreflightDTO, DesktopBridge,
  EvidenceDetailDTO, ManualContextDTO, ManualContextInput, ModuleDescriptorDTO, ModuleSummaryDTO,
  PagedModuleItemsDTO, RecentCaseDTO, ReviewItemDTO, SourceReviewSummaryDTO,
} from "../bridge/contracts";
import { IconButton } from "../components/IconButton";
import { canChangePage, clearedCaseState, isAnalysisActive, isCompatibleApiVersion, isCurrentAnalysis, isCurrentCase, isModuleEnabled, nextTheme, shouldShowSourceReview } from "./requestGuard";

type Theme = "dark" | "light";
type Connection = "connecting" | "ready" | "disconnected";

const ICONS: Record<string, LucideIcon> = {
  "car-front": CarFront, "shield-alert": ShieldAlert, "briefcase-business": BriefcaseBusiness,
  landmark: Landmark, "clipboard-check": ClipboardCheck, "circle-help": CircleHelp,
  car: Car, "map-pin": MapPin, "wallet-cards": WalletCards,
};
const EMPTY_PAGE: PagedModuleItemsDTO = { module_id: "", case_session_id: "", page: 1, page_size: 50, total: 0, total_pages: 1, items: [], available_filters: [], meta: {} };

export function App() {
  const [theme, setTheme] = useState<Theme>("dark");
  const [connection, setConnection] = useState<Connection>("connecting");
  const [bridge, setBridge] = useState<DesktopBridge | null>(null);
  const [appState, setAppState] = useState<AppStateDTO | null>(null);
  const [header, setHeader] = useState<CaseHeaderDTO | null>(null);
  const [modules, setModules] = useState<ModuleDescriptorDTO[]>([]);
  const [activeModule, setActiveModule] = useState<ModuleDescriptorDTO | null>(null);
  const [summary, setSummary] = useState<ModuleSummaryDTO | null>(null);
  const [pageData, setPageData] = useState<PagedModuleItemsDTO>(EMPTY_PAGE);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [filterDraft, setFilterDraft] = useState<Record<string, string>>({});
  const [pageSize, setPageSize] = useState(50);
  const [selectedId, setSelectedId] = useState("");
  const [evidence, setEvidence] = useState<EvidenceDetailDTO | null>(null);
  const [evidenceError, setEvidenceError] = useState("");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [fullEvidence, setFullEvidence] = useState(false);
  const [sourceReview, setSourceReview] = useState<SourceReviewSummaryDTO | null>(null);
  const [sourceReviewOpen, setSourceReviewOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [commandOpen, setCommandOpen] = useState(false);
  const [preflight, setPreflight] = useState<CasePreflightDTO | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisStatusDTO | null>(null);
  const [completion, setCompletion] = useState<{ sources: number; transactions: number; reviews: number } | null>(null);
  const [notice, setNotice] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [recentCases, setRecentCases] = useState<RecentCaseDTO[]>([]);
  const [recentCorrupt, setRecentCorrupt] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [contextDraft, setContextDraft] = useState<ManualContextInput>({
    company_name: "", confirmed_primary_business: "", confirmed_products_or_services: "",
    confirmation_note: "", confirmation_status: "unconfirmed",
  });
  const [contextExtract, setContextExtract] = useState<ManualContextDTO | null>(null);
  const [contextNotice, setContextNotice] = useState("");
  const sessionRef = useRef<string | null>(null);
  const analysisTaskRef = useRef<string | null>(null);
  const requestRef = useRef(0);
  const commandInput = useRef<HTMLInputElement>(null);

  const clearCaseUi = useCallback(() => {
    const cleared = clearedCaseState();
    setModules([]); setActiveModule(null); setSummary(null); setPageData(EMPTY_PAGE);
    setFilters(cleared.filters); setFilterDraft(cleared.filters); setSelectedId(cleared.selectedId);
    setEvidence(null); setEvidenceError(""); setInspectorOpen(cleared.inspectorOpen);
    setSourceReview(null); setSourceReviewOpen(cleared.sourceReviewOpen);
  }, []);

  const loadModule = useCallback(async (
    activeBridge: DesktopBridge,
    descriptor: ModuleDescriptorDTO,
    sessionId: string,
    page = 1,
    nextFilters: Record<string, string> = {},
    nextPageSize = 50,
  ) => {
    if (!isModuleEnabled(descriptor.availability)) return;
    const token = ++requestRef.current;
    setLoading(true); setError(""); setActiveModule(descriptor); setSelectedId("");
    setEvidence(null); setEvidenceError(""); setInspectorOpen(false);
    const [summaryResponse, pageResponse] = await Promise.all([
      activeBridge.getModuleSummary(descriptor.module_id, sessionId),
      activeBridge.listModuleItems(descriptor.module_id, page, nextPageSize, nextFilters, "default", sessionId),
    ]);
    if (token !== requestRef.current || sessionRef.current !== sessionId) return;
    if (!summaryResponse.ok || !pageResponse.ok || !summaryResponse.data || !pageResponse.data) {
      setError(summaryResponse.error?.message || pageResponse.error?.message || "读取模块失败"); setLoading(false); return;
    }
    if (!isCurrentCase(sessionId, summaryResponse.data.case_session_id) || !isCurrentCase(sessionId, pageResponse.data.case_session_id)) return;
    setSummary(summaryResponse.data); setPageData(pageResponse.data); setFilters(nextFilters); setFilterDraft(nextFilters);
    setPageSize(nextPageSize); setLoading(false);
  }, []);

  const activateCase = useCallback(async (activeBridge: DesktopBridge, caseHeader: CaseHeaderDTO) => {
    const sessionId = caseHeader.case_session_id;
    ++requestRef.current; sessionRef.current = sessionId; clearCaseUi(); setHeader(caseHeader); setLoading(true); setError("");
    const registry = await activeBridge.getReviewModules(sessionId);
    if (sessionRef.current !== sessionId || !registry.ok || !registry.data || !isCurrentCase(sessionId, registry.data.case_session_id)) {
      if (sessionRef.current === sessionId) { setError(registry.error?.message || "读取模块目录失败"); setLoading(false); }
      return;
    }
    setModules(registry.data.modules);
    const first = registry.data.modules.find((item) => item.availability === "available") || registry.data.modules.find((item) => item.availability === "empty");
    if (first) await loadModule(activeBridge, first, sessionId);
    else setLoading(false);
  }, [clearCaseUi, loadModule]);

  useEffect(() => {
    connectDesktopBridge().then(async (activeBridge) => {
      setBridge(activeBridge); setConnection("ready");
      const state = await activeBridge.getAppState();
      if (!state.ok || !state.data) { setError(state.error?.message || "无法读取应用状态"); return; }
      setAppState(state.data);
      if (!isCompatibleApiVersion(state.data.api_version)) { setError("前后端 API 版本不兼容，请更新程序后重试。"); return; }
      if (state.data.case_loaded) {
        const response = await activeBridge.getCaseHeader();
        if (response.ok && response.data) await activateCase(activeBridge, response.data);
      }
    }).catch(() => setConnection("disconnected"));
  }, [activateCase]);

  const openResult = async () => {
    if (!bridge || loading) return;
    setLoading(true); setError(""); setCommandOpen(false); ++requestRef.current;
    const response = await bridge.selectStandardResult();
    if (!response.ok || !response.data) {
      if (response.error?.code !== "CANCELLED") setError(response.error?.message || "加载失败");
      setLoading(false); return;
    }
    setAppState((current) => current ? { ...current, case_loaded: true, case_session_id: response.data!.case_session_id, case_revision: response.data!.case_revision } : current);
    setPreflight(null); setAnalysis(null); setHistoryOpen(false); analysisTaskRef.current = null;
    setContextDraft({ company_name: "", confirmed_primary_business: "", confirmed_products_or_services: "", confirmation_note: "", confirmation_status: "unconfirmed" });
    setContextExtract(null);
    setContextNotice("");
    await activateCase(bridge, response.data);
  };

  const chooseNewCase = async () => {
    if (!bridge || loading || isAnalysisActive(analysis?.state)) return;
    setLoading(true); setError(""); setNotice(""); setCommandOpen(false);
    const selected = await bridge.chooseCaseDirectory();
    if (!selected.ok || !selected.data) {
      if (selected.error?.code !== "CANCELLED") setError(selected.error?.message || "选择案件目录失败");
      setLoading(false); return;
    }
    const inspected = await bridge.inspectCaseDirectory(selected.data.case_handle);
    if (!inspected.ok || !inspected.data) {
      setError(inspected.error?.message || "来源预检失败"); setLoading(false); return;
    }
    setPreflight(inspected.data); setAnalysis(null); setHistoryOpen(false); analysisTaskRef.current = null; setLoading(false);
    setContextDraft({ company_name: "", confirmed_primary_business: "", confirmed_products_or_services: "", confirmation_note: "", confirmation_status: "unconfirmed" });
    setContextExtract(null);
    setContextNotice("");
    const contextResponse = await bridge.getManualCaseContext(selected.data.case_handle);
    if (contextResponse.ok && contextResponse.data) {
      setContextExtract(contextResponse.data);
      setContextDraft({
        company_name: contextResponse.data.company_name,
        confirmed_primary_business: contextResponse.data.confirmed_primary_business,
        confirmed_products_or_services: contextResponse.data.confirmed_products_or_services,
        confirmation_note: contextResponse.data.confirmation_note,
        confirmation_status: contextResponse.data.confirmation_status,
      });
    }
  };

  const startAnalysis = async () => {
    if (!bridge || !preflight?.can_start || isAnalysisActive(analysis?.state)) return;
    setError(""); setNotice(""); setLoading(true);
    const response = await bridge.startCaseAnalysis(preflight.case_handle, {});
    setLoading(false);
    if (!response.ok || !response.data) { setError(response.error?.message || "无法开始分析"); return; }
    analysisTaskRef.current = response.data.analysis_task_id;
    setAnalysis(response.data);
  };

  const cancelAnalysis = async () => {
    if (!bridge || !analysisTaskRef.current || !analysis || !isAnalysisActive(analysis.state)) return;
    const response = await bridge.cancelAnalysis(analysisTaskRef.current);
    if (response.ok && response.data && isCurrentAnalysis(analysisTaskRef.current, response.data.analysis_task_id)) setAnalysis(response.data);
    else if (!response.ok) setError(response.error?.message || "无法请求停止分析");
  };

  const saveResult = async () => {
    if (!bridge || !header) return;
    const response = await bridge.saveCurrentStandardResult();
    if (response.ok && response.data) setNotice(`已保存：${response.data.display_name}`);
    else if (response.error?.code !== "CANCELLED") setError(response.error?.message || "保存标准结果失败");
  };

  const openHistory = async () => {
    if (!bridge) return;
    setError(""); setHistoryLoading(true); setHistoryOpen(true);
    setRecentCases([]); setRecentCorrupt(false);
    const response = await bridge.listRecentCases();
    setHistoryLoading(false);
    if (!response.ok || !response.data) { setError(response.error?.message || "读取历史案件失败"); return; }
    setRecentCases(response.data.cases); setRecentCorrupt(response.data.corrupt_index);
  };

  const openRecentCase = async (recordId: string) => {
    if (!bridge || historyLoading) return;
    setHistoryLoading(true); setError("");
    const response = await bridge.openRecentCase(recordId);
    setHistoryLoading(false);
    if (!response.ok || !response.data) { setError(response.error?.message || "打开历史案件失败"); return; }
    setHistoryOpen(false); setPreflight(null); setAnalysis(null); analysisTaskRef.current = null;
    setContextDraft({ company_name: "", confirmed_primary_business: "", confirmed_products_or_services: "", confirmation_note: "", confirmation_status: "unconfirmed" });
    setContextExtract(null);
    setContextNotice("");
    setAppState((current) => current ? { ...current, case_loaded: true, case_session_id: response.data!.case_session_id, case_revision: response.data!.case_revision } : current);
    await activateCase(bridge, response.data);
  };

  const removeRecentCase = async (recordId: string) => {
    if (!bridge) return;
    const response = await bridge.removeRecentCase(recordId);
    if (response.ok) setRecentCases((items) => items.filter((item) => item.record_id !== recordId));
    else setError(response.error?.message || "删除历史案件失败");
  };

  const saveContext = async () => {
    if (!bridge || !preflight) return;
    setLoading(true); setError(""); setContextNotice("");
    const response = await bridge.saveManualCaseContext(preflight.case_handle, contextDraft);
    setLoading(false);
    if (!response.ok || !response.data) { setError(response.error?.message || "保存经营上下文失败"); return; }
    setContextNotice("经营上下文已保存，开始分析时会自动使用");
  };

  const rebuildContext = async () => {
    if (!bridge) return;
    setLoading(true); setError(""); setNotice("");
    const response = await bridge.rebuildContextObservations();
    setLoading(false);
    if (!response.ok || !response.data) { setError(response.error?.message || "重新构建经营上下文失败"); return; }
    setNotice("经营上下文观察已重新构建");
    await activateCase(bridge, response.data);
  };

  const exportReport = async () => {
    if (!bridge) return;
    setLoading(true); setError(""); setNotice("");
    const response = await bridge.exportReport();
    setLoading(false);
    if (!response.ok || !response.data) {
      if (response.error?.code !== "CANCELLED") setError(response.error?.message || "导出报告失败");
      return;
    }
    setNotice(`报告已导出：${response.data.display_name}`);
  };

  const leaveAnalysis = async () => {
    if (bridge && analysis && !isAnalysisActive(analysis.state)) await bridge.dismissAnalysisTask(analysis.analysis_task_id);
    analysisTaskRef.current = null; setAnalysis(null); setError("");
  };

  useEffect(() => {
    if (!bridge || !analysis || !isAnalysisActive(analysis.state)) return;
    const taskId = analysis.analysis_task_id;
    let stopped = false;
    const poll = async () => {
      const response = await bridge.getAnalysisStatus(taskId);
      if (stopped || !analysisTaskRef.current || !response.ok || !response.data || !isCurrentAnalysis(analysisTaskRef.current, response.data.analysis_task_id)) return;
      if (response.data.state === "completed" && response.data.result_ready) {
        analysisTaskRef.current = null;
        const headerResponse = await bridge.getCaseHeader();
        if (!headerResponse.ok || !headerResponse.data || headerResponse.data.case_session_id !== response.data.case_session_id) {
          setError(headerResponse.error?.message || "分析结果已生成，但工作台加载失败");
          setAnalysis(response.data);
          return;
        }
        setCompletion({ sources: response.data.total_sources, transactions: response.data.transaction_count, reviews: response.data.review_sources });
        setPreflight(null); setAnalysis(null);
        await activateCase(bridge, headerResponse.data);
        await bridge.dismissAnalysisTask(taskId);
        return;
      }
      setAnalysis(response.data);
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 350);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [activateCase, analysis?.analysis_task_id, analysis?.state, bridge]);

  const closeCase = async () => {
    if (!bridge) return;
    ++requestRef.current; await bridge.closeCase(); sessionRef.current = null; setHeader(null); clearCaseUi();
    setHistoryOpen(false); setRecentCases([]); setRecentCorrupt(false);
    setContextDraft({ company_name: "", confirmed_primary_business: "", confirmed_products_or_services: "", confirmation_note: "", confirmation_status: "unconfirmed" });
    setContextNotice("");
    setAppState((current) => current ? { ...current, case_loaded: false, case_session_id: null } : current);
  };

  const selectModule = (descriptor: ModuleDescriptorDTO) => {
    if (bridge && sessionRef.current) void loadModule(bridge, descriptor, sessionRef.current, 1, {}, pageSize);
  };

  const selectItem = useCallback(async (item: ReviewItemDTO) => {
    if (!bridge || !sessionRef.current) return;
    setSelectedId(item.item_id); setInspectorOpen(true); setFullEvidence(false); setEvidence(null); setEvidenceError("");
    if (!item.transaction_id || !item.evidence_available) { setEvidenceError("该项没有可用的交易证据引用。"); return; }
    const sessionId = sessionRef.current; const token = ++requestRef.current;
    const response = await bridge.getEvidence(item.transaction_id, sessionId);
    if (token !== requestRef.current || sessionRef.current !== sessionId) return;
    if (response.ok && response.data && isCurrentCase(sessionId, response.data.case_session_id)) setEvidence(response.data);
    else setEvidenceError(response.error?.message || "证据不可用");
  }, [bridge]);

  const moveSelection = useCallback((offset: number) => {
    if (!pageData.items.length) return;
    const current = pageData.items.findIndex((item) => item.item_id === selectedId);
    const next = Math.min(pageData.items.length - 1, Math.max(0, (current < 0 ? 0 : current) + offset));
    void selectItem(pageData.items[next]);
  }, [pageData.items, selectedId, selectItem]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setCommandOpen(true); return; }
      if (event.key === "Escape") { if (commandOpen) setCommandOpen(false); else if (sourceReviewOpen) setSourceReviewOpen(false); else setInspectorOpen(false); return; }
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
      if (event.key === "ArrowDown") { event.preventDefault(); moveSelection(1); }
      if (event.key === "ArrowUp") { event.preventDefault(); moveSelection(-1); }
      if (event.key === "Enter" && selectedId) setInspectorOpen(true);
    };
    window.addEventListener("keydown", handler); return () => window.removeEventListener("keydown", handler);
  }, [commandOpen, moveSelection, selectedId, sourceReviewOpen]);
  useEffect(() => { if (commandOpen) window.setTimeout(() => commandInput.current?.focus(), 0); }, [commandOpen]);

  const showSourceReviews = async () => {
    if (!bridge || !sessionRef.current) return;
    const sessionId = sessionRef.current; setSourceReviewOpen(true); setSourceReview(null);
    const response = await bridge.listSourceReviews(sessionId);
    if (sessionRef.current === sessionId && response.ok && response.data && isCurrentCase(sessionId, response.data.case_session_id)) setSourceReview(response.data);
  };
  const applyFilters = () => bridge && activeModule && sessionRef.current && loadModule(bridge, activeModule, sessionRef.current, 1, filterDraft, pageSize);
  const resetFilters = () => bridge && activeModule && sessionRef.current && loadModule(bridge, activeModule, sessionRef.current, 1, {}, pageSize);
  const changePage = (page: number) => bridge && activeModule && sessionRef.current && canChangePage(page, pageData.total_pages) && loadModule(bridge, activeModule, sessionRef.current, page, filters, pageSize);
  const handleListWheel = (event: ReactWheelEvent<HTMLElement>) => {
    const element = event.currentTarget;
    const atTop = element.scrollTop <= 0;
    const atBottom = element.scrollTop + element.clientHeight >= element.scrollHeight - 1;
    if (event.deltaY < 0 && atTop && pageData.page > 1) changePage(pageData.page - 1);
    else if (event.deltaY > 0 && atBottom && pageData.page < pageData.total_pages) changePage(pageData.page + 1);
  };

  const selectedIndex = pageData.items.findIndex((item) => item.item_id === selectedId);
  const categories = useMemo(() => Object.entries(summary?.category_counts || {}), [summary]);

  return <main className="app-shell" data-theme={theme} data-inspector={inspectorOpen || sourceReviewOpen ? "open" : "closed"}>
    <aside className="sidebar">
      <div className="workspace-switch"><span className="workspace-glyph"><FileJson /></span><span className="workspace-copy"><strong>流水核查</strong><small>{analysis?.case_display_name || preflight?.case_display_name || header?.case_name || "基础审核工作台"}</small></span></div>
      <section className="sidebar-section module-section"><p>流水核查</p>{modules.map((item) => { const Icon = ICONS[item.icon] || CircleHelp; const disabled = !isModuleEnabled(item.availability); return <button key={item.module_id} className={`sidebar-row ${activeModule?.module_id === item.module_id ? "active" : ""} ${disabled ? "disabled" : ""}`} onClick={() => selectModule(item)} disabled={disabled}><Icon /><span>{item.title}</span>{item.review_count > 0 && <i className="review-dot" />}{item.availability === "not_implemented" ? <em>未实施</em> : <b>{header ? item.total_count : ""}</b>}</button>; })}</section>
      <div className="sidebar-bottom"><button className="sidebar-row" onClick={() => setTheme(nextTheme(theme))}>{theme === "dark" ? <Moon /> : <Sun />}<span>主题：{theme === "dark" ? "深色" : "浅色"}</span></button></div>
    </aside>
    <section className="work-area">
      <header className="context-bar"><div className="breadcrumb"><span>{analysis?.case_display_name || preflight?.case_display_name || header?.case_name || "未加载案件"}</span>{activeModule && !analysis && !preflight && <><i>/</i><strong>{activeModule.title}</strong></>}</div><div className="context-actions"><IconButton icon={Search} label="搜索命令 (Ctrl+K)" onClick={() => setCommandOpen(true)} /><IconButton icon={History} label="历史案件" onClick={openHistory} disabled={!bridge || loading || historyOpen} /><IconButton icon={FolderPlus} label="新建案件" onClick={chooseNewCase} disabled={!bridge || loading || isAnalysisActive(analysis?.state)} /><IconButton icon={FolderOpen} label="打开标准结果" onClick={openResult} disabled={!bridge || loading || isAnalysisActive(analysis?.state)} /></div></header>
      {completion && <div className="completion-toast"><strong>分析完成</strong><span>共处理 {completion.sources} 个来源 · {completion.transactions} 笔交易 · {completion.reviews} 个来源需复核</span><button onClick={() => setCompletion(null)} aria-label="关闭完成提示"><X /></button></div>}
      {notice && <div className="save-toast">{notice}</div>}
      {analysis ? <AnalysisProgress value={analysis} error={error} onCancel={cancelAnalysis} onBack={leaveAnalysis} /> : preflight ? <CasePreflight value={preflight} loading={loading} error={error} onStart={startAnalysis} onReselect={chooseNewCase} onCancel={() => { setPreflight(null); setError(""); }} context={contextDraft} extract={contextExtract} contextNotice={contextNotice} onContextChange={setContextDraft} onSaveContext={saveContext} /> : historyOpen ? <HistoryPage cases={recentCases} corrupt={recentCorrupt} loading={historyLoading} error={error} onOpen={openRecentCase} onRemove={removeRecentCase} onClose={() => { setHistoryOpen(false); setError(""); }} /> : !header ? <EmptyWorkspace connection={connection} loading={loading} error={error} onNew={chooseNewCase} onOpen={openResult} /> : <>
        <header className="view-bar"><div className="view-title"><strong>{activeModule?.title}</strong><span>{pageData.total} 项</span></div><div className="summary-metrics"><span>总计 <b>{summary?.total_count ?? 0}</b></span><span className={summary?.review_count ? "warning-text" : ""}>需复核 <b>{summary?.review_count ?? 0}</b></span>{categories.slice(0, 2).map(([label, count]) => <span key={label}>{label} <b>{count}</b></span>)}</div><div className="case-meta">{header.period_start.slice(0, 10)}—{header.period_end.slice(0, 10)} · {header.source_count} 来源{shouldShowSourceReview(header.review_source_count) && <button className="source-review-alert" onClick={showSourceReviews}> · {header.review_source_count} 来源需复核</button>} · {header.transaction_count} 交易 · schema {header.schema_version}</div></header>
        <div className="module-summary"><span>{summary?.description}</span>{summary?.boundary_note && <em>{summary.boundary_note}</em>}<div className="module-actions"><button className="save-result-button" onClick={rebuildContext}><RefreshCw />重新构建上下文观察</button><button className="save-result-button" onClick={exportReport}><FileText />导出报告</button><button className="save-result-button" onClick={saveResult}><Save />保存标准结果</button></div></div>
        <div className="filter-bar"><div className="filter-controls"><span className="property-button static"><SlidersHorizontal />筛选</span>{pageData.available_filters.map((definition) => definition.kind === "select" ? <select key={definition.key} value={filterDraft[definition.key] || ""} onChange={(event) => setFilterDraft({ ...filterDraft, [definition.key]: event.target.value })}><option value="">{definition.label}：全部</option>{definition.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select> : <input key={definition.key} type={definition.kind === "date" ? "date" : "search"} aria-label={definition.label} placeholder={definition.label} value={filterDraft[definition.key] || ""} onChange={(event) => setFilterDraft({ ...filterDraft, [definition.key]: event.target.value })} />)}<button className="property-button applied" onClick={applyFilters}>应用</button><button className="property-button" onClick={resetFilters}>重置</button></div><select aria-label="每页数量" value={pageSize} onChange={(event) => { const size = Number(event.target.value); if (bridge && activeModule && sessionRef.current) void loadModule(bridge, activeModule, sessionRef.current, 1, filters, size); }}><option value="25">25 / 页</option><option value="50">50 / 页</option><option value="100">100 / 页</option></select></div>
        <section className="list-region" aria-label="模块候选列表" onWheel={handleListWheel}>{loading && <div className="loading-line"><LoaderCircle className="spin" />正在读取当前模块…</div>}{error && <div className="inline-error">{error}</div>}{activeModule?.availability === "empty" ? <ListState text="当前结果中没有该类候选" /> : pageData.items.length === 0 && !loading ? <ListState text="当前筛选下没有候选" /> : <div className="issue-list"><div className="list-header"><span /><span>日期</span><span>交易与命中内容</span><span>金额</span><span>分类</span><span>来源</span></div>{pageData.items.map((item) => <button className={`transaction-row ${selectedId === item.item_id ? "selected" : ""}`} key={item.item_id} onClick={() => selectItem(item)}><span className="row-status"><span className={`status-mark ${item.review_status === "review" ? "review" : "direct"}`} /></span><time>{item.date?.slice(5, 10) || "—"}</time><span className="transaction-title"><strong>{item.primary_text}</strong><em>{item.matched_text || item.secondary_text || item.interpretation}</em></span><span className="amount">{item.amount ? `${item.direction === "收入" ? "+" : item.direction === "支出" ? "−" : ""}${item.amount}` : "—"}</span><span className={`row-verdict ${item.review_status}`}>{item.category || "—"}</span><span className="source-name">{item.source_name || (item.evidence_available ? "证据可用" : "无交易证据")}</span></button>)}</div>}<footer className="page-footer"><span>第 {pageData.page} / {pageData.total_pages} 页 · {pageData.total} 条 · 查询 {pageData.meta.query_elapsed_ms ?? 0}ms</span><div><button onClick={() => changePage(pageData.page - 1)} disabled={pageData.page <= 1}><ChevronLeft />上一页</button><button onClick={() => changePage(pageData.page + 1)} disabled={pageData.page >= pageData.total_pages}>下一页<ChevronRight /></button></div></footer></section>
      </>}
    </section>
    {inspectorOpen && <Inspector evidence={evidence} error={evidenceError} full={fullEvidence} index={selectedIndex} total={pageData.items.length} onFull={setFullEvidence} onClose={() => setInspectorOpen(false)} onPrevious={() => moveSelection(-1)} onNext={() => moveSelection(1)} />}
    {sourceReviewOpen && <SourceReviewPanel value={sourceReview} onClose={() => setSourceReviewOpen(false)} />}
    {commandOpen && <CommandPalette inputRef={commandInput} onClose={() => setCommandOpen(false)} onNew={chooseNewCase} onOpen={openResult} onTheme={() => { setTheme(nextTheme(theme)); setCommandOpen(false); }} onCloseCase={closeCase} caseLoaded={Boolean(header)} />}
  </main>;
}

function EmptyWorkspace({ connection, loading, error, onNew, onOpen }: { connection: Connection; loading: boolean; error: string; onNew: () => void; onOpen: () => void }) {
  const disconnected = connection === "disconnected";
  return <section className="empty-workspace"><span className="empty-icon">{loading ? <LoaderCircle className="spin" /> : disconnected ? <CircleHelp /> : <FileJson />}</span><h1>{loading ? "正在读取案件" : disconnected ? "未连接桌面 API" : "流水核查工作台"}</h1><p>{disconnected ? "请从“启动WebView2流水核查工作台.bat”打开。" : "从客户案件目录运行现有正式分析流程，或打开已有 schema 1.16 标准结果。"}</p>{error && <div className="empty-error">{error}</div>}<div className="empty-actions"><button className="primary-button" onClick={onNew} disabled={disconnected || loading}><FolderPlus />新建案件</button><button className="secondary-button" onClick={onOpen} disabled={disconnected || loading}><FolderOpen />打开标准结果</button></div></section>;
}

function CasePreflight({ value, loading, error, onStart, onReselect, onCancel, context, extract, contextNotice, onContextChange, onSaveContext }: { value: CasePreflightDTO; loading: boolean; error: string; onStart: () => void; onReselect: () => void; onCancel: () => void; context: ManualContextInput; extract: ManualContextDTO | null; contextNotice: string; onContextChange: (next: ManualContextInput) => void; onSaveContext: () => void }) {
  const hasExtract = Boolean(extract && (extract.source_names.length > 0 || extract.company_name || extract.declared_work_description || extract.work_units.length > 0 || extract.work_locations.length > 0 || extract.residence_locations.length > 0));
  return <section className="workflow-page"><header className="workflow-header"><div><span>来源预检</span><h1>{value.case_display_name}</h1><p>只核对正式流程支持的来源，不运行完整流水解析。</p></div><dl><div><dt>支持</dt><dd>{value.supported_source_count}</dd></div><div><dt>不支持</dt><dd>{value.unsupported_source_count}</dd></div><div><dt>预检耗时</dt><dd>{value.elapsed_ms}ms</dd></div></dl></header>{value.warnings.length > 0 && <div className="workflow-warnings">{value.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}{error && <div className="inline-error">{error}</div>}<div className="source-table"><div className="source-table-head"><span>来源</span><span>类型</span><span>识别</span><span>大小</span><span>状态</span></div>{value.sources.map((source) => <div className="source-table-row" key={source.source_ref}><span><strong>{source.display_name}</strong>{source.warning && <em>{source.warning}</em>}</span><span>{source.detected_source_type === "pdf" ? "PDF" : source.detected_source_type === "excel" ? "Excel" : source.extension || "其他"}</span><span>{source.detected_bank_type || "未识别"}{source.may_use_generic_fallback ? " · 可能通用回退" : ""}</span><span>{formatBytes(source.size)}</span><span className={source.supported ? "source-ready" : source.initial_status === "context" ? "source-context" : "source-unsupported"}>{source.supported ? "可处理" : source.initial_status === "context" ? "上下文资料" : "将跳过"}</span></div>)}</div>{hasExtract && extract && <section className="context-section extracted-context"><header><span>案件上下文（来自 TXT 自动提取）</span></header>{extract.source_names.length > 0 && <p className="context-note">来源：{extract.source_names.join("、")}</p>}<div className="context-grid"><label>工作单位<strong className="extract-value">{extract.company_name || "—"}</strong></label><label>申报工作描述<strong className="extract-value">{extract.declared_work_description || "—"}</strong></label><label>工作单位候选<strong className="extract-value">{extract.work_units.length ? extract.work_units.join("、") : "—"}</strong></label><label>工作地点<strong className="extract-value">{extract.work_locations.length ? extract.work_locations.join("、") : "—"}</strong></label><label>居住地点<strong className="extract-value">{extract.residence_locations.length ? extract.residence_locations.join("、") : "—"}</strong></label><label>提取状态<strong className="extract-value">{extract.declared_work_status || "—"}</strong></label></div></section>}<section className="context-section"><header><span>经营上下文（可选）</span><button className="property-button" onClick={onSaveContext} disabled={loading}>{loading ? <LoaderCircle className="spin" /> : <Save />}保存经营上下文</button></header>{contextNotice && <p className="context-notice">{contextNotice}</p>}<p className="context-note">当 TXT 未提取到明确工作内容时，可在此人工补充，作为辅助。</p><div className="context-grid"><label>工作单位<input value={context.company_name} onChange={(event) => onContextChange({ ...context, company_name: event.target.value })} /></label><label>确认状态<select value={context.confirmation_status} onChange={(event) => onContextChange({ ...context, confirmation_status: event.target.value })}><option value="unconfirmed">未确认</option><option value="confirmed">已确认</option></select></label><label>主要经营内容<input value={context.confirmed_primary_business} onChange={(event) => onContextChange({ ...context, confirmed_primary_business: event.target.value })} /></label><label>产品 / 服务<input value={context.confirmed_products_or_services} onChange={(event) => onContextChange({ ...context, confirmed_products_or_services: event.target.value })} /></label><label>补充说明<textarea value={context.confirmation_note} onChange={(event) => onContextChange({ ...context, confirmation_note: event.target.value })} /></label></div></section><footer className="workflow-actions"><button className="secondary-button" onClick={onCancel}>取消</button><button className="secondary-button" onClick={onReselect} disabled={loading}>重新选择</button><button className="primary-button" onClick={onStart} disabled={loading || !value.can_start}>{loading ? <LoaderCircle className="spin" /> : <ClipboardCheck />}开始分析</button></footer></section>;
}

function HistoryPage({ cases, corrupt, loading, error, onOpen, onRemove, onClose }: { cases: RecentCaseDTO[]; corrupt: boolean; loading: boolean; error: string; onOpen: (recordId: string) => void; onRemove: (recordId: string) => void; onClose: () => void }) {
  return <section className="workflow-page history-page"><header className="workflow-header"><div><span>历史案件</span><h1>最近打开的案件</h1><p>只记录摘要，不包含客户原始资料与完整结果。</p></div></header>{error && <div className="inline-error">{error}</div>}{corrupt && <div className="workflow-warnings"><p>最近案件索引损坏，已按空列表处理；打开新案件后会重建。</p></div>}{loading ? <div className="loading-line"><LoaderCircle className="spin" />正在读取历史案件…</div> : cases.length === 0 ? <ListState text="暂无历史案件" /> : <div className="history-list">{cases.map((record) => <div className="history-row" key={record.record_id}><div><strong>{record.case_name}</strong><em>{record.period_start || "—"} 至 {record.period_end || "—"} · {record.source_count} 来源 · {record.transaction_count} 交易 · schema {record.schema_version || "—"}</em></div><span>{record.updated_at}</span><div className="history-actions"><button className="property-button" disabled={!record.available || loading} onClick={() => onOpen(record.record_id)}>打开</button><button className="property-button danger-text" onClick={() => onRemove(record.record_id)}>删除</button></div></div>)}</div>}<footer className="workflow-actions"><button className="secondary-button" onClick={onClose}>返回</button></footer></section>;
}

const STAGE_LABELS: Record<string, string> = {
  discovering_sources: "正在识别来源", detecting_source_type: "正在识别来源类型",
  parsing_source: "正在解析来源", normalizing_transactions: "正在规范化交易",
  reading_source: "正在处理来源", building_result: "正在构建标准结果",
  validating_result: "正在校验 schema 1.16", finalizing: "正在完成结果接入",
  cancelling: "正在停止", cancelled: "分析已取消", failed: "分析未完成", completed: "分析完成",
};

function AnalysisProgress({ value, error, onCancel, onBack }: { value: AnalysisStatusDTO; error: string; onCancel: () => void; onBack: () => void }) {
  const active = isAnalysisActive(value.state);
  const progress = value.total_sources ? Math.round(value.completed_sources / value.total_sources * 100) : 0;
  return <section className="workflow-page analysis-page"><header className="workflow-header"><div><span>{STAGE_LABELS[value.current_stage] || "正在分析"}</span><h1>{value.case_display_name}</h1><p>{value.current_source_name ? `当前来源：${value.current_source_name}` : value.state === "cancelling" ? "正在停止，当前文件处理完成后结束。" : "使用当前正式解析与核查流程。"}</p></div><dl><div><dt>已完成</dt><dd>{value.completed_sources} / {value.total_sources}</dd></div><div><dt>成功 / 复核 / 失败</dt><dd>{value.success_sources} / {value.review_sources} / {value.failed_sources}</dd></div><div><dt>已耗时</dt><dd>{formatElapsed(value.elapsed_ms)}</dd></div></dl></header><div className="coarse-progress" aria-label={`已完成 ${value.completed_sources} / ${value.total_sources} 个来源`}><i style={{ width: `${progress}%` }} /></div>{(error || value.error_message) && <div className="inline-error">{value.error_message || error}</div>}<div className="source-table"><div className="source-table-head analysis-source-head"><span>来源</span><span>类型</span><span>交易</span><span>状态</span></div>{value.sources.map((source) => <div className="source-table-row analysis-source-row" key={source.source_ref}><span><strong>{source.display_name}</strong>{source.message && <em>{source.message}</em>}</span><span>{source.source_type === "pdf" ? "PDF" : "Excel"}</span><span>{source.transaction_count || "—"}</span><span className={`analysis-source-status ${source.status}`}>{source.status === "included" ? "已纳入" : source.status === "review" ? "需复核" : source.status === "pending" ? "等待处理" : source.status}</span></div>)}</div><footer className="workflow-actions"><span>{value.state === "cancelling" ? "正在停止，当前文件处理完成后结束。" : active ? "分析期间可继续查看来源级进度。" : value.state === "cancelled" ? "未生成或接入部分结果。" : "原案件仍保留，可返回审核工作台。"}</span>{active ? <button className="secondary-button danger-button" onClick={onCancel} disabled={value.state === "cancelling"}><StopCircle />{value.state === "cancelling" ? "正在停止" : "取消分析"}</button> : <button className="primary-button" onClick={onBack}>返回</button>}</footer></section>;
}

function formatBytes(value: number): string { return value < 1024 ? `${value} B` : value < 1024 * 1024 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`; }
function formatElapsed(value: number): string { const seconds = Math.floor(value / 1000); return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`; }

function ListState({ text }: { text: string }) { return <div className="list-state"><FileJson /><strong>{text}</strong></div>; }

function Inspector({ evidence, error, full, index, total, onFull, onClose, onPrevious, onNext }: { evidence: EvidenceDetailDTO | null; error: string; full: boolean; index: number; total: number; onFull: (value: boolean) => void; onClose: () => void; onPrevious: () => void; onNext: () => void }) {
  return <aside className="inspector"><header className="inspector-bar"><strong>交易证据</strong><div><button onClick={onPrevious} disabled={index <= 0}><ChevronLeft /></button><button onClick={onNext} disabled={index < 0 || index >= total - 1}><ChevronRight /></button><IconButton icon={X} label="关闭详情" onClick={onClose} /></div></header><div className="inspector-scroll">{error ? <div className="inspector-empty"><ShieldAlert /><strong>证据不可用</strong><span>{error}</span></div> : !evidence ? <div className="inspector-empty"><LoaderCircle className="spin" /><strong>正在读取当前交易证据</strong><span>完整结果仍保留在 Python 端。</span></div> : <><section className="transaction-overview"><div className="amount-large">{evidence.direction}<strong>{evidence.amount}</strong></div><h1>{evidence.counterparty || "未提供交易对手"}</h1><time>{evidence.date}</time></section><div className="property-list">{[["证据状态",evidence.integrity_status],["交易ID",evidence.transaction_id_short],["摘要",evidence.summary || "—"],["用途",evidence.purpose || "—"],["来源",evidence.source_name],["定位",evidence.page_no ? `第${evidence.page_no}页 · 第${evidence.row_no}行` : evidence.evidence_locator || "未提供"]].map(([label,value]) => <div className="property-row" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><section className="annotation-section"><p>引用原因</p><span>{evidence.reference_reason}</span></section><button className="evidence-toggle" onClick={() => onFull(!full)}><ChevronRight className={full ? "expanded" : ""} />{full ? "收起完整允许内容" : "展开完整允许内容"}</button><pre className="evidence-block">{(full ? evidence.full_original_fields : evidence.masked_original_fields).filter((line) => { const trimmed = line.trim(); return trimmed !== "" && trimmed !== "/"; }).join("\n") || "无可显示原始字段"}</pre></>}</div></aside>;
}

function SourceReviewPanel({ value, onClose }: { value: SourceReviewSummaryDTO | null; onClose: () => void }) {
  return <aside className="inspector source-review-panel"><header className="inspector-bar"><strong>来源需复核</strong><IconButton icon={X} label="关闭来源复核" onClick={onClose} /></header><div className="inspector-scroll">{!value ? <div className="inspector-empty"><LoaderCircle className="spin" /><strong>正在读取来源状态</strong></div> : value.items.length === 0 ? <div className="inspector-empty"><strong>当前没有需复核来源</strong></div> : value.items.map((item) => <section className="source-review-item" key={item.source_id}><header><span className="status-mark review" /><strong>{item.display_name}</strong></header><p>{item.review_reason}</p><dl><div><dt>来源类型</dt><dd>{item.source_type}</dd></div><div><dt>交易生成</dt><dd>{item.generated_transactions ? "已生成" : "未生成"}</dd></div>{item.parser_name && <div><dt>解析器</dt><dd>{item.parser_name}</dd></div>}</dl></section>)}</div></aside>;
}

function CommandPalette({ inputRef, onClose, onNew, onOpen, onTheme, onCloseCase, caseLoaded }: { inputRef: React.RefObject<HTMLInputElement>; onClose: () => void; onNew: () => void; onOpen: () => void; onTheme: () => void; onCloseCase: () => void; caseLoaded: boolean }) {
  const [query, setQuery] = useState("");
  const commands = [{ icon: FolderPlus, label: "新建案件", action: onNew }, { icon: FolderOpen, label: "打开标准结果", action: onOpen }, { icon: Sun, label: "切换主题", action: onTheme }, ...(caseLoaded ? [{ icon: Archive, label: "关闭当前案件", action: onCloseCase }] : [])].filter((item) => item.label.includes(query));
  return <div className="command-backdrop" onMouseDown={onClose}><section className="command-palette" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><div className="command-search"><Search /><input ref={inputRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索命令…" /><kbd>Esc</kbd></div><div className="command-results"><p>建议</p>{commands.map(({ icon: Icon, label, action }, index) => <button key={label} className={index === 0 ? "current" : ""} onClick={action}><Icon /><span>{label}</span></button>)}</div></section></div>;
}
