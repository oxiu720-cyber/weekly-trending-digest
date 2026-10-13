#!/usr/bin/env python3
"""
Weekly GitHub Trending Digest
=============================

This script fetches GitHub's weekly trending repositories across 4 categories
of interest (AI/LLM, Web Dev, AI Coding, Security/CTF), generates a Chinese-
language markdown digest with explanations, and opens a PR on the target repo.

Run modes
---------
- default (read-only): fetches trending repos, prints digest markdown to stdout
- --push : clones target repo, writes the report, opens a PR

Environment
-----------
- GH_TOKEN (or GITHUB_TOKEN): a GitHub PAT with `repo` scope on target repo.
- GITHUB_USER  (fallback: read from `gh api user` if available)
- TARGET_REPO  (default: env TARGET_REPO or oxiu720-cyber/weekly-trending-digest)
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import glob
import json
import os
import random
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# --------------------------------------------------------------------------- #
# Configuration                                                                #
# --------------------------------------------------------------------------- #

API_BASE = "https://api.github.com"

CATEGORIES: list[dict] = [
    {
        "key": "ai-llm",
        "title": "AI / LLM / Agent",
        "emoji": "AI",
        "queries": [
            'topic:llm stars:>30',
            'topic:large-language-models stars:>30',
            'topic:ai-agent stars:>20',
            'topic:openai stars:>30',
        ],
    },
    {
        "key": "web-dev",
        "title": "Web 开发（前后端）",
        "emoji": "Web",
        "queries": [
            'topic:react stars:>50',
            'topic:vue stars:>30',
            'topic:nextjs stars:>30',
            'topic:svelte stars:>20',
            'topic:tailwindcss stars:>30',
            'topic:frontend stars:>30',
        ],
    },
    {
        "key": "ai-coding",
        "title": "AI 编程助手 / IDE",
        "emoji": "IDE",
        "queries": [
            'topic:claude-code stars:>20',
            'topic:copilot stars:>20',
            'topic:ai-coding stars:>10',
            'topic:code-agent stars:>10',
            'claude-code in:name,description stars:>15',
        ],
    },
    {
        "key": "security",
        "title": "网络安全 / 挖洞 / CTF",
        "emoji": "Sec",
        "queries": [
            'topic:ctf stars:>15',
            'topic:security-tools stars:>30',
            'topic:pentesting stars:>15',
            'topic:exploit stars:>10',
            'topic:hacking stars:>20',
            'topic:bug-bounty stars:>10',
        ],
    },
]

PER_CATEGORY = 5   # max repos per category in the digest
WINDOW_DAYS = 7    # how recent a repo must be (we use created>...-7d)


# --------------------------------------------------------------------------- #
# HTTP helpers                                                                 #
# --------------------------------------------------------------------------- #

def gh_get(path: str, params: dict | None = None) -> dict:
    """GET GitHub API, returning parsed JSON. Uses GH_TOKEN if available."""
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API error {e.code} for {url}: {body}") from e


def gh_search_repos(query: str, sort: str = "stars", order: str = "desc", per_page: int = 20) -> list[dict]:
    """Wrapper around /search/repositories."""
    since = (dt.date.today() - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    full_q = f"{query} created:>={since}"
    data = gh_get("/search/repositories", {
        "q": full_q,
        "sort": sort,
        "order": order,
        "per_page": per_page,
    })
    return data.get("items", [])


# --------------------------------------------------------------------------- #
# Filtering / ranking                                                          #
# --------------------------------------------------------------------------- #

@dataclass
class Repo:
    full_name: str
    description: str
    html_url: str
    stars: int
    forks: int
    language: str
    topics: list[str]
    pushed_at: str
    owner_avatar: str
    weekly_stars_added: int = 0         # inferred from search ranking
    category: str = ""
    search_query: str = ""

    @property
    def slug(self) -> str:
        return self.full_name.replace("/", "-")


def collect_category(cat: dict, seen: dict[str, Repo]) -> list[Repo]:
    """Run all search queries for one category, dedupe, return sorted list."""
    bag: list[Repo] = []
    for q in cat["queries"]:
        try:
            items = gh_search_repos(q, per_page=10)
        except RuntimeError as e:
            print(f"  ! query failed: {q} -> {e}", file=sys.stderr)
            continue
        for r in items:
            full = r.get("full_name")
            if not full or full in seen:
                continue
            # Skip archived / mirrors / forks where owner is also a fork
            if r.get("archived") or r.get("fork") or r.get("disabled"):
                continue
            stars = r.get("stargazers_count", 0)
            if stars < 5:
                continue
            repo = Repo(
                full_name=full,
                description=(r.get("description") or "").strip().replace("\n", " "),
                html_url=r.get("html_url", ""),
                stars=stars,
                forks=r.get("forks_count", 0),
                language=r.get("language") or "Unknown",
                topics=r.get("topics") or [],
                pushed_at=r.get("pushed_at", ""),
                owner_avatar=(r.get("owner") or {}).get("avatar_url", ""),
                category=cat["key"],
                search_query=q,
            )
            seen[full] = repo
            bag.append(repo)
    bag.sort(key=lambda x: x.stars, reverse=True)
    return bag[:PER_CATEGORY]


def describe(repo: Repo) -> str:
    """Heuristic Chinese-language blurb explaining why this repo is interesting."""
    desc = repo.description or "暂无描述"
    lang = repo.language
    topics = ", ".join(repo.topics[:4]) or "—"
    if repo.stars >= 1000:
        star_noun = f"{repo.stars/1000:.1f}k+ Stars"
    else:
        star_noun = f"{repo.stars} Stars"

    # Try to infer angle from topics / description / name
    text_lower = (repo.description + " " + repo.full_name + " " + " ".join(repo.topics)).lower()
    if any(k in text_lower for k in ("claude", "cursor", "copilot", "ai cod", "code agent")):
        angle = "AI 编程方向，关注 agent/IDE 自动化能力"
    elif any(k in text_lower for k in ("llm", "gpt", "agent", "rag", "langchain", "openai")):
        angle = "AI 应用层工程：与 LLM/Agent 生态结合"
    elif any(k in text_lower for k in ("react", "vue", "svelte", "tailwind", "next", "frontend", "ui")):
        angle = "前端工程化方向，关注开发体验或组件体系"
    elif any(k in text_lower for k in ("ctf", "pwn", "exploit", "vuln", "bounty", "hacking", "fuzz")):
        angle = "网络安全实战方向，常用于 CTF / 渗透测试 / 漏洞挖掘"
    elif any(k in text_lower for k in ("security", "scanner", "hardening")):
        angle = "通用安全工具方向，覆盖检测、加固或合规"
    else:
        angle = "近一周获得显著关注的开源项目"

    return (
        f"- 是什么：{desc}\n"
        f"- 为什么火：{angle}\n"
        f"- 技术栈：{lang} · Topics: {topics}\n"
        f"- 热度：{star_noun} · {repo.forks} Forks"
    )


# --------------------------------------------------------------------------- #
# Digest assembly                                                              #
# --------------------------------------------------------------------------- #

def build_digest(categories: dict[str, list[Repo]]) -> str:
    today = dt.date.today().isoformat()
    week_start = (dt.date.today() - dt.timedelta(days=WINDOW_DAYS)).isoformat()

    lines: list[str] = []
    lines.append(f"# GitHub 本周热门推荐 · {today}")
    lines.append("")
    lines.append(
        f"> 自动汇总 {week_start} ~ {today} 期间在以下方向获得显著关注的 GitHub 仓库："
        " AI/LLM、Web 开发、AI 编程助手、网络安全。"
    )
    lines.append("")

    # Summary table
    lines.append("## 本周概览")
    lines.append("")
    lines.append("| 分类 | 仓库数 | 综合热度（Star） |")
    lines.append("|------|--------|------------------|")
    for cat in CATEGORIES:
        repos = categories.get(cat["key"], [])
        if not repos:
            lines.append(f"| {cat['title']} | 0 | - |")
            continue
        total_stars = sum(r.stars for r in repos)
        lines.append(f"| {cat['title']} | {len(repos)} | {total_stars:,} |")
    lines.append("")

    # Per-category deep dive
    for cat in CATEGORIES:
        repos = categories.get(cat["key"], [])
        if not repos:
            continue
        lines.append(f"## {cat['emoji']} · {cat['title']}")
        lines.append("")
        for r in repos:
            lines.append(f"### [`{r.full_name}`]({r.html_url})")
            lines.append("")
            lines.append(describe(r))
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.append(f"_本报告由 WorkBuddy 自动化周任务自动生成于 {today}。_")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# PR flow (optional)                                                           #
# --------------------------------------------------------------------------- #

def git(*args: str, cwd: str | None = None) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=False
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr}")
    return out.stdout


def commit_to_main(workdir: Path, week_label: str, content: str) -> str:
    """Commit digest directly to the current branch (assumed main).

    Used by ``--commit-main`` mode (GitHub Actions). Assumes ``workdir`` is already
    a checked-out git working tree pointing at the desired target branch — no
    clone, no PR, no separate work branch.  Returns a short status string.
    """
    docs_dir = workdir / "weekly"
    docs_dir.mkdir(exist_ok=True)
    out_file = docs_dir / f"{week_label}.md"
    out_file.write_text(content, encoding="utf-8")

    # Update index README
    index = workdir / "README.md"
    if index.exists():
        existing = index.read_text(encoding="utf-8")
    else:
        existing = "# Weekly Trending Digest\n"
    new_section = f"- [{week_label}](weekly/{week_label}.md)"
    if new_section not in existing:
        if "## 历史周报" not in existing:
            existing += "\n## 历史周报\n\n" + new_section + "\n"
        else:
            existing = existing.rstrip() + "\n" + new_section + "\n"
        index.write_text(existing, encoding="utf-8")

    subprocess.run(["git", "config", "user.name", "weekly-trending-bot"],
                   cwd=str(workdir), check=False)
    subprocess.run(
        ["git", "config", "user.email", "weekly-trending-bot@users.noreply.github.com"],
        cwd=str(workdir), check=False,
    )

    subprocess.run(["git", "add", "weekly", "README.md"],
                   cwd=str(workdir), check=True)
    # Skip commit if nothing changed (same week re-run).
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(workdir), capture_output=True,
    )
    if diff.returncode == 0:
        return f"noop: nothing to commit for {week_label}"

    subprocess.run(
        ["git", "commit", "-m", f"weekly digest {week_label}"],
        cwd=str(workdir), check=True,
    )
    subprocess.run(["git", "push", "origin", "HEAD"],
                   cwd=str(workdir), check=True)
    return f"committed weekly/{week_label}.md to HEAD"


def push_digest(target_repo: str, content: str, week_label: str) -> str:
    """Clone target repo (shallow), write report into weekly/<label>.md, push branch,
    open PR.  Returns PR URL.  Handles brand-new (empty) repos by initialising main
    with a README so PRs always have a base."""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GH_TOKEN is required for --push mode")

    workdir = Path("/tmp/weekly-trending-work")
    if workdir.exists():
        subprocess.run(["rm", "-rf", str(workdir)], check=False)
    workdir.mkdir(parents=True)

    auth_url = (
        f"https://x-access-token:{token}@github.com/{target_repo}.git"
    )
    print(f"  -> Cloning {target_repo}", file=sys.stderr)
    subprocess.run(["git", "clone", auth_url, str(workdir)],
                   capture_output=True, text=True)

    # Decide: does upstream main exist? If not, this is a brand-new empty repo.
    ls_remote = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", "main"],
        cwd=str(workdir), capture_output=True, text=True,
    )
    upstream_has_main = bool((ls_remote.stdout or "").strip())

    if not upstream_has_main:
        print("  -> Empty repo detected, initialising main branch", file=sys.stderr)
        if not (workdir / ".git").exists():
            # Even git clone leaves us without a working tree on truly empty remotes.
            subprocess.run(["git", "init", "-b", "main"],
                           cwd=str(workdir), check=True)
            subprocess.run(["git", "remote", "add", "origin", auth_url],
                           cwd=str(workdir), check=True)
        else:
            # .git exists but main is unborn — switch to a real main locally.
            subprocess.run(["git", "checkout", "-b", "main"],
                           cwd=str(workdir), check=True,
                           capture_output=True)
        (workdir / "README.md").write_text(
            "# weekly-trending-digest\n\n"
            "Auto-generated weekly GitHub trending digest.\n\n"
            "Reports live under the `weekly/` directory, one Markdown file per ISO week.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "README.md"],
                       cwd=str(workdir), check=True)
        subprocess.run(
            ["git", "-c", "user.name=weekly-trending-bot",
             "-c", "user.email=weekly-trending-bot@users.noreply.github.com",
             "commit", "-m", "Initial commit"],
            cwd=str(workdir), check=True,
        )
        subprocess.run(["git", "push", "-u", "origin", "main"],
                       cwd=str(workdir), check=True)
        # Make sure GitHub picks main as the default branch.
        subprocess.run(
            ["gh", "repo", "edit", target_repo, "--default-branch", "main"],
            capture_output=True, text=True, check=False,
            env={**os.environ, "GH_TOKEN": token, "GITHUB_TOKEN": token},
        )
        # After first push, make sure the local main ref actually points at it.
        subprocess.run(["git", "checkout", "main"],
                       cwd=str(workdir), check=True)
    else:
        # Normal case: existing main, just switch to it.
        subprocess.run(["git", "checkout", "main"],
                       cwd=str(workdir), check=True)

    branch = f"weekly/{week_label}"
    git("checkout", "-B", branch, cwd=str(workdir))

    docs_dir = workdir / "weekly"
    docs_dir.mkdir(exist_ok=True)
    out_file = docs_dir / f"{week_label}.md"
    out_file.write_text(content, encoding="utf-8")

    # Update index README
    index = workdir / "README.md"
    if index.exists():
        existing = index.read_text(encoding="utf-8")
    else:
        existing = "# Weekly Trending Digest\n"
    new_section = f"- [{week_label}](weekly/{week_label}.md)"
    if new_section not in existing:
        if "## 历史周报" not in existing:
            existing += "\n## 历史周报\n\n" + new_section + "\n"
        else:
            existing = existing.rstrip() + "\n" + new_section + "\n"
        index.write_text(existing, encoding="utf-8")

    git("add", "weekly", "README.md", cwd=str(workdir))
    git("config", "user.name", "weekly-trending-bot", cwd=str(workdir))
    git("config", "user.email", "weekly-trending-bot@users.noreply.github.com", cwd=str(workdir))
    git("commit", "-m", f"weekly digest {week_label}", cwd=str(workdir))
    git("push", "origin", branch, "-u", cwd=str(workdir))

    # Open PR via gh CLI (so we get a sensible URL)
    title = f"Weekly trending digest · {week_label}"
    body = f"自动生成的本周热门仓库推荐（{week_label}）。\n\n详见 `weekly/{week_label}.md`。"
    result = subprocess.run(
        [
            "gh", "pr", "create",
            "--base", "main",
            "--head", branch,
            "--title", title,
            "--body", body,
            "--repo", target_repo,
        ],
        capture_output=True, text=True, check=False,
        env={**os.environ, "GH_TOKEN": token, "GITHUB_TOKEN": token},
    )
    if result.returncode != 0:
        print(f"  ! gh pr create failed: {result.stderr}", file=sys.stderr)
        return ""
    return result.stdout.strip()


# --------------------------------------------------------------------------- #
# Cleanup / audit                                                              #
# --------------------------------------------------------------------------- #

WORKDIR_GLOB = "/tmp/weekly-trending-*"


def audit() -> dict:
    """Return a snapshot of transient state on this machine."""
    state: dict = {"workdirs": [], "gh_token_in_env": False,
                   "git_configs_with_token": [], "pycaches": []}

    state["gh_token_in_env"] = bool(os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))

    for d in sorted(glob.glob(WORKDIR_GLOB)):
        info = {"path": d, "exists": os.path.isdir(d)}
        if info["exists"]:
            cfg = Path(d) / ".git" / "config"
            if cfg.exists():
                content = cfg.read_text(errors="replace")
                leak = ("ghp_" in content) or ("x-access-token" in content) or ("GITHUB_TOKEN" in content)
                info["git_config_leaks_token"] = leak
        state["workdirs"].append(info)

    for p in sorted(glob.glob("/workspace/**/__pycache__", recursive=True)) + \
             sorted(glob.glob("/tmp/**/__pycache__", recursive=True)):
        state["pycaches"].append(p)

    return state


def cleanup() -> dict:
    """Remove every transient artefact created during a run. Idempotent."""
    removed: list[str] = []
    errors: list[str] = []

    candidates: list[Path] = list(map(Path, glob.glob(WORKDIR_GLOB)))
    candidates += [Path("/workspace/weekly-trending-digest/__pycache__")]
    candidates += list(map(Path, glob.glob("/workspace/**/__pycache__", recursive=True)))

    seen: set[str] = set()
    for c in candidates:
        s = str(c)
        if s in seen:
            continue
        seen.add(s)
        if not c.exists():
            continue
        try:
            if c.is_dir():
                shutil.rmtree(c)
            else:
                c.unlink()
            removed.append(s)
        except Exception as e:
            errors.append(f"{s}: {e}")

    # Best-effort unset in current shell. Other shell sessions are out of reach.
    for k in ("GH_TOKEN", "GITHUB_TOKEN"):
        os.environ.pop(k, None)

    return {"removed": removed, "errors": errors}


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly GitHub Trending Digest")
    parser.add_argument("--push", action="store_true", help="Write report and open PR")
    parser.add_argument(
        "--target-repo",
        default=os.environ.get("TARGET_REPO", "oxiu720-cyber/weekly-trending-digest"),
        help="owner/repo to push the digest into",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print digest to stdout only"
    )
    parser.add_argument(
        "--audit", action="store_true",
        help="Audit transient state (workdirs, env vars, cache) and exit",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Remove transient state and exit (always runs as part of --push)",
    )
    parser.add_argument(
        "--commit-main", action="store_true",
        help="Commit digest straight to current HEAD (no PR). "
             "Used by GitHub Actions runner — assumes cwd is a checked-out repo.",
    )
    parser.add_argument(
        "--workdir",
        default=os.environ.get("GITHUB_WORKSPACE") or os.environ.get("WORKDIR") or os.getcwd(),
        help="Working directory for --commit-main (default: GITHUB_WORKSPACE or cwd)",
    )
    args = parser.parse_args()

    if args.audit:
        print(json.dumps(audit(), indent=2))
        return 0
    if args.clean:
        result = cleanup()
        print(json.dumps(result, indent=2))
        return 0 if not result["errors"] else 1

    seen: dict[str, Repo] = {}
    per_cat: dict[str, list[Repo]] = {}

    try:
        for cat in CATEGORIES:
            print(f"[*] Fetching category: {cat['title']}", file=sys.stderr)
            per_cat[cat["key"]] = collect_category(cat, seen)

        digest = build_digest(per_cat)

        if args.dry_run or (not args.push and not args.commit_main):
            print(digest)
            return 0

        week_label = dt.date.today().strftime("%Y-W%V")

        if args.commit_main:
            workdir = Path(args.workdir).resolve()
            if not (workdir / ".git").exists():
                raise RuntimeError(
                    f"--commit-main requires {workdir} to be a git working tree"
                )
            status = commit_to_main(workdir, week_label, digest)
            print(f"STATUS: {status}")
            return 0

        url = push_digest(args.target_repo, digest, week_label)
        print(f"PR: {url}")
        return 0 if url else 1
    finally:
        # Always clean transient artefacts at the end, success or failure.
        # (No-op for --commit-main in Actions where /tmp doesn't carry our files.)
        if not args.commit_main:
            cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
