"""Export one customer directory through the schema 1.16 GUI processing path."""

from __future__ import annotations

import argparse
import hashlib
import socket
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.result_export import write_bankflow_json
from bankflow_v2.standard_result_view import (
    build_case_context_from_directory,
    evidence_transaction,
    validate_standard_result,
)
from bankflow_v2.verification_worker import SUPPORTED_INPUTS, VerificationWorker
from bankflow_web.case_session import CaseSession
from gui_verification_app import (
    business_confirmation_from_record,
    load_manual_case_context,
)


def _files_in_case(case_dir: Path) -> list[Path]:
    return sorted(
        (path for path in case_dir.rglob("*") if path.is_file()),
        key=lambda path: str(path.relative_to(case_dir)).casefold(),
    )


def _source_paths(case_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in case_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_INPUTS
    )


def _case_snapshot(case_dir: Path) -> dict[str, tuple[int, int, str]]:
    snapshot: dict[str, tuple[int, int, str]] = {}
    for path in _files_in_case(case_dir):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        stat = path.stat()
        snapshot[str(path.relative_to(case_dir))] = (
            stat.st_size,
            stat.st_mtime_ns,
            digest.hexdigest(),
        )
    return snapshot


@contextmanager
def _network_blocked() -> Iterator[None]:
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def blocked(*_args, **_kwargs):
        raise RuntimeError("该导出工具禁止网络连接")

    socket.socket.connect = blocked
    socket.create_connection = blocked
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_create_connection


def _case_context(case_dir: Path) -> dict[str, object]:
    manual = load_manual_case_context(case_dir)
    confirmation = business_confirmation_from_record(manual)
    if confirmation.get("confirmation_status") == "confirmed":
        return build_case_context_from_directory(
            case_dir,
            business_confirmation=confirmation,
        )
    return build_case_context_from_directory(case_dir)


def _run_formal_worker(
    paths: list[Path],
    case_context: dict[str, object],
) -> tuple[list[object], list[object], dict[str, object]]:
    completed: list[tuple[list[object], list[object], dict[str, object]]] = []
    failures: list[str] = []
    worker = VerificationWorker(
        paths,
        pdf_passwords={},
        case_context=case_context,
        ai_config={},
        ai_evaluator=None,
    )
    worker.finished.connect(
        lambda sources, issues, result: completed.append((sources, issues, result))
    )
    worker.failed.connect(failures.append)
    worker.run()
    if failures:
        raise RuntimeError(failures[0])
    if len(completed) != 1:
        raise RuntimeError("正式处理入口未返回标准结果")
    return completed[0]


def _validate_result(result: dict[str, object], output: Path) -> list[str]:
    validated = validate_standard_result(result)
    if validated.get("module") != "bankflow":
        raise ValueError("标准结果 module 不是 bankflow")
    result_body = validated["result"]
    transactions = result_body["original_transactions"]
    if not transactions:
        raise ValueError("标准结果没有 original_transactions")
    evidence = result_body["evidence"]
    transaction_index = evidence.get("transaction_index")
    if not isinstance(transaction_index, dict) or not transaction_index:
        raise ValueError("标准结果没有 evidence.transaction_index")

    checked: list[str] = []
    for transaction in transactions:
        if not isinstance(transaction, dict):
            continue
        transaction_id = str(transaction.get("transaction_id") or "")
        if not transaction_id:
            continue
        resolved = evidence_transaction(validated, transaction_id)
        if resolved["transaction"].get("transaction_id") != transaction_id:
            raise ValueError("transaction_id 精确回跳不一致")
        checked.append(transaction_id)
        if len(checked) == 3:
            break
    if len(checked) < 3:
        raise ValueError("可精确回跳的 transaction_id 少于 3 个")

    session = CaseSession()
    session.load(output)
    session.close()
    return checked


def export_case(case_dir: Path, output: Path) -> dict[str, object]:
    case_dir = case_dir.resolve(strict=True)
    if not case_dir.is_dir():
        raise NotADirectoryError(f"客户资料目录无效：{case_dir}")
    output = output.resolve(strict=False)
    if output.suffix.lower() != ".json":
        raise ValueError("输出文件必须使用 .json 扩展名")
    if output == case_dir or case_dir in output.parents:
        raise ValueError("输出文件不得位于客户资料目录内")
    if output.exists():
        raise FileExistsError(f"输出文件已存在：{output}")

    paths = _source_paths(case_dir)
    if not paths:
        raise ValueError("客户资料目录中未找到支持的 PDF/Excel 文件")
    before = _case_snapshot(case_dir)
    with _network_blocked():
        source_results, issues, result = _run_formal_worker(
            paths,
            _case_context(case_dir),
        )
    if not any(getattr(item, "transactions", []) for item in source_results):
        raise ValueError("正式处理入口未解析到交易")

    validate_standard_result(result)
    write_bankflow_json(result, output)
    checked_ids = _validate_result(result, output)
    after = _case_snapshot(case_dir)
    if before != after:
        raise RuntimeError("客户原资料在导出过程中发生变化")
    return {
        "output": str(output),
        "source_count": len(paths),
        "source_error_count": sum(
            1 for item in source_results if getattr(item, "status", "") != "已纳入"
        ),
        "issue_count": len(issues),
        "transaction_count": len(result["result"]["original_transactions"]),
        "checked_transaction_ids": checked_ids,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用正式流水核查处理链导出 schema 1.16 客户结果（AI 与网络关闭）"
    )
    parser.add_argument("--case-dir", required=True, type=Path, help="客户资料目录")
    parser.add_argument("--output", required=True, type=Path, help="目标 JSON 路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = export_case(args.case_dir, args.output)
    except Exception as exc:
        print(f"导出失败：{exc}", file=sys.stderr)
        return 1
    print(f"导出成功：{summary['output']}")
    print(
        "来源文件：{source_count}；交易：{transaction_count}；"
        "来源异常：{source_error_count}；核查事项：{issue_count}".format(**summary)
    )
    print("已验证 3 个 transaction_id 精确回跳；客户原资料 SHA256 快照未变化。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
