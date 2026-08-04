"""Re-run approved cases through the framework-neutral Web analysis service."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.result_export import write_bankflow_json
from bankflow_v2.standard_result_view import build_case_context_from_directory
from bankflow_web.analysis.service import AnalysisService
from bankflow_web.analysis.source_discovery import SUPPORTED_INPUTS
from bankflow_web.case_session import CaseSession


IGNORED_KEYS = {"created_at", "run_at", "output_path", "temporary_output_path"}


def snapshot(directory: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        values[str(path.relative_to(directory))] = digest.hexdigest()
    return values


def normalized(value):
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items() if key not in IGNORED_KEYS}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


def transaction_ids(result: dict[str, object]) -> set[str]:
    return {
        str(item.get("transaction_id") or "")
        for item in result["result"]["original_transactions"]
        if isinstance(item, dict)
    }


def run_case(tag: str, directory: Path, approved_path: Path, output_dir: Path) -> dict[str, object]:
    directory = directory.resolve(strict=True)
    before = snapshot(directory)
    paths = sorted(path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_INPUTS)
    first_progress_ms: float | None = None
    source_update_ms: list[float] = []
    started = time.perf_counter()
    last_source = started
    peak_rss = 0
    stop_sample = threading.Event()

    def sample_memory() -> None:
        nonlocal peak_rss
        try:
            import psutil

            process = psutil.Process()
            while not stop_sample.wait(0.02):
                peak_rss = max(peak_rss, process.memory_info().rss)
        except (ImportError, OSError):
            return

    sampler = threading.Thread(target=sample_memory, daemon=True)
    sampler.start()

    def progress(_event) -> None:
        nonlocal first_progress_ms
        if first_progress_ms is None:
            first_progress_ms = round((time.perf_counter() - started) * 1000, 3)

    def source_complete(_source) -> None:
        nonlocal last_source
        now = time.perf_counter()
        source_update_ms.append(round((now - last_source) * 1000, 3))
        last_source = now

    try:
        outcome = AnalysisService().run(
            paths,
            case_context=build_case_context_from_directory(directory),
            progress=progress,
            source_complete=source_complete,
        )
    finally:
        stop_sample.set()
        sampler.join(1)
    analysis_ms = round((time.perf_counter() - started) * 1000, 3)
    output_path = output_dir / f"{tag}-reanalyzed.json"
    write_bankflow_json(outcome.standard_result, output_path)
    approved = json.loads(approved_path.read_text(encoding="utf-8"))
    equivalent = normalized(outcome.standard_result) == normalized(approved)
    ids_equal = transaction_ids(outcome.standard_result) == transaction_ids(approved)
    evidence_new = outcome.standard_result["result"]["evidence"]["transaction_index"]
    evidence_old = approved["result"]["evidence"]["transaction_index"]
    bind_started = time.perf_counter()
    session = CaseSession()
    session.load_result_dict(outcome.standard_result, case_name=tag, origin="analysis")
    bind_ms = round((time.perf_counter() - bind_started) * 1000, 3)
    header = session.adapter().case_header()
    after = snapshot(directory)
    return {
        "case": tag,
        "source_count": len(paths),
        "review_source_count": sum(source.status == "review" for source in outcome.source_results),
        "transaction_count": header.transaction_count,
        "evidence_index_count": len(evidence_new),
        "business_equivalent_except_runtime": equivalent,
        "transaction_ids_equal": ids_equal,
        "evidence_index_equal": evidence_new == evidence_old,
        "customer_snapshot_unchanged": before == after,
        "first_progress_ms": first_progress_ms,
        "analysis_ms": analysis_ms,
        "result_build_ms": outcome.result_build_ms,
        "case_session_bind_ms": bind_ms,
        "source_completion_intervals_ms": source_update_ms,
        "peak_rss_bytes": peak_rss,
        "case_session_id_created": bool(session.case_session_id),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", nargs=3, metavar=("TAG", "DIRECTORY", "APPROVED"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    results = [run_case(tag, Path(directory), Path(approved), args.output_dir) for tag, directory, approved in args.case]
    summary = {"cases": results, "all_passed": all(
        item["business_equivalent_except_runtime"]
        and item["transaction_ids_equal"]
        and item["evidence_index_equal"]
        and item["customer_snapshot_unchanged"]
        for item in results
    )}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
