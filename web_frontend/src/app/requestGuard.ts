export function isCurrentCase(expected: string | null, returned: string | null | undefined): boolean {
  return Boolean(expected && returned && expected === returned);
}

export function isCurrentAnalysis(expected: string | null, returned: string | null | undefined): boolean {
  return Boolean(expected && returned && expected === returned);
}

export function isAnalysisActive(state: string | null | undefined): boolean {
  return state === "running" || state === "cancelling";
}

export function clearedCaseState() {
  return { selectedId: "", inspectorOpen: false, sourceReviewOpen: false, filters: {} as Record<string, string>, page: 1 };
}

export function isModuleEnabled(availability: string): boolean {
  return availability === "available" || availability === "empty";
}

export function filterChangeState(filters: Record<string, string>) {
  return { filters, page: 1, selectedId: "", inspectorOpen: false };
}

export function canChangePage(page: number, totalPages: number): boolean {
  return page >= 1 && page <= totalPages;
}

export function nextTheme(theme: "dark" | "light"): "dark" | "light" {
  return theme === "dark" ? "light" : "dark";
}

export function isCompatibleApiVersion(version: string): boolean {
  return version === "1";
}

export function shouldShowSourceReview(count: number): boolean {
  return count > 0;
}

export function bridgeErrorMessage(message?: string | null): string {
  return message || "桌面 API 请求失败";
}

export function emptyModuleMessage(availability: string): string {
  return availability === "not_implemented" ? "当前版本尚未实施" : "当前结果中没有该类候选";
}
