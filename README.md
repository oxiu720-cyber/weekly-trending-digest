# weekly-trending-digest

> 每周自动汇总 GitHub 在以下方向的热门仓库，并推送到本仓库作为 PR：
> **AI / LLM / Agent** · **Web 开发** · **AI 编程助手** · **网络安全 / CTF**

## 文件结构

```
weekly-trending-digest/
├── generate_report.py   # 主脚本：抓取趋势 → 生成报告 → 推送 PR
└── README.md            # 本文件
```

## 工作原理

1. 调用 GitHub Search API，按 `created:>=<7天前> stars:>阈值` 抓取近一周热门仓库
2. 按 4 个分类的话题（topic）做关键词筛选 + 去重
3. 对每个仓库生成中文简介（基于描述 / Topics / 名称启发式分析）
4. 渲染成 Markdown 报告
5. clone 本仓库到 `/tmp/`，新建 `weekly/<YYYY-Www>.md` 分支、提交、`gh pr create`

## 怎么手动跑一次

```bash
# 仅查看报告（不推送）
python3.11 generate_report.py --dry-run

# 真正推送（需要 GH_TOKEN + 已创建本仓库）
export GH_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
python3.11 generate_report.py --push
```

## 怎么接入自动化

详见 `/root/.codebuddy/skills/automation-task-manager/`。

- Cron：`0 0 17 * * 5`（每周五 17:00）
- Frequency：`daily`
- Prompt：调用本脚本并打 PR

## 配置项

| 环境变量 | 必填 | 默认值 |
|---------|------|--------|
| `GH_TOKEN` / `GITHUB_TOKEN` | 推送时必填（PAT 需 `repo` scope） | — |
| `TARGET_REPO` | 否 | `oxiu720-cyber/weekly-trending-digest` |

## 第一次使用 checklist

- [ ] 在 `oxiu720-cyber` 下创建空仓库 `weekly-trending-digest`（不要勾选 README）
- [ ] 准备一个 PAT，开启 `repo` scope，把 token 配到 `GH_TOKEN` 环境变量
- [ ] 跑一次 `python3.11 generate_report.py --dry-run` 看报告内容
- [ ] 确认没问题后跑 `python3.11 generate_report.py --push`，应自动生成一个 PR
- [ ] 通过 automation-task-manager 配置每周五 17:00 自动跑
