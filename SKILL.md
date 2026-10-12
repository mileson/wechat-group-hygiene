---
name: wechat-group-hygiene
description: 从已核验的单群分析 JSON 生成离线成员复核工作台，集中查看消息证据、筛选候选、保留保护成员、记录人工跟进并准备公告草稿。此公开版本不采集微信、不自动判定或移除成员、不发送消息。
---

# Community Review Workbench / 社群成员复核工作台

## Read first

Read `references/review_workbench_contract.md` before preparing or changing a workbench. Read `docs/collection-boundaries.md` if the task mentions collecting data. Source collection and account actions are outside this release.

## Workflow

1. Ask for an already checked single-group analysis JSON. Do not read WeChat or invent members, message evidence, metrics, identity mappings, or upstream verification results.
2. Verify the reporting dates, current member baseline, complete pagination/message total, sender identity mappings, ambiguity, and this group's protection rules from the user's supplied evidence. Rendering alone cannot establish these checks.
3. Require a stable `chatroom_id` and a `group_name` in the JSON or explicit parameters. Never choose a default group. Any conflict between explicit identity and JSON must stop rendering.
4. Generate using the existing renderer instead of recreating a similar page:

   ```bash
   python3 -B scripts/render_review_workbench.py --analysis-json ./private-analysis.json --output-html ./private-review.html
   ```

5. Deliver the output file with the reporting period and any missing upstream checks. Do not report a candidate as a confirmed removal decision. The page only organizes classifications supplied by the source.
6. Explain that new, special-keep, and excluded members are review-only. Selection, handling marks, and announcements are local browser records; none execute account actions.
7. For an announcement, require actual counts and policy wording, then let the user inspect and copy it. No default invitation policy exists; no automatic sending is supported.

## Demo

`python3 -B scripts/demo.py` renders 12 fictional members. It is safe to use for demonstrations. Never replace public examples with actual community records.

## Protection and persistence

Use stable usernames rather than display names as identity. Do not merge ambiguous members. Treat unknown metrics as unknown; missing fields fail validation, never become zero.

The complete group ID and period isolate local state. Group-specific default filenames also include an ID digest. Opening a renamed or moved file, a different browser, or a private window may affect browser storage. There is no cloud synchronization or backup.

Do not create execution memories, personal configuration, real member lists, or chat excerpts inside this public skill directory. Keep private input and output outside the repository.

## Changes and verification

After editing the renderer, run:

```bash
python3 -B -m unittest discover -s tests -p 'test_render_review_workbench.py' -v
```

Node.js, when available, runs the included synthetic-DOM interaction tests. Tests never connect to WeChat or launch a browser; do not describe them as live account or browser visual verification. Keep README and input contracts aligned with actual behavior.
