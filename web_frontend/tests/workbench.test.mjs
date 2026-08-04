import test from "node:test";
import assert from "node:assert/strict";

import { readFileSync } from "node:fs";
import { bridgeErrorMessage, canChangePage, clearedCaseState, emptyModuleMessage, filterChangeState, isAnalysisActive, isCompatibleApiVersion, isCurrentAnalysis, isCurrentCase, isModuleEnabled, nextTheme, shouldShowSourceReview } from "../src/app/requestGuard.ts";
import { PyWebviewBridgeAdapter } from "../src/bridge/pywebviewBridgeAdapter.ts";

test("case guard accepts only the active session", () => {
  assert.equal(isCurrentCase("case-a", "case-a"), true);
  assert.equal(isCurrentCase("case-a", "case-b"), false);
  assert.equal(isCurrentCase(null, "case-a"), false);
});

test("case switch clears selection, filters and panels", () => {
  assert.deepEqual(clearedCaseState(), {
    selectedId: "", inspectorOpen: false, sourceReviewOpen: false, filters: {}, page: 1,
  });
});

test("pywebview adapter uses the unified module API", async () => {
  const calls = [];
  const api = new Proxy({}, { get: (_target, key) => async (...args) => {
    calls.push([key, ...args]);
    return { ok: true, data: { case_session_id: "case-a", items: [] }, error: null, meta: { elapsed_ms: 1 } };
  }});
  const bridge = new PyWebviewBridgeAdapter(api);
  await bridge.listModuleItems("purchase", 1, 50, { status: "review" }, "default", "case-a");
  assert.deepEqual(calls[0], ["list_module_items", "purchase", 1, 50, { status: "review" }, "default", "case-a"]);
});

test("pywebview adapter forwards evidence session identity", async () => {
  const calls = [];
  const bridge = new PyWebviewBridgeAdapter({ get_evidence: async (...args) => {
    calls.push(args); return { ok: false, data: null, error: { code: "TRANSACTION_NOT_FOUND", message: "未找到指定交易" }, meta: { elapsed_ms: 1 } };
  }});
  const response = await bridge.getEvidence("tx:old", "case-new");
  assert.equal(response.error?.code, "TRANSACTION_NOT_FOUND");
  assert.deepEqual(calls[0], ["tx:old", "case-new"]);
});

test("invalid desktop envelope is rejected", async () => {
  const bridge = new PyWebviewBridgeAdapter({ get_app_state: async () => ({ invalid: true }) });
  await assert.rejects(() => bridge.getAppState(), /返回格式无效/);
});

test("available and empty modules are interactive while disabled states are not", () => {
  assert.equal(isModuleEnabled("available"), true);
  assert.equal(isModuleEnabled("empty"), true);
  assert.equal(isModuleEnabled("not_implemented"), false);
  assert.equal(isModuleEnabled("unavailable"), false);
});

test("filter changes reset page selection and inspector", () => {
  assert.deepEqual(filterChangeState({ category: "敏感文字" }), { filters: { category: "敏感文字" }, page: 1, selectedId: "", inspectorOpen: false });
});

test("pagination rejects pages outside the loaded result", () => {
  assert.equal(canChangePage(1, 3), true);
  assert.equal(canChangePage(4, 3), false);
  assert.equal(canChangePage(0, 3), false);
});

test("theme toggles in both directions", () => {
  assert.equal(nextTheme("dark"), "light");
  assert.equal(nextTheme("light"), "dark");
});

test("API compatibility is explicit", () => {
  assert.equal(isCompatibleApiVersion("1"), true);
  assert.equal(isCompatibleApiVersion("2"), false);
});

test("source review prompt follows the current case count", () => {
  assert.equal(shouldShowSourceReview(1), true);
  assert.equal(shouldShowSourceReview(0), false);
});

test("bridge errors have a stable natural-language fallback", () => {
  assert.equal(bridgeErrorMessage("读取失败"), "读取失败");
  assert.equal(bridgeErrorMessage(null), "桌面 API 请求失败");
});

test("empty and unimplemented modules have distinct messages", () => {
  assert.equal(emptyModuleMessage("empty"), "当前结果中没有该类候选");
  assert.equal(emptyModuleMessage("not_implemented"), "当前版本尚未实施");
});

test("analysis guard ignores stale polling responses", () => {
  assert.equal(isCurrentAnalysis("task-a", "task-a"), true);
  assert.equal(isCurrentAnalysis("task-a", "task-b"), false);
  assert.equal(isCurrentAnalysis(null, "task-a"), false);
});

test("only running and cancelling are active analysis states", () => {
  assert.equal(isAnalysisActive("running"), true);
  assert.equal(isAnalysisActive("cancelling"), true);
  assert.equal(isAnalysisActive("cancelled"), false);
  assert.equal(isAnalysisActive("failed"), false);
  assert.equal(isAnalysisActive("completed"), false);
});

test("directory selection and preflight use opaque bridge calls", async () => {
  const calls = [];
  const api = new Proxy({}, { get: (_target, key) => async (...args) => {
    calls.push([key, ...args]); return { ok: true, data: {}, error: null, meta: { elapsed_ms: 1 } };
  }});
  const bridge = new PyWebviewBridgeAdapter(api);
  await bridge.chooseCaseDirectory();
  await bridge.inspectCaseDirectory("opaque-handle");
  assert.deepEqual(calls, [["choose_case_directory"], ["inspect_case_directory", "opaque-handle"]]);
});

test("analysis start polling and cancellation preserve task identity", async () => {
  const calls = [];
  const api = new Proxy({}, { get: (_target, key) => async (...args) => {
    calls.push([key, ...args]); return { ok: true, data: { analysis_task_id: "task-a" }, error: null, meta: { elapsed_ms: 1 } };
  }});
  const bridge = new PyWebviewBridgeAdapter(api);
  await bridge.startCaseAnalysis("case-a", {});
  await bridge.getAnalysisStatus("task-a");
  await bridge.cancelAnalysis("task-a");
  assert.deepEqual(calls, [["start_case_analysis", "case-a", {}], ["get_analysis_status", "task-a"], ["cancel_analysis", "task-a"]]);
});

test("terminal task dismissal and result save use Python APIs", async () => {
  const calls = [];
  const api = new Proxy({}, { get: (_target, key) => async (...args) => {
    calls.push([key, ...args]); return { ok: true, data: null, error: null, meta: { elapsed_ms: 1 } };
  }});
  const bridge = new PyWebviewBridgeAdapter(api);
  await bridge.dismissAnalysisTask("task-a");
  await bridge.saveCurrentStandardResult();
  assert.deepEqual(calls, [["dismiss_analysis_task", "task-a"], ["save_current_standard_result"]]);
});

test("cancelled directory selection remains a normal envelope", async () => {
  const bridge = new PyWebviewBridgeAdapter({ choose_case_directory: async () => ({ ok: false, data: null, error: { code: "CANCELLED", message: "未选择目录" }, meta: { elapsed_ms: 1 } }) });
  const response = await bridge.chooseCaseDirectory();
  assert.equal(response.error?.code, "CANCELLED");
});

test("empty state contains distinct new-case and open-result actions", () => {
  const source = readFileSync(new URL("../src/app/App.tsx", import.meta.url), "utf8");
  assert.match(source, /新建案件/);
  assert.match(source, /打开标准结果/);
});

test("preflight view exposes support counts and start controls", () => {
  const source = readFileSync(new URL("../src/app/App.tsx", import.meta.url), "utf8");
  assert.match(source, /来源预检/);
  assert.match(source, /supported_source_count/);
  assert.match(source, /开始分析/);
});

test("progress view explains cooperative cancellation", () => {
  const source = readFileSync(new URL("../src/app/App.tsx", import.meta.url), "utf8");
  assert.match(source, /正在停止，当前文件处理完成后结束/);
  assert.match(source, /取消分析/);
});

test("completed analysis enters review without frontend result payload", () => {
  const source = readFileSync(new URL("../src/app/App.tsx", import.meta.url), "utf8");
  assert.match(source, /getCaseHeader/);
  assert.doesNotMatch(source, /standard_result/);
  assert.doesNotMatch(source, /original_transactions/);
});
