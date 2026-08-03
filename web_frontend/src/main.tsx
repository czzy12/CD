import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Archive, Bell, CarFront, ChevronDown, ChevronLeft, ChevronRight, CircleHelp,
  Command, FileJson, Filter, FolderOpen, History, Inbox, Landmark, LoaderCircle,
  Moon, Search, Settings, ShieldAlert, SlidersHorizontal, Sparkles, Sun, X,
  type LucideIcon,
} from "lucide-react";
import {
  connectDesktopBridge,
  type AppStateDTO as AppState,
  type CaseHeaderDTO as CaseHeader,
  type DesktopBridge,
  type EvidenceDetailDTO as Evidence,
  type PagedTransactionsDTO as PageData,
  type PurchaseSummaryDTO as PurchaseSummary,
  type ReviewStatus,
  type TransactionDTO as Transaction,
} from "./bridge/desktopBridge";
import "./styles.css";

type Theme = "dark" | "light";
type Connection = "connecting" | "ready" | "disconnected";

function IconButton({ icon: Icon, label, onClick, disabled = false }: { icon: LucideIcon; label: string; onClick?: () => void; disabled?: boolean }) {
  return <button className="icon-button" data-tooltip={label} aria-label={label} onClick={onClick} disabled={disabled}><Icon /></button>;
}

function App() {
  const [theme, setTheme] = useState<Theme>("dark");
  const [connection, setConnection] = useState<Connection>("connecting");
  const [bridge, setBridge] = useState<DesktopBridge | null>(null);
  const [appState, setAppState] = useState<AppState | null>(null);
  const [header, setHeader] = useState<CaseHeader | null>(null);
  const [summary, setSummary] = useState<PurchaseSummary | null>(null);
  const [pageData, setPageData] = useState<PageData>({ items: [], page: 1, page_size: 50, total: 0, total_pages: 1, query_elapsed_ms: 0, payload_bytes: 0 });
  const [filter, setFilter] = useState("all");
  const [selectedId, setSelectedId] = useState("");
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [fullEvidence, setFullEvidence] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [commandOpen, setCommandOpen] = useState(false);
  const commandInput = useRef<HTMLInputElement>(null);

  const refreshCase = async (activeBridge: DesktopBridge, page = 1, activeFilter = filter) => {
    setLoading(true); setError("");
    const [h, s, rows] = await Promise.all([
      activeBridge.getCaseHeader(),
      activeBridge.getPurchaseSummary(),
      activeBridge.listPurchaseTransactions(page, 50, { status: activeFilter }),
    ]);
    if (!h.ok || !s.ok || !rows.ok) {
      setError(h.error?.message || s.error?.message || rows.error?.message || "读取案件失败");
    } else {
      setHeader(h.data); setSummary(s.data); setPageData(rows.data!); setEvidence(null); setSelectedId(""); setInspectorOpen(false);
      setAppState((current) => current ? { ...current, case_loaded: true } : current);
    }
    setLoading(false);
  };

  useEffect(() => {
    connectDesktopBridge().then(async (activeBridge) => {
      setBridge(activeBridge); setConnection("ready");
      const state = await activeBridge.getAppState();
      if (state.ok && state.data) {
        setAppState(state.data);
        if (state.data.case_loaded) await refreshCase(activeBridge);
      }
    }).catch(() => setConnection("disconnected"));
  }, []);

  useEffect(() => { if (commandOpen) setTimeout(() => commandInput.current?.focus(), 0); }, [commandOpen]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setCommandOpen(true); }
      if (event.key === "Escape") { if (commandOpen) setCommandOpen(false); else setInspectorOpen(false); }
    };
    window.addEventListener("keydown", handler); return () => window.removeEventListener("keydown", handler);
  }, [commandOpen]);

  const openResult = async () => {
    if (!bridge) return;
    setLoading(true); setError(""); setCommandOpen(false);
    const response = await bridge.selectStandardResult();
    if (!response.ok) { if (response.error?.message !== "未选择文件") setError(response.error?.message || "加载失败"); setLoading(false); return; }
    await refreshCase(bridge, 1, filter);
  };

  const changeFilter = async (value: string) => {
    setFilter(value);
    if (!bridge || !header) return;
    setLoading(true);
    const response = await bridge.listPurchaseTransactions(1, 50, { status: value });
    if (response.ok && response.data) setPageData(response.data); else setError(response.error?.message || "筛选失败");
    setLoading(false);
  };

  const changePage = async (page: number) => {
    if (!bridge || page < 1 || page > pageData.total_pages) return;
    setLoading(true);
    const response = await bridge.listPurchaseTransactions(page, 50, { status: filter });
    if (response.ok && response.data) setPageData(response.data); else setError(response.error?.message || "分页失败");
    setLoading(false);
  };

  const selectTransaction = async (transaction: Transaction) => {
    if (!bridge) return;
    setSelectedId(transaction.transaction_id); setInspectorOpen(true); setFullEvidence(false); setEvidence(null);
    const response = await bridge.getEvidence(transaction.transaction_id);
    if (response.ok) setEvidence(response.data); else setError(response.error?.message || "证据不可用");
  };

  const groups = useMemo(() => ([
    { key: "direct" as ReviewStatus, label: "直接命中", items: pageData.items.filter((item) => item.review_status === "direct") },
    { key: "review" as ReviewStatus, label: "需人工核实", items: pageData.items.filter((item) => item.review_status === "review") },
  ]), [pageData.items]);

  return <main className="app-shell" data-theme={theme} data-inspector={inspectorOpen ? "open" : "closed"}>
    <aside className="sidebar">
      <button className="workspace-switch"><span className="workspace-glyph"><Sparkles /></span><span className="workspace-copy"><strong>流水核查</strong><small>{header?.case_name || "Web 集成切片"}</small></span><ChevronDown /></button>
      <section className="sidebar-section quick-section"><p>收件箱</p><button className="sidebar-row"><Inbox /><span>待人工核实</span><b>{summary?.review_count || 0}</b></button><button className="sidebar-row"><Bell /><span>需关注事项</span></button></section>
      <section className="sidebar-section module-section"><p>流水核查</p><button className="sidebar-row active"><CarFront /><span>下定与购车</span><b>{summary?.total_count || 0}</b></button><button className="sidebar-row disabled"><ShieldAlert /><span>其他模块（本轮未接入）</span></button><button className="sidebar-row disabled"><Landmark /><span>资金与余额</span></button></section>
      <div className="sidebar-bottom"><button className="sidebar-row disabled"><History /><span>历史案件（未接入）</span></button><button className="sidebar-row disabled"><Settings /><span>设置</span></button><button className="sidebar-row" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? <Moon /> : <Sun />}<span>主题：{theme === "dark" ? "深色" : "浅色"}</span></button></div>
    </aside>
    <section className="work-area">
      <header className="context-bar"><div className="breadcrumb"><span>{header?.case_name || "未加载案件"}</span><i>/</i><strong>下定与购车</strong></div><div className="context-actions"><IconButton icon={Search} label="搜索 (Ctrl+K)" onClick={() => setCommandOpen(true)} /><IconButton icon={FolderOpen} label="打开标准结果" onClick={openResult} disabled={!bridge} /></div></header>
      {!header ? <EmptyWorkspace connection={connection} loading={loading} error={error} onOpen={openResult} /> : <>
        <header className="view-bar"><div className="view-title"><strong>下定与购车</strong><span>{pageData.total} 项</span></div><div className="summary-metrics"><span>直接命中 <b>{summary?.direct_count}</b></span><span>订金/定金 <b>{summary?.deposit_count}</b></span><span>此前收入 <b>{summary?.prior_income_count}</b></span><span className="warning-text">待判断 <b>{summary?.review_count}</b></span></div><div className="case-meta">{header.period_start.slice(0, 10)}—{header.period_end.slice(0, 10)} · {header.source_count} 来源{header.review_source_count > 0 && <span className="source-review-alert" title={header.review_sources.map((source) => `${source.source_name}：${source.reason}`).join("\n")}> · {header.review_source_count} 来源需复核</span>} · schema {header.schema_version}</div></header>
        <div className="filter-bar"><div className="filter-controls"><span className="property-button static"><SlidersHorizontal />Filter</span>{[["all","全部"],["direct","直接命中"],["deposit","订金/定金"],["prior_income","此前收入"],["review","待人工判断"]].map(([value,label]) => <button key={value} className={`property-button ${filter === value ? "applied" : ""}`} onClick={() => changeFilter(value)}>{label}</button>)}</div><button className="command-hint" onClick={() => setCommandOpen(true)}><Command /> Ctrl+K</button></div>
        <section className="list-region" aria-label="真实下定购车交易列表">{loading && <div className="loading-line"><LoaderCircle />正在读取真实结果…</div>}{error && <div className="inline-error">{error}</div>}<div className="issue-list">{groups.map((group) => group.items.length > 0 && <section className="transaction-group" key={group.key}><div className="group-row"><span className={`status-mark ${group.key}`} /><span>{group.label}</span><b>{group.items.length}</b></div>{group.items.map((item) => <button className={`transaction-row ${selectedId === item.transaction_id ? "selected" : ""}`} key={item.transaction_id} onClick={() => selectTransaction(item)}><span className="row-status"><span className={`status-mark ${item.review_status}`} /></span><time>{item.date.slice(5, 10)}</time><span className="transaction-title"><strong>{item.counterparty}</strong><em>{item.matched_text}</em></span><span className="amount">{item.direction === "收入" ? "+" : "−"}{item.amount}</span><span className={`row-verdict ${item.review_status}`}>{item.category}</span><span className="source-name">{item.source_name}</span></button>)}</section>)}</div><footer className="page-footer"><span>第 {pageData.page} / {pageData.total_pages} 页 · {pageData.total} 条 · 查询 {pageData.query_elapsed_ms}ms · {pageData.payload_bytes} bytes</span><div><button onClick={() => changePage(pageData.page - 1)} disabled={pageData.page <= 1}><ChevronLeft />上一页</button><button onClick={() => changePage(pageData.page + 1)} disabled={pageData.page >= pageData.total_pages}>下一页<ChevronRight /></button></div></footer></section>
      </>}
    </section>
    {inspectorOpen && <Inspector evidence={evidence} full={fullEvidence} onFull={setFullEvidence} onClose={() => setInspectorOpen(false)} />}
    {commandOpen && <CommandPalette inputRef={commandInput} onClose={() => setCommandOpen(false)} onOpen={openResult} onTheme={() => { setTheme(theme === "dark" ? "light" : "dark"); setCommandOpen(false); }} onInspector={() => { setInspectorOpen(false); setCommandOpen(false); }} />}
  </main>;
}

function EmptyWorkspace({ connection, loading, error, onOpen }: { connection: Connection; loading: boolean; error: string; onOpen: () => void }) {
  const disconnected = connection === "disconnected";
  return <section className="empty-workspace"><span className="empty-icon">{loading ? <LoaderCircle className="spin" /> : disconnected ? <CircleHelp /> : <FileJson />}</span><h1>{loading ? "正在读取和校验结果" : disconnected ? "未连接桌面后端" : "打开 schema 1.16 标准结果"}</h1><p>{disconnected ? "请从“启动Web流水核查集成切片.bat”打开。当前不会回退到模拟案件。" : "仅打开已有结果，不解析原始文件，也不会修改所选 JSON。"}</p>{error && <div className="empty-error">{error}</div>}<button className="primary-button" onClick={onOpen} disabled={disconnected || loading}><FolderOpen />打开标准结果</button></section>;
}

function Inspector({ evidence, full, onFull, onClose }: { evidence: Evidence | null; full: boolean; onFull: (value: boolean) => void; onClose: () => void }) {
  return <aside className="inspector"><header className="inspector-bar"><strong>交易证据</strong><IconButton icon={X} label="关闭详情" onClick={onClose} /></header><div className="inspector-scroll">{!evidence ? <div className="inspector-empty"><LoaderCircle className="spin" /><strong>正在读取当前交易证据</strong><span>完整结果仍保留在 Python 端。</span></div> : <><section className="transaction-overview"><div className="amount-large">{evidence.direction}<strong>{evidence.amount}</strong></div><h1>{evidence.counterparty || "未提供交易对手"}</h1><time>{evidence.date}</time></section><div className="property-list">{[["证据状态",evidence.integrity_status],["交易ID",evidence.transaction_id_short],["摘要",evidence.summary || "—"],["用途",evidence.purpose || "—"],["来源",evidence.source_name],["定位",`第${evidence.page_no}页 · 第${evidence.row_no}行`]].map(([label,value]) => <div className="property-row" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><section className="annotation-section"><p>核查说明</p><span>{evidence.reference_reason}</span></section><button className="evidence-toggle" onClick={() => onFull(!full)}><ChevronRight className={full ? "expanded" : ""} />{full ? "收起完整证据" : "展开完整证据"}</button><pre className="evidence-block">{(full ? evidence.full_original_fields : evidence.masked_original_fields).join("\n") || "无可显示原始字段"}</pre></>}</div></aside>;
}

function CommandPalette({ inputRef, onClose, onOpen, onTheme, onInspector }: { inputRef: React.RefObject<HTMLInputElement>; onClose: () => void; onOpen: () => void; onTheme: () => void; onInspector: () => void }) {
  const [query, setQuery] = useState("");
  const commands = [{ icon: FolderOpen, label: "打开标准结果", key: "O", action: onOpen }, { icon: Sun, label: "切换主题", key: "T", action: onTheme }, { icon: Archive, label: "关闭详情", key: "Esc", action: onInspector }].filter((item) => item.label.includes(query));
  return <div className="command-backdrop" onMouseDown={onClose}><section className="command-palette" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><div className="command-search"><Search /><input ref={inputRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索命令…" /><kbd>Esc</kbd></div><div className="command-results"><p>建议</p>{commands.map(({ icon: Icon, label, key, action }, index) => <button key={label} className={index === 0 ? "current" : ""} onClick={action}><Icon /><span>{label}</span><kbd>{key}</kbd></button>)}</div></section></div>;
}

createRoot(document.getElementById("root")!).render(<App />);
