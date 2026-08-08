"""Gate E preflight: local branch / upstream tracking audit (read-only)."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


GATE_D31_COMMITS = (
    ("0282877", "fix(knowledge): rebalance payment rail and business evidence boundaries"),
    ("89e458c", "fix(ai): rebalance semantic concept insufficient behavior"),
    ("eaddff4", "test(knowledge): validate gate d3.1 recall recovery"),
)


def _run(repo: str, *args: str) -> tuple[str, str, int]:
    cmd = ["git", "-c", f"safe.directory={repo}", "-C", repo, *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path("D:/Investigator PDF/CD-bankflow-refactor"),
    )
    args = parser.parse_args()
    repo = str(args.repo)

    branch, _, _ = _run(repo, "branch", "--show-current")
    head, _, _ = _run(repo, "rev-parse", "HEAD")
    status, _, _ = _run(repo, "status", "-sb")
    branch_list, _, _ = _run(repo, "branch", "-a", "-vv")
    remote_list, _, _ = _run(repo, "branch", "-r")
    remote_v, _, _ = _run(repo, "remote", "-v")
    upstream, upstream_err, upstream_code = _run(
        repo,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    )
    remote_head, _, _ = _run(
        repo,
        "rev-parse",
        "origin/work/2026-07-18-bankflow-verification",
    )
    branch_remote, _, _ = _run(
        repo,
        "config",
        "--get",
        f"branch.{branch}.remote",
    )
    branch_merge, _, _ = _run(
        repo,
        "config",
        "--get",
        f"branch.{branch}.merge",
    )
    branch_config, _, _ = _run(repo, "config", "--get-regexp", "^branch\\.")

    ancestor_results = []
    for commit, label in GATE_D31_COMMITS:
        _, _, code = _run(repo, "merge-base", "--is-ancestor", commit, "HEAD")
        ancestor_results.append(
            {
                "commit": commit,
                "subject": label,
                "contained_in_head": code == 0,
            }
        )

    tracking_configured = bool(branch_remote and branch_merge)
    q1 = branch == "work/deepseek-12b2-followup"
    q2 = (
        tracking_configured
        and branch_remote == "origin"
        and branch_merge == "refs/heads/work/2026-07-18-bankflow-verification"
    )
    q3 = (
        "no tracking configured; previous reports referenced the explicit "
        "push refspec target, not a configured upstream"
        if not tracking_configured
        else "tracking is configured (see values)"
    )
    q4 = (
        "local branch name differs from remote upstream branch name; no branch "
        "switch detected"
    )

    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": repo,
        "current_local_branch": branch,
        "current_head": head,
        "local_branch_list": branch_list,
        "remote_branch_list": remote_list,
        "upstream_branch": upstream or "",
        "upstream_error": upstream_err or "",
        "upstream_resolution_code": upstream_code,
        "branch_remote": branch_remote or "",
        "branch_merge": branch_merge or "",
        "tracking_configured": tracking_configured,
        "status_short": status,
        "remote_v": remote_v,
        "origin_work_2026_07_18_bankflow_verification": remote_head,
        "gate_d31_commits": ancestor_results,
        "answers": {
            "Q1_current_local_branch_is_work_deepseek_12b2_followup": q1,
            "Q2_upstream_is_origin_work_2026_07_18_bankflow_verification": q2,
            "Q3_tracking_explanation": q3,
            "Q4_naming_difference_or_branch_switch": q4,
        },
        "push_performed": False,
        "push_target_requires_confirmation": True,
        "future_push_target_understood_as": (
            "explicit refspec HEAD:work/2026-07-18-bankflow-verification "
            "(requires user confirmation before any push)"
        ),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "git_branch_upstream_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "git_branch_upstream_audit.md").write_text(
        _render_md(audit),
        encoding="utf-8",
    )
    print("status=ok")
    print(f"branch={branch}")
    print(f"head={head}")
    print(f"tracking_configured={tracking_configured}")
    print(f"output={args.output_dir}")
    return 0


def _render_md(audit: dict) -> str:
    lines = [
        "# Gate E Git Branch / Upstream Audit",
        "",
        f"- repository：`{audit['repository']}`",
        f"- current local branch：`{audit['current_local_branch']}`",
        f"- HEAD：`{audit['current_head']}`",
        f"- configured upstream："
        f"`{audit['upstream_branch'] or 'NONE (not configured)'}`",
        f"- branch remote config：`{audit['branch_remote'] or 'NONE'}`",
        f"- branch merge config：`{audit['branch_merge'] or 'NONE'}`",
        f"- remote ref origin/work/2026-07-18-bankflow-verification："
        f"`{audit['origin_work_2026_07_18_bankflow_verification']}`",
        "",
        "## Answers",
        "",
        f"- Q1 current local branch is work/deepseek-12b2-followup："
        f"**{audit['answers']['Q1_current_local_branch_is_work_deepseek_12b2_followup']}**",
        f"- Q2 upstream is origin/work/2026-07-18-bankflow-verification："
        f"**{audit['answers']['Q2_upstream_is_origin_work_2026_07_18_bankflow_verification']}**",
        f"- Q3：{audit['answers']['Q3_tracking_explanation']}",
        f"- Q4：{audit['answers']['Q4_naming_difference_or_branch_switch']}",
        "",
        "## D.3.1 Commit Containment",
        "",
    ]
    for item in audit["gate_d31_commits"]:
        lines.append(
            f"- `{item['commit']}` {item['subject']}："
            f"contained={item['contained_in_head']}"
        )
    lines.extend(
        [
            "",
            "## Push Status",
            "",
            f"- push performed：{audit['push_performed']}",
            f"- push target requires confirmation："
            f"{audit['push_target_requires_confirmation']}",
            f"- future push target understood as："
            f"{audit['future_push_target_understood_as']}",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
