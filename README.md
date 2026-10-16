# weekly-trending-digest

> 每周自动汇总 GitHub 在以下方向的热门仓库，由 **GitHub Actions** 自动生成并直接 commit 到 `main`：
> **AI / LLM / Agent** · **Web 开发** · **AI 编程助手** · **网络安全 / CTF**

## 文件结构

```
weekly-trending-digest/
├── generate_report.py         # 主脚本（标准库零依赖）
├── .github/workflows/
│   └── weekly.yml             # 每周五 17:00 (Asia/Shanghai) 自动跑
├── weekly/
│   └── YYYY-Www.md            # 每周一份历史报告
└── README.md
```

## 工作原理

1. `.github/workflows/weekly.yml` 在每周五 09:00 UTC = 北京时间 17:00 自动触发
2. Actions runner checkout main → `actions/setup-python@v5` 装 Python 3.11
3. 跑 `python3 generate_report.py --commit-main`：
   - 调用 GitHub Search API，按 `created:>=<7天前> stars:>阈值` 抓取近一周热门仓库
   - 按 4 个分类的话题（topic）做关键词筛选 + 去重
   - 对每个仓库生成中文简介（基于描述 / Topics / 名称启发式分析）
   - 渲染成 `weekly/<YYYY-Www>.md` 报告
5. 直接 commit 到 main（无需 PR），README 索引自动追加新行

凭据用 GitHub Actions 自动注入的 `secrets.GITHUB_TOKEN` —— **无需任何 PAT**。

## 触发时机

| 触发器 | 用途 |
|--------|------|
| `schedule: cron "0 9 * * 5"` | 周五 09:00 UTC = 北京时间周五 17:00 |
| `workflow_dispatch` | 手动触发（GitHub 网页 Actions 页面） |

## 手动跑一次

**方式 A：在 GitHub 网页上**

进入 https://github.com/oxiu720-cyber/weekly-trending-digest/actions/workflows/weekly.yml → 点 "Run workflow" → 等绿色 ✓

**方式 B：在本地**

```bash
# 仅查看报告（不推送）
python3.11 generate_report.py --dry-run

# 在 Actions runner 里（自动 commit 到 main）
python3.11 generate_report.py --commit-main --workdir .

# 旧版 PR 流程，需要 GH_TOKEN
export GH_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
python3.11 generate_report.py --push
```

## 状态查询

```bash
# 列出最近 5 次运行
gh run list -R weekly-trending-digest --workflow weekly.yml -L 5

# 看具体一次
gh run view <run-id> --log
```

## 历史报告

每周报告累积在 `weekly/` 目录下，README 顶部会自动列出索引。

---

由 WorkBuddy 协助搭建，2026-10-13 完成 GitHub Actions 迁移。
## 历史周报

- [2026-W42](weekly/2026-W42.md)
