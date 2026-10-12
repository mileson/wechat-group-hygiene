#!/usr/bin/env python3
# # 文件说明书 (File Manual)
# ## 核心功能 (Core Function)
# 将已核验的单群分析 JSON 渲染为可离线使用的净化候选与人工评审工作台。
# ## 输入 (Input)
# 分析 JSON 中的群 ID、群名、统计周期、成员状态、活动指标、消息证据和可选公告语境；可用命令行参数指定群身份与输出路径。
# ## 输出 (Output)
# 单文件 HTML，包含活跃榜、六列审查卡、自定义状态筛选、模块全选切换、证据弹窗、二级复核名单及可复制公告；无名单导出入口，本地状态按群 ID 和周期隔离。
# ## 定位 (Position)
# 本脚本是 wechat-group-hygiene 的独立离线渲染器，不执行微信采集、发消息或移除成员。
# ## 依赖 (Dependency)
# - Python 3 标准库：校验 JSON、转义内容并渲染 HTML。
# - references/review_workbench_contract.md：输入字段与审查边界。
# ## 维护规则 (Maintenance Rules)
# 1. 每次修改代码逻辑后，必须检查并更新上述的【核心功能】、【输入】、【输出】等信息，确保文档与代码一致。
# 2. 禁止修改或删除本【维护规则】章节的内容。
# 3. 修改完成后，必须扫描当前文件所在的文件夹目录，找到对应的 README 文档，并同步更新该 README 中关于本文件的描述信息；本 Skill 以 SKILL.md 和对应 reference 充当说明入口。

"""Render a local, review-only WeChat group hygiene workbench from validated analysis JSON."""

from __future__ import annotations

import argparse
import html
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

STATUSES = {
    "confirmed_inactive", "confirmed_low_invalid", "low_activity_needs_review",
    "low_activity_kept", "recent_joiner", "special_keep", "normal_activity", "excluded",
}
REQUIRED_ROW_KEYS = {
    "username", "display_name", "status", "status_label", "message_count",
    "valid_count", "invalid_count", "replies_sent", "has_direct_dialogue", "samples",
}


def js_literal(value: str) -> str:
    """Escape strings embedded in inline JavaScript, including closing script tags."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def safe_group_stem(group_name: str, chatroom_id: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", group_name).replace(" ", "").strip() or "微信群"
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", chatroom_id).strip("_")
    if not safe_id:
        raise ValueError("群 ID 不能用于安全文件名")
    return f"{name}_{safe_id}_{hashlib.sha256(chatroom_id.encode()).hexdigest()[:12]}"


def validate_payload(payload: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("分析数据必须是 JSON 对象")
    for field in ("chatroom_id", "group_name"):
        if field in payload and (not isinstance(payload[field], str) or not payload[field].strip()):
            raise ValueError(f"{field} 必须是非空文本")
    date_range = payload.get("date_range")
    if not isinstance(date_range, dict):
        raise ValueError("缺少 date_range")
    start, end = str(date_range.get("start", ""))[:10], str(date_range.get("end", ""))[:10]
    try:
        start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        raise ValueError("统计周期必须提供有效的 YYYY-MM-DD 起止日期") from exc
    if start_day > end_day:
        raise ValueError("统计开始日期不能晚于结束日期")
    rows, counts = payload.get("rows"), payload.get("status_counts")
    if not isinstance(rows, list) or not isinstance(counts, dict):
        raise ValueError("缺少 rows 或 status_counts")
    if counts.keys() - STATUSES:
        raise ValueError("status_counts 含有不受支持的成员状态")
    seen: set[str] = set()
    actual: Counter[str] = Counter()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or REQUIRED_ROW_KEYS - row.keys():
            raise ValueError(f"第 {index + 1} 位成员缺少工作台必需字段")
        username = row["username"]
        status = row["status"]
        if not isinstance(username, str) or not username or username in seen:
            raise ValueError(f"第 {index + 1} 位成员 username 缺失或重复")
        if status not in STATUSES:
            raise ValueError(f"第 {index + 1} 位成员 status 不受支持：{status}")
        if not isinstance(row["display_name"], str) or not isinstance(row["status_label"], str):
            raise ValueError(f"第 {index + 1} 位成员名称或状态标签不是文本")
        for key in ("message_count", "valid_count", "invalid_count", "replies_sent"):
            if type(row[key]) is not int or row[key] < 0:
                raise ValueError(f"第 {index + 1} 位成员 {key} 必须是非负整数")
        if not isinstance(row["has_direct_dialogue"], bool) or not isinstance(row["samples"], list):
            raise ValueError(f"第 {index + 1} 位成员互动或证据字段格式错误")
        for sample in row["samples"]:
            if (
                not isinstance(sample, dict)
                or not {"time", "quality", "text", "reason"} <= sample.keys()
                or any(not isinstance(sample[key], str) for key in ("time", "quality", "text", "reason"))
            ):
                raise ValueError(f"第 {index + 1} 位成员消息证据格式错误")
        ai_review = row.get("ai_review")
        if ai_review is not None and (
            not isinstance(ai_review, dict)
            or not {"recommendation", "reason"} <= ai_review.keys()
            or not all(isinstance(ai_review[key], str) for key in ("recommendation", "reason"))
        ):
            raise ValueError(f"第 {index + 1} 位成员 AI 复核字段格式错误")
        seen.add(username)
        actual[status] += 1
    for status in STATUSES:
        if type(counts.get(status, 0)) is not int or counts.get(status, 0) != actual[status]:
            raise ValueError(f"status_counts 与成员明细不一致：{status}")
    if type(payload.get("members_total")) is not int or payload["members_total"] != len(rows):
        raise ValueError("members_total 与成员明细不一致")
    announcement_context = payload.get("announcement_context")
    allowed_context = {"salutation", "member_noun", "community_label", "valid_rule", "invalid_rule", "closing", "policy_text"}
    if announcement_context is not None and (
        not isinstance(announcement_context, dict)
        or any(key not in allowed_context or not isinstance(value, str) for key, value in announcement_context.items())
    ):
        raise ValueError("announcement_context 仅支持预定义的文本字段")
    return start, end


def render_html(payload: dict[str, Any], output: Path, group_name: str, date_range: str, chatroom_id: str) -> None:
    validate_payload(payload)
    if not re.fullmatch(r"[A-Za-z0-9_@.-]+", chatroom_id) or not group_name.strip():
        raise ValueError("必须提供稳定群 ID 和群名称")
    if payload.get("chatroom_id") and str(payload["chatroom_id"]).strip() != chatroom_id:
        raise ValueError("群 ID 与分析 JSON 不一致")
    if payload.get("group_name") and str(payload["group_name"]).strip() != group_name:
        raise ValueError("群名称与分析 JSON 不一致")
    date_parts = payload["date_range"]
    # Full stable group identity and period isolate all browser state.
    storage_scope = f"{chatroom_id}::{date_parts['start'][:10].replace('-', '')}-{date_parts['end'][:10].replace('-', '')}"
    counts = payload["status_counts"]
    recent_joiner_note = "入群不足 24 小时，单独观察" if counts.get("recent_joiner", 0) else "暂无新成员记录"
    special_keep_option = "<option value='special_keep'>特殊保留</option>" if counts.get("special_keep", 0) else ""
    section_specs = [
        ("review_queue", "待审查成员", f"无发言候选 {counts.get('confirmed_inactive', 0)} 人 · 边界案例 {counts.get('low_activity_needs_review', 0)} 人", {"confirmed_inactive", "low_activity_needs_review"}),
        ("confirmed_low_invalid", "低活跃无效交流", "少量发言均被规则判为低信息量", {"confirmed_low_invalid"}),
        ("low_activity_kept", "低活跃但有有效交流", "已有具体提问、分享或其他有效内容", {"low_activity_kept"}),
        ("recent_joiner", "新成员保护", recent_joiner_note, {"recent_joiner"}),
        ("special_keep", "特殊保留成员", "保留观察，不进入净化候选", {"special_keep"}),
        ("normal_activity", "正常活跃成员", "本周期有持续群内交流", {"normal_activity"}),
        ("excluded", "长期豁免与管理成员", "不进入净化候选", {"excluded"}),
    ]

    def row_html(row: dict[str, Any]) -> str:
        samples = "".join(
            f"<li><time>{html.escape(str(s['time']))}</time><span class='q {html.escape(str(s['quality']))}'>{html.escape(s['quality'])}</span>"
            f"{html.escape(str(s['text']))}<small>{html.escape(s['reason'])}</small></li>"
            for s in row["samples"]
        ) or "<li class='empty'>本窗口无消息样本</li>"
        protected = row["status"] in {"recent_joiner", "special_keep", "excluded"}
        checkbox = (
            f"<input class='pick' type='checkbox' data-id='{html.escape(row['username'])}' "
            f"data-name='{html.escape(row['display_name'])}' data-status='{row['status']}' "
            f"aria-label='勾选 {html.escape(row['display_name'])}'>"
        )
        select_control = f"<label class='select-label'>{checkbox}<span>{'加入复核名单' if protected else '加入净化名单'}</span></label>"
        dialogue = "有引用互动" if row["has_direct_dialogue"] else "未检测到引用互动"
        ai_review = row.get("ai_review")
        ai_review_html = (
            f"<span class='ai-verdict'>{html.escape(ai_review['recommendation'])}</span>"
            if ai_review else ""
        )
        ai_review_detail = (
            f"<p class='ai-review'><strong>AI 复核依据</strong>{html.escape(ai_review['reason'])}</p>"
            if ai_review else ""
        )
        compact_status = {
            "recent_joiner": "新加入",
            "special_keep": "保留",
            "confirmed_inactive": "无发言",
            "confirmed_low_invalid": "无效",
            "low_activity_needs_review": "复核",
            "low_activity_kept": "保留",
            "normal_activity": "正常",
            "excluded": "排除",
        }.get(row["status"], row["status_label"])
        join_signal = f"<span class='join-time'>加入 {html.escape(str(row['joined_at']))}</span>" if row.get("joined_at") else ""
        evidence_count = len(row["samples"])
        evidence = (
            f"<button class='evidence-button' type='button' data-id='{html.escape(row['username'])}' "
            f"aria-label='查看 {html.escape(row['display_name'])} 的证据'>"
            f"查看证据 <span>{evidence_count} 条</span><svg viewBox='0 0 16 16' aria-hidden='true'><path d='m6 3 5 5-5 5'/></svg></button>"
            f"<template class='evidence-template'>{ai_review_detail}<ul class='evidence-list'>{samples}</ul></template>"
        )
        latest = row["samples"][-1]["text"] if row["samples"] else "统计周期内暂无群内发言"
        card_hint = {
            "recent_joiner": "处于新成员保护期",
            "special_keep": "配置为特殊保留，单独观察",
            "confirmed_inactive": "建议核对入群时间与特殊保留名单",
            "confirmed_low_invalid": "仅凭短句规则判断，需看原消息",
            "low_activity_needs_review": "需要结合上下文判断",
            "low_activity_kept": "已发现有效交流",
            "normal_activity": "持续参与群内交流",
            "excluded": "已列入豁免或管理成员",
        }[row["status"]]
        message_class = "message-positive" if row["message_count"] > 0 else ""
        valid_class = "valid-positive" if row["valid_count"] > 0 else ""
        invalid_class = "invalid-positive" if row["invalid_count"] > 0 else ""
        return f"""
        <article class='member' data-id='{html.escape(row['username'])}' data-status='{row['status']}' data-search='{html.escape((row['display_name'] + ' ' + row['username']).lower())}'>
          <div class='person-top'><div class='identity'><h3 title='{html.escape(row['display_name'])}'>{html.escape(row['display_name'])}</h3><code title='{html.escape(row['username'])}'>{html.escape(row['username'])}</code></div></div>
          <div class='person-state'><span class='badge {row['status']}' title='{html.escape(row['status_label'])}'>{html.escape(compact_status)}</span><span class='state-hint'>{html.escape(card_hint)}</span></div>
          <div class='metric-strip'><div><small>发言</small><b class='{message_class}'>{row['message_count']}</b></div><div><small>有效</small><b class='{valid_class}'>{row['valid_count']}</b></div><div><small>无效</small><b class='{invalid_class}'>{row['invalid_count']}</b></div><div><small>回复</small><b>{row['replies_sent']}</b></div></div>
          <div class='latest'><span>最近发言</span><p title='{html.escape(latest)}'>{html.escape(latest)}</p></div>
          <div class='signals'>{join_signal}<span class='dialogue'>{dialogue}</span>{ai_review_html}</div>
          <div class='card-foot'>{select_control}{evidence}</div>
        </article>"""

    sections = []
    for section_id, title, subtitle, statuses in section_specs:
        rows = [row for row in payload["rows"] if row["status"] in statuses]
        if section_id == "special_keep" and not rows:
            continue
        select_all = (
            f"<button class='section-select-all' type='button' data-section='{section_id}' "
            f"aria-label='全选{html.escape(title)}' aria-pressed='false'>全选</button>"
            if section_id in {"review_queue", "confirmed_low_invalid"} else ""
        )
        sections.append(
            f"<section id='{section_id}' class='member-section'><div class='section-heading'><div class='section-heading-main'><div class='section-title-row'><h2>{html.escape(title)}</h2><span class='section-count'>{len(rows)} 人</span>{select_all}</div><p>{html.escape(subtitle)}</p></div></div>"
            + "<div class='member-grid'>" + "".join(row_html(row) for row in rows)
            + "</div></section>"
        )
    leaderboard_rows = sorted(
        (row for row in payload["rows"] if row["message_count"] > 0),
        key=lambda row: (-row["message_count"], -row["valid_count"], row["username"]),
    )[:10]
    leaderboard_cards = []
    for rank, row in enumerate(leaderboard_rows, start=1):
        leaderboard_cards.append(
            f"<li class='leader-card {'leader-top' if rank <= 3 else ''}'>"
            f"<span class='leader-rank'>{rank:02d}</span>"
            f"<div class='leader-person'><strong title='{html.escape(row['display_name'])}'>{html.escape(row['display_name'])}</strong>"
            f"<code title='{html.escape(row['username'])}'>{html.escape(row['username'])}</code></div>"
            f"<div class='leader-volume'><strong>{row['message_count']}</strong><span>发言</span></div>"
            f"<div class='leader-detail'><span>有效 <b>{row['valid_count']}</b></span><span>回复 <b>{row['replies_sent']}</b></span></div>"
            "</li>"
        )
    leaderboard_html = (
        "<section id='leaderboard' class='leaderboard' aria-labelledby='leaderboardTitle'>"
        "<div class='leader-heading'><div><h2 id='leaderboardTitle'>发言活跃榜</h2>"
        "<p>本周期发言最多的 10 位成员 · 按发言数排序</p></div></div>"
        "<ol class='leader-grid'>" + ("".join(leaderboard_cards) or "<li class='leader-empty'>统计周期内暂无发言</li>") + "</ol>"
        "</section>"
    )
    icons = {
        "people": '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="9" cy="7" r="3.2"/><path d="M2.5 19v-1.1A5.9 5.9 0 0 1 8.4 12h1.2a5.9 5.9 0 0 1 5.9 5.9V19a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1Z"/><path d="M16.3 4.1a3.2 3.2 0 0 1 0 6.2 4.8 4.8 0 0 1 4.8 4.8V18h-3.6v-.1a8 8 0 0 0-3.2-6.4 5.4 5.4 0 0 0 2-7.4Z"/></svg>',
        "new": '<svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="11.5" cy="9.5" r="4.2" fill="currentColor"/><path d="M4 25v-2.1c0-5.1 3.1-8.3 7.5-8.3s7.5 3.2 7.5 8.3V25H4Z" fill="currentColor"/><circle cx="23.5" cy="23.5" r="6.2" fill="#eaf2ff"/><path d="M23.5 19.4v8.2M19.4 23.5h8.2" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>',
        "chat": '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 3C6.8 3 2.5 6.4 2.5 10.6c0 2.1 1.1 4 2.9 5.4L4.7 20l4.5-2.2c.9.2 1.8.3 2.8.3 5.2 0 9.5-3.4 9.5-7.6S17.2 3 12 3Zm-5 8a1.2 1.2 0 1 1 2.4 0A1.2 1.2 0 0 1 7 11Zm3.8 0a1.2 1.2 0 1 1 2.4 0 1.2 1.2 0 0 1-2.4 0Zm3.8 0a1.2 1.2 0 1 1 2.4 0 1.2 1.2 0 0 1-2.4 0Z"/></svg>',
        "alert": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9.5" fill="currentColor"/><path d="M10.9 6.7h2.2l-.3 8.2h-1.6l-.3-8.2Z" fill="#fff"/><circle cx="12" cy="17.6" r="1.2" fill="#fff"/></svg>',
        "shield": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 3.5 5.4v6.3c0 5.5 3.4 8.9 8.5 10.3 5.1-1.4 8.5-4.8 8.5-10.3V5.4L12 2Z" fill="currentColor"/><path d="m8.1 12.1 2.6 2.5 5-5.3" fill="none" stroke="#fff" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    }
    period_start = (payload.get("date_range") or {}).get("start", "")[:10]
    period_end = (payload.get("date_range") or {}).get("end", "")[:10]
    context = payload.get("announcement_context") or {}
    announcement_values = {
        "__ANNOUNCEMENT_SALUTATION__": context.get("salutation", "各位群友") + "，",
        "__ANNOUNCEMENT_MEMBER_NOUN__": context.get("member_noun", "成员"),
        "__ANNOUNCEMENT_COMMUNITY__": context.get("community_label", group_name),
        "__ANNOUNCEMENT_VALID_RULE__": context.get("valid_rule", "提问、解答、分享产品进展、分享行业见闻（含个人观点）"),
        "__ANNOUNCEMENT_INVALID_RULE__": context.get("invalid_rule", "纯打招呼、纯表情、纯附和、纯链接分享、无意义灌水"),
        "__ANNOUNCEMENT_CLOSING__": context.get("closing", "如有统计遗漏或身份疑问，请联系管理员核对。"),
        "__ANNOUNCEMENT_STORAGE_KEY__": "wechat-hygiene-announcement::" + storage_scope,
    }
    policy_default = context.get("policy_text", "")
    announcement_html = f"""
    <dialog id='announcementDialog' class='announcement-modal' aria-labelledby='announcementTitle'>
    <section id='announcement' class='announcement-workbench'>
      <div class='section-heading'><div><h2 id='announcementTitle'>群聊公告文案</h2></div><button id='closeAnnouncement' class='dialog-close' type='button' aria-label='关闭群公告弹窗'><svg viewBox='0 0 24 24' aria-hidden='true'><path d='M5 5 19 19M19 5 5 19'/></svg></button></div>
      <div class='announcement-grid'>
        <div class='announcement-form'>
          <div class='field-row'>
            <label>统计开始<input id='periodStart' type='text' inputmode='numeric' maxlength='10' placeholder='YYYY-MM-DD' value='{html.escape(period_start)}'></label>
            <label>统计结束<input id='periodEnd' type='text' inputmode='numeric' maxlength='10' placeholder='YYYY-MM-DD' value='{html.escape(period_end)}'></label>
          </div>
          <div class='field-row'>
            <label>实际净化人数<input id='removedCount' type='number' min='0' step='1' inputmode='numeric' placeholder='执行后填写'></label>
            <label>净化前群成员数<input id='beforeMembers' type='number' min='1' step='1' inputmode='numeric' placeholder='用于计算净化率'></label>
          </div>
          <div class='field-row'>
            <label>其中无自我介绍<input id='noIntroCount' type='number' min='0' step='1' inputmode='numeric' placeholder='填 0 或实际人数'></label>
            <label>其中无有效发言<input id='noValidCount' type='number' min='0' step='1' inputmode='numeric' placeholder='填 0 或实际人数'></label>
          </div>
          <label class='check-row'><input id='includePolicy' type='checkbox'>附上额外群规则</label>
          <label class='policy-label'>特事公告正文<textarea id='policyText' rows='3'>{html.escape(policy_default)}</textarea></label>
        </div>
        <div class='announcement-preview-panel'>
          <div class='preview-heading'><strong>群聊发送预览</strong><div class='rate-meta'><span id='rateView' class='rate-pill'>净化率 —</span><small>净化人数 ÷ 净化前人数 × 100%</small></div></div>
          <pre id='announcementPreview' aria-live='polite'></pre>
          <div class='preview-actions'><button id='copyAnnouncement' type='button'>复制群公告</button></div>
        </div>
      </div>
      <div id='announcementToast' class='announcement-toast' role='status' aria-live='polite' hidden></div>
    </section>
    </dialog>"""
    purge_view_html = """
    <main id='purgeView' hidden>
      <button id='backReview' class='back-button' type='button'>← 返回净化行动工作台</button>
      <div class='purge-heading-row'><div><h1>净化名单复核</h1></div></div>
      <div class='purge-overview'><span>已选 <strong id='selectedTotal'>0</strong> 人</span><span>待手工核对 <strong id='actionTotal'>0</strong> 人</span><span>已标记处理 <strong id='processedTotal'>0</strong> 人</span><span>仅供复核 <strong id='protectedTotal'>0</strong> 人</span></div>
      <section id='purgeActionSection' class='member-section'><div class='section-heading'><div class='section-heading-main'><div class='section-title-row'><h2>待手工核对</h2><span id='actionCount' class='section-count'>0 人</span><button id='purgeSelectAll' class='purge-select-all' type='button' aria-label='全选待手工核对成员的处理标记' aria-pressed='false'>全选</button></div></div></div><div id='purgeActionList' class='purge-grid'></div></section>
      <section id='purgeProtectedSection' class='member-section'><div class='section-heading'><div class='section-heading-main'><div class='section-title-row'><h2>保护成员 · 仅供复核</h2><span id='protectedCount' class='section-count'>0 人</span></div><p>新加入、特殊保留及长期豁免成员可以选中查看，但不进入待手工净化名单</p></div></div><div id='purgeProtectedList' class='purge-grid'></div></section>
      <div id='purgeEmpty' class='purge-empty' hidden>还没有勾选成员。返回工作台，点击成员卡片即可加入名单</div>
    </main>"""
    evidence_html = """
    <dialog id='evidenceDialog' class='announcement-modal evidence-modal' aria-labelledby='evidenceTitle'>
      <div class='evidence-shell'><div class='evidence-header'><div><span class='evidence-kicker'>MESSAGE EVIDENCE</span><h2 id='evidenceTitle'>成员证据</h2><p id='evidenceSubtitle'></p></div><button id='closeEvidence' class='dialog-close' type='button' aria-label='关闭证据弹窗'><svg viewBox='0 0 24 24' aria-hidden='true'><path d='M5 5 19 19M19 5 5 19'/></svg></button></div><div id='evidenceBody'></div></div>
    </dialog>"""
    announcement_script = """
const announcementKey = __ANNOUNCEMENT_STORAGE_KEY__;
const announcementIds = ['periodStart','periodEnd','removedCount','beforeMembers','noIntroCount','noValidCount','includePolicy','policyText'];
const announcementFields = Object.fromEntries(announcementIds.map(id => [id, document.getElementById(id)]));
try {
  const restored = JSON.parse(localStorage.getItem(announcementKey) || '{}');
  announcementIds.forEach(id => {
    if (!(id in restored)) return;
    if (announcementFields[id].type === 'checkbox') announcementFields[id].checked = Boolean(restored[id]);
    else announcementFields[id].value = String(restored[id]);
  });
} catch (_) {}
function checkedInt(id) {
  const value = announcementFields[id].value.trim();
  if (!/^\\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}
function noticeDate(value) {
  const match = /^(\\d{4})-(\\d{2})-(\\d{2})$/.exec(value.trim());
  if (!match) return '【待填】';
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  if (date.getFullYear() !== Number(match[1]) || date.getMonth() !== Number(match[2]) - 1 || date.getDate() !== Number(match[3])) return '【待填】';
  return match[1] + '.' + Number(match[2]) + '.' + Number(match[3]);
}
function makeAnnouncement() {
  const removed = checkedInt('removedCount');
  const before = checkedInt('beforeMembers');
  const noIntro = checkedInt('noIntroCount');
  const noValid = checkedInt('noValidCount');
  const start = announcementFields.periodStart.value;
  const end = announcementFields.periodEnd.value;
  const rate = removed !== null && before !== null && before > 0 ? (removed / before * 100).toFixed(1).replace(/\\.0$/, '') + '%' : '【待算】';
  const filled = value => value === null ? '【待填】' : String(value);
  const lines = [
    __ANNOUNCEMENT_SALUTATION__,
    '',
    '本轮成员复核已完成（统计周期：' + noticeDate(start) + '～' + noticeDate(end) + '），感谢各位' + __ANNOUNCEMENT_MEMBER_NOUN__ + '在' + __ANNOUNCEMENT_COMMUNITY__ + '中的交流与参与。',
    '',
    '📊 净化报告',
    '净化人数：' + filled(removed) + ' 人（其中 ' + filled(noIntro) + ' 人无自我介绍，' + filled(noValid) + ' 人无有效发言）',
    '净化率：' + rate,
    '',
    '📋 净化标准说明：',
    '• 有效互动包括：' + __ANNOUNCEMENT_VALID_RULE__,
    '• 无效互动包括：' + __ANNOUNCEMENT_INVALID_RULE__,
    '',
    __ANNOUNCEMENT_CLOSING__
  ];
  if (announcementFields.includePolicy.checked) {
    lines.push('', '⚠️ 特事公告：' + (announcementFields.policyText.value.trim() || '【待填】'));
  }
  document.getElementById('announcementPreview').textContent = lines.join('\\n');
  document.getElementById('rateView').textContent = '净化率 ' + rate;
  try {
    const state = Object.fromEntries(announcementIds.map(id => [id, announcementFields[id].type === 'checkbox' ? announcementFields[id].checked : announcementFields[id].value]));
    localStorage.setItem(announcementKey, JSON.stringify(state));
  } catch (_) {}
  return lines.join('\\n');
}
announcementIds.forEach(id => {
  announcementFields[id].addEventListener('input', makeAnnouncement);
  announcementFields[id].addEventListener('change', makeAnnouncement);
});
let announcementToastTimer;
function showAnnouncementToast(message, failed = false) {
  const toast = document.getElementById('announcementToast');
  toast.textContent = message;
  toast.classList.toggle('is-error', failed);
  toast.hidden = false;
  clearTimeout(announcementToastTimer);
  announcementToastTimer = setTimeout(() => { toast.hidden = true; }, 3200);
}
function fallbackCopy(message) {
  const scratch = document.createElement('textarea');
  scratch.value = message;
  scratch.style.position = 'fixed';
  scratch.style.opacity = '0';
  document.body.appendChild(scratch);
  scratch.focus();
  scratch.select();
  const copied = document.execCommand('copy');
  scratch.remove();
  if (!copied) throw new Error('copy failed');
}
document.getElementById('copyAnnouncement').addEventListener('click', async () => {
  const message = makeAnnouncement();
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(message);
    else fallbackCopy(message);
    showAnnouncementToast('已复制群公告，可粘贴到群聊发送');
  } catch (_) {
    try {
      fallbackCopy(message);
      showAnnouncementToast('已复制群公告，可粘贴到群聊发送');
    } catch (_) {
      showAnnouncementToast('复制失败，请手动选中预览文案', true);
    }
  }
});
makeAnnouncement();
"""
    announcement_script = re.sub(
        r"__ANNOUNCEMENT_[A-Z_]+__",
        lambda match: js_literal(announcement_values[match.group(0)]),
        announcement_script,
    )
    document = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(group_name)} 净化审查</title>
<style>
:root{{--bg:#f5f1e8;--paper:#fffdf8;--ink:#20201d;--muted:#777268;--line:#d9d1c1;--red:#ad392f;--amber:#a66a19;--green:#2d7354}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:13px/1.4 ui-rounded,"SF Pro Rounded","PingFang SC",sans-serif}}
main{{max-width:1800px;margin:auto;padding:24px 16px 56px}}h1{{font:700 28px/1.15 ui-serif,"Songti SC",serif;margin:0 0 5px}}.lead{{color:var(--muted);max-width:1060px;margin:0}}
.notice{{background:#fff4d9;border:1px solid #e8c675;padding:9px 12px;border-radius:9px;margin:14px 0}}.summary{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:12px 0}}
.summary div{{background:var(--paper);border:1px solid var(--line);border-radius:9px;padding:9px 12px}}.summary strong{{font-size:21px;display:inline;margin-right:7px}}.summary span{{color:var(--muted);font-size:12px}}
.tools{{position:sticky;top:0;z-index:3;background:rgba(245,241,232,.94);backdrop-filter:blur(8px);padding:8px 0;display:flex;gap:7px;flex-wrap:wrap}}
input[type=search]{{flex:1;min-width:220px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:white}}button{{border:0;border-radius:8px;background:#20201d;color:white;padding:8px 11px;cursor:pointer;font-size:12px}}
section{{margin-top:22px}}h2{{font-size:17px;margin:0 0 8px;border-bottom:1px solid var(--line);padding-bottom:6px}}h2 span{{font-weight:400;color:var(--muted)}}
.member-grid{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:7px;align-items:start}}
.member{{min-width:0;align-self:start;background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:9px;box-shadow:0 1px 0 rgba(56,45,25,.04)}}.member header{{display:flex;align-items:flex-start;gap:6px;min-width:0}}.identity{{min-width:0;flex:1}}.member h3{{margin:0;font-size:13px;line-height:1.25;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}code{{display:block;color:var(--muted);font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}}.badge{{flex:none;margin-left:auto;border-radius:999px;padding:2px 6px;font-size:10px;line-height:1.3;background:#ece8df}}
.badge.recent_joiner{{background:#dcebf5;color:#2c6483}}.badge.confirmed_inactive,.badge.confirmed_low_invalid{{background:#f7deda;color:var(--red)}}.badge.low_activity_needs_review{{background:#f7ebcc;color:var(--amber)}}.badge.low_activity_kept{{background:#dceee4;color:var(--green)}}
.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:3px;margin:7px 0}}.metrics b{{background:#f3efe7;padding:4px 2px;border-radius:5px;text-align:center;font-size:14px;line-height:1.1}}.metrics small{{display:block;font-size:8px;color:var(--muted);font-weight:400;margin-top:2px}}
.signals{{display:flex;gap:4px;align-items:center;min-height:18px;overflow:hidden}}.dialogue,.ai-verdict,.join-time{{display:inline-block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-radius:5px;padding:2px 5px;font-size:9px;background:#eeebe4;color:var(--muted)}}.join-time{{background:#e2f0f8;color:#2c6483}}.ai-verdict{{background:#e8edf5;color:#4b5873}}details{{margin-top:5px;border-top:1px dashed var(--line);padding-top:4px}}summary{{cursor:pointer;color:#655f55;font-size:10px;user-select:none}}.ai-review{{background:#edf0f5;border-left:2px solid #65718b;padding:6px 7px;border-radius:4px;font-size:10px}}.ai-review strong{{display:block}}ul{{margin:5px 0 0;padding-left:14px}}li{{margin:5px 0;font-size:10px;overflow-wrap:anywhere}}li time{{display:block;color:var(--muted);font-size:9px}}li small{{display:block;color:var(--muted)}}.q{{font-size:8px;border-radius:4px;padding:1px 4px;margin-right:4px;background:#eee}}.q.valid{{color:var(--green)}}.q.invalid{{color:var(--red)}}.pick{{flex:none;width:16px;height:16px;margin:1px 0 0}}.hidden{{display:none}}footer{{margin-top:28px;color:var(--muted)}}
@media(max-width:1200px){{.member-grid{{grid-template-columns:repeat(4,minmax(0,1fr))}}}}@media(max-width:820px){{.member-grid{{grid-template-columns:repeat(3,minmax(0,1fr))}}}}@media(max-width:620px){{.summary{{grid-template-columns:repeat(2,1fr)}}.member-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:420px){{.member-grid{{grid-template-columns:1fr}}}}
/* A 方向：延续参考工作台的浅灰底、白卡、细边框和低阴影。 */
:root{{--bg:#f8fafc;--paper:#fff;--ink:#1f252d;--muted:#718093;--line:#e5eaf0;--red:#bd5d50;--amber:#c96b39;--green:#23835a;--blue:#3179c4}}
html{{scroll-behavior:smooth}}body{{background:var(--bg);font:14px/1.48 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;-webkit-font-smoothing:antialiased}}
main{{max-width:1900px;padding:28px 28px 72px}}.page-header{{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;margin-bottom:22px}}
.eyebrow{{display:block;color:var(--green);font-size:11px;font-weight:800;letter-spacing:.14em;margin-bottom:7px}}h1{{font:760 clamp(26px,2vw,36px)/1.16 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;letter-spacing:-.025em;margin:0}}
.lead{{margin:8px 0 0;color:#657384;font-size:13px;max-width:1080px}}.date-stamp{{flex:none;display:flex;align-items:center;gap:10px;border:1px solid var(--line);border-radius:11px;background:#fff;padding:11px 14px;color:#526174;font-size:12px;box-shadow:0 2px 8px rgba(31,37,45,.025)}}.date-stamp strong{{display:block;color:var(--ink);font-size:12px}}
.summary{{grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:0 0 18px}}.summary .summary-card{{display:flex;align-items:center;gap:12px;min-height:96px;padding:18px;border:1px solid var(--line);border-radius:12px;box-shadow:0 3px 14px rgba(31,37,45,.028)}}
.summary-icon{{flex:none;display:grid;place-items:center;width:42px;height:42px;border-radius:50%;background:#eaf5ef;color:var(--green);font-size:20px;font-weight:750}}.summary-icon.blue{{background:#ebf3ff;color:var(--blue)}}.summary-icon.orange{{background:#fff0e7;color:var(--amber)}}.summary-icon.red{{background:#fcebe9;color:var(--red)}}.summary-card strong{{font-size:28px;line-height:1;display:block;margin:0 0 6px;letter-spacing:-.035em}}.summary-card span.label{{color:#4b5868;font-size:12px;font-weight:700}}.summary-card small{{display:block;margin-top:4px;color:#8a95a3;font-size:10px}}
.tools{{top:0;z-index:4;border:1px solid var(--line);border-radius:11px;background:rgba(255,255,255,.96);box-shadow:0 4px 16px rgba(31,37,45,.04);padding:10px;gap:8px;margin-bottom:14px}}.tools input[type=search]{{min-width:240px;max-width:520px;border-radius:8px;padding:10px 12px;font-size:13px}}.tools select{{border:1px solid var(--line);border-radius:8px;background:#fff;color:#475465;padding:9px 11px;font:inherit;font-size:12px}}.tools button,.tools a{{display:inline-flex;align-items:center;justify-content:center;min-height:36px;border:1px solid var(--line);border-radius:8px;background:#fff;color:#485466;font-size:12px;font-weight:700;padding:8px 12px;text-decoration:none;cursor:pointer}}.tools button:hover,.tools a:hover{{background:#f3f6f8}}.tools .primary-action{{margin-left:auto;border-color:var(--green);background:var(--green);color:#fff}}.tools .primary-action:hover{{background:#1b704d}}
.notice{{background:#f0f7f3;border:1px solid #d6e9dc;border-radius:9px;color:#4c6558;font-size:12px;margin:0 0 22px;padding:10px 14px}}.member-section{{margin-top:28px}}.section-heading{{display:flex;align-items:center;justify-content:space-between;gap:16px;border-bottom:1px solid var(--line);padding:0 0 10px;margin:0 0 12px;position:relative}}.section-heading::before{{content:"";position:absolute;left:0;bottom:-1px;width:35px;height:3px;border-radius:3px;background:var(--green)}}#confirmed_inactive .section-heading::before,#confirmed_low_invalid .section-heading::before{{background:var(--amber)}}#low_activity_needs_review .section-heading::before{{background:var(--blue)}}.section-heading h2{{border:0;margin:0;padding:0;font-size:18px;line-height:1.2;color:var(--ink)}}.section-heading p{{margin:5px 0 0;color:#8995a2;font-size:11px}}.section-count{{flex:none;border-radius:999px;background:#edf3f0;color:var(--green);padding:4px 10px;font-size:11px;font-weight:750}}#confirmed_inactive .section-count,#confirmed_low_invalid .section-count{{background:#fff2e9;color:var(--amber)}}
.member-grid{{gap:10px}}.member{{border-color:var(--line);border-radius:10px;padding:13px;box-shadow:0 3px 13px rgba(31,37,45,.035);transition:transform .14s ease,box-shadow .14s ease,border-color .14s ease}}.member:hover{{transform:translateY(-2px);box-shadow:0 8px 22px rgba(31,37,45,.075)}}.member:has(.pick:checked){{border-color:#92cdb0;background:#f9fdfb}}.person-top{{display:flex;align-items:center;gap:9px;min-width:0}}.person-avatar{{flex:none;display:grid;place-items:center;width:34px;height:34px;border-radius:50%;background:#ebf0f5;color:#657386;font-size:14px;font-weight:800}}.person-avatar.recent_joiner,.person-avatar.excluded{{background:#e3f4eb;color:var(--green)}}.person-avatar.confirmed_inactive,.person-avatar.confirmed_low_invalid{{background:#fff0e7;color:var(--amber)}}.identity h3{{font-size:13px;font-weight:750;max-width:100%}}.identity code{{font-size:9px;color:#99a4af}}
.person-state{{display:flex;align-items:center;gap:6px;min-width:0;margin:10px 0 9px}}.state-hint{{color:#8a96a2;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.badge{{margin:0;padding:3px 8px;font-size:10px;font-weight:750}}.badge.recent_joiner,.badge.excluded,.badge.low_activity_kept{{background:#e2f4ea;color:var(--green)}}.badge.confirmed_inactive,.badge.confirmed_low_invalid{{background:#fff0e7;color:var(--amber)}}.badge.low_activity_needs_review{{background:#eaf2ff;color:var(--blue)}}
.metric-strip{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:8px 0}}.metric-strip div{{text-align:center;border-right:1px solid var(--line)}}.metric-strip div:last-child{{border-right:0}}.metric-strip small{{display:block;color:#8b98a6;font-size:10px}}.metric-strip b{{display:block;margin-top:2px;font-size:15px;line-height:1.1}}.mini-metrics{{color:#9aa4ae;font-size:10px;margin:6px 0 0}}.latest{{min-height:53px;margin-top:8px}}.latest span{{font-size:10px;color:#9aa4ae}}.latest p{{margin:3px 0 0;color:#526071;font-size:11px;line-height:1.4;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;overflow-wrap:anywhere}}.signals{{margin:6px 0 0;min-height:17px}}.signals .dialogue,.signals .ai-verdict,.signals .join-time{{font-size:9px;background:#f2f5f7;color:#8090a0}}.signals .ai-verdict{{background:#edf2fa;color:#5171a2}}.signals .join-time{{background:#eaf6ee;color:var(--green)}}.card-foot{{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:4px;border-top:1px solid var(--line);margin-top:9px;padding-top:8px;min-height:24px}}.select-label{{display:flex;align-items:center;gap:5px;color:#627083;font-size:10px;cursor:pointer;white-space:nowrap}}.select-label .pick{{width:15px;height:15px;accent-color:var(--green)}}.protected-label{{color:#a0aab3;font-size:10px}}.card-foot details{{margin:0;padding:0;border:0;min-width:0}}.card-foot details[open]{{flex-basis:100%;border-top:1px dashed var(--line);padding-top:8px;margin-top:4px}}.card-foot summary{{font-size:10px;color:#536274;font-weight:700;white-space:nowrap}}.card-foot li{{font-size:11px}}.card-foot li time{{font-size:10px}}
.announcement-workbench{{margin:34px 0;padding:0}}.announcement-grid{{display:grid;grid-template-columns:minmax(340px,.9fr) minmax(0,1.1fr);gap:12px}}.announcement-form,.announcement-preview-panel{{border:1px solid var(--line);border-radius:11px;background:#fff;box-shadow:0 3px 14px rgba(31,37,45,.028);padding:18px}}.field-row{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:11px}}.announcement-form label:not(.check-row){{display:block;color:#5d6b7b;font-size:11px;font-weight:700}}.announcement-form input[type=date],.announcement-form input[type=number],.announcement-form textarea{{display:block;width:100%;margin-top:5px;border:1px solid #dce3ea;border-radius:8px;padding:9px 10px;background:#fff;color:var(--ink);font:inherit;font-size:12px}}.announcement-form input:focus,.announcement-form textarea:focus{{outline:2px solid #b4dfc8;outline-offset:0}}.form-note{{color:#8895a2;font-size:10px;margin:4px 0 12px}}.check-row{{display:flex;align-items:center;gap:7px;color:#4a5969;font-size:12px;font-weight:650;margin:10px 0;cursor:pointer}}.check-row input{{accent-color:var(--green);width:15px;height:15px;flex:none}}.policy-label{{margin-top:8px}}.announcement-form textarea{{resize:vertical;min-height:68px;line-height:1.55}}.confirm-row{{border-top:1px solid var(--line);padding-top:12px;margin-top:13px}}.preview-heading{{display:flex;align-items:center;justify-content:space-between;gap:12px}}.preview-heading strong{{display:block;font-size:14px}}.preview-heading span{{display:block;color:#98a3af;font-size:10px;margin-top:3px}}.rate-pill{{flex:none;border-radius:999px;background:#e9f5ed;color:var(--green);padding:5px 8px;font-size:10px;font-weight:750}}#announcementPreview{{margin:14px 0 10px;padding:14px;border:1px solid var(--line);border-radius:8px;background:#fbfcfd;color:#3c4857;white-space:pre-wrap;overflow:auto;max-height:370px;min-height:220px;font:12px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}}.preview-actions{{display:flex;align-items:center;justify-content:space-between;gap:10px}}#announcementHint{{color:#84909d;font-size:11px}}#copyAnnouncement{{border:0;border-radius:8px;padding:10px 15px;background:var(--green);color:#fff;font-size:12px;font-weight:750;cursor:pointer}}#copyAnnouncement:disabled{{background:#dce3e8;color:#929eaa;cursor:not-allowed}}
@media(max-width:1440px){{.member-grid{{grid-template-columns:repeat(4,minmax(0,1fr))}}}}@media(max-width:1100px){{.summary{{grid-template-columns:repeat(3,minmax(0,1fr))}}.announcement-grid{{grid-template-columns:1fr}}}}@media(max-width:850px){{.page-header{{flex-direction:column}}.date-stamp{{width:100%}}.member-grid{{grid-template-columns:repeat(3,minmax(0,1fr))}}.tools .primary-action{{margin-left:0}}}}@media(max-width:640px){{main{{padding:18px 12px 50px}}.summary{{grid-template-columns:repeat(2,minmax(0,1fr))}}.summary .summary-card{{min-height:82px;padding:12px}}.member-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.field-row{{grid-template-columns:1fr}}.tools input[type=search]{{max-width:none;width:100%}}}}@media(max-width:440px){{.member-grid{{grid-template-columns:1fr}}}}
.summary .summary-card > div{{min-width:0;border:0;border-radius:0;background:transparent;box-shadow:none;padding:0}}
#review_queue .section-heading::before{{background:var(--amber)}}#review_queue .section-count{{background:#fff2e9;color:var(--amber)}}
@media(min-width:1101px){{.member-grid{{grid-template-columns:repeat(6,minmax(0,1fr))}}}}
.summary-icon svg{{display:block;width:22px;height:22px;fill:currentColor}}
.summary .summary-icon{{width:52px;height:52px;background:#e8f6ee;color:#168c59}}
.summary .summary-icon.blue{{background:#eaf2ff;color:#2c7fdf}}
.summary .summary-icon.orange,.summary .summary-icon.red{{background:#fff0e6;color:#dc6e2a}}
.summary .summary-icon svg{{width:28px;height:28px;fill:currentColor}}
.summary .summary-icon.blue svg{{width:30px;height:30px}}
.metric-strip b.invalid-positive{{color:#d84a46}}
.badge.special_keep{{background:#e2f4ea;color:var(--green)}}
.metric-strip b.message-positive{{color:#2c7fdf}}
.metric-strip b.valid-positive{{color:#168c59}}
.page-header{{margin-bottom:24px}}.page-header .lead{{margin-top:10px}}.tools{{margin-bottom:25px}}
.tools{{position:static;top:auto;z-index:auto;border:0;border-radius:0;background:transparent;box-shadow:none;backdrop-filter:none;padding:0}}
.section-heading-main{{min-width:0}}.section-title-row{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}.section-title-row .section-count{{margin:0}}
#review_queue .section-heading-main,#confirmed_low_invalid .section-heading-main,#purgeActionSection .section-heading-main{{flex:1}}
.section-select-all,.purge-select-all{{flex:none;margin-left:auto;padding:6px 12px;border:1px solid #c9ddf9;border-radius:7px;background:#f3f8ff;color:#216cb9;font:inherit;font-size:12px;font-weight:750;cursor:pointer}}.section-select-all:hover,.purge-select-all:hover{{background:#eaf2ff}}.section-select-all:focus-visible,.purge-select-all:focus-visible{{outline:2px solid var(--blue);outline-offset:2px}}
.purge-select-all:disabled{{opacity:.45;cursor:not-allowed}}
html.modal-open,body.modal-open{{overflow:hidden}}
.announcement-modal{{width:min(1080px,calc(100vw - 36px));max-width:none;max-height:min(92vh,920px);padding:0;border:1px solid #dce3ea;border-radius:14px;background:var(--bg);color:var(--ink);box-shadow:0 28px 80px rgba(18,31,44,.2);overflow:auto}}
.announcement-form input[type=text]{{display:block;width:100%;margin-top:5px;border:1px solid #dce3ea;border-radius:8px;padding:9px 10px;background:#fff;color:var(--ink);font:inherit;font-size:12px;font-variant-numeric:tabular-nums}}
.rate-meta{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}}
.rate-meta small{{color:#8c99a6;font-size:10px}}
.preview-heading .rate-pill{{display:inline-flex;align-items:center;margin:0;color:var(--green);font-size:10px}}
.preview-actions{{justify-content:flex-end}}
.dialog-close svg{{display:block;width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:2.3;stroke-linecap:round}}
.announcement-toast{{position:sticky;bottom:12px;width:max-content;max-width:calc(100% - 40px);margin:12px auto 0;padding:9px 14px;border-radius:8px;background:#e6f5ec;color:#176342;font-size:12px;font-weight:700;box-shadow:0 5px 16px rgba(15,70,43,.12)}}
.announcement-toast.is-error{{background:#fff0eb;color:#af4b35}}
.announcement-toast[hidden]{{display:none}}
.announcement-modal::backdrop{{background:rgba(24,34,45,.55);backdrop-filter:blur(3px)}}
.announcement-modal .announcement-workbench{{margin:0;padding:22px}}.announcement-modal .section-heading{{margin-bottom:16px}}.dialog-close{{display:flex;align-items:center;justify-content:center;flex:none;width:34px;height:34px;padding:0;border:1px solid var(--line);border-radius:8px;background:#fff;color:#687686;line-height:0;cursor:pointer}}.dialog-close:hover{{background:#eef2f5;color:var(--ink)}}
@media(max-width:760px){{.announcement-modal{{width:calc(100vw - 18px);max-height:calc(100vh - 18px)}}.announcement-modal .announcement-workbench{{padding:13px}}.announcement-modal .announcement-grid{{grid-template-columns:1fr}}}}
.tools input[type=search]{{flex:0 1 270px;width:270px;min-width:180px;max-width:270px}}.tools .go-purge{{border-color:#c9ddf9;background:#eaf2ff;color:#216cb9;font-weight:800}}.tools .go-purge:hover:not(:disabled){{background:#daeaff;color:#155d9f}}.tools .go-purge:disabled{{opacity:.45;cursor:not-allowed}}
.member{{cursor:pointer}}.member:focus-within{{border-color:#a8cdef}}.card-foot .evidence-button{{display:inline-flex;align-items:center;gap:5px;padding:5px 7px;border:1px solid #d6e5f6;border-radius:6px;background:#f3f8ff;color:#286dae;font-size:10px;font-weight:750;white-space:nowrap;cursor:pointer}}.card-foot .evidence-button:hover{{background:#e8f2ff;border-color:#a7c9ed}}.evidence-button span{{font-size:9px;color:#6d8eaf}}.evidence-button svg{{width:10px;height:10px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}}
.evidence-modal{{width:min(680px,calc(100vw - 28px));max-height:84vh}}.evidence-shell{{padding:20px}}.evidence-header{{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;border-bottom:1px solid var(--line);padding-bottom:14px}}.evidence-kicker{{color:var(--blue);font-size:10px;letter-spacing:.12em;font-weight:800}}.evidence-header h2{{margin:5px 0;font-size:22px}}.evidence-header p{{margin:0;color:var(--muted);font-size:12px}}#evidenceBody{{max-height:60vh;overflow:auto}}#evidenceBody .ai-review{{font-size:12px;line-height:1.55;margin:16px 0;padding:10px 12px}}.evidence-list{{list-style:none;margin:0;padding:0}}.evidence-list li{{border-bottom:1px solid var(--line);padding:13px 2px;margin:0;font-size:13px;line-height:1.55;overflow-wrap:anywhere}}.evidence-list time{{display:block;color:var(--muted);font-size:11px;margin-bottom:6px}}.evidence-list small{{display:block;color:#798795;font-size:11px;margin-top:6px}}.evidence-list .q{{display:inline-block;font-size:10px;margin-right:8px;padding:3px 6px;border-radius:5px;background:#eef3f7}}
#purgeView{{min-height:100vh}}.back-button{{border:0;background:transparent;color:#516576;padding:4px 0 18px;font-size:12px;font-weight:750;cursor:pointer}}.back-button:hover{{color:var(--blue)}}.purge-heading-row{{display:flex;justify-content:space-between;gap:20px;align-items:flex-end}}.purge-heading-row p{{color:var(--muted);font-size:12px;margin:8px 0 0}}.purge-kicker{{display:block;color:var(--blue);font-size:10px;font-weight:850;letter-spacing:.14em;margin-bottom:8px}}.purge-overview{{display:flex;flex-wrap:wrap;gap:10px;margin:22px 0}}.purge-overview span{{border:1px solid var(--line);border-radius:9px;background:#fff;padding:10px 13px;color:#6a7888;font-size:12px}}.purge-overview strong{{font-size:19px;color:var(--ink);margin:0 3px}}.purge-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;align-items:start}}.purge-card .card-foot{{justify-content:space-between}}.purge-card .select-label{{display:none}}.purge-card .processed-label{{display:inline-flex;align-items:center;gap:5px;color:var(--green);font-size:11px;font-weight:750;cursor:pointer}}.purge-card .processed-label input{{accent-color:var(--green)}}.purge-card .remove-selected{{border:0;background:transparent;color:#8493a2;font-size:10px;cursor:pointer}}.purge-card .remove-selected:hover{{color:#bd5d50}}.purge-card.protected{{border-color:#cee9d9;background:#fbfefc}}.purge-card .protection-note{{color:var(--green);font-size:10px;font-weight:700}}.purge-empty{{border:1px dashed #cbd7e2;border-radius:10px;background:#fff;padding:36px;text-align:center;color:var(--muted);margin-top:26px}}
@media(max-width:1000px){{.purge-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:640px){{.tools input[type=search]{{flex:1 1 100%;width:100%;max-width:none}}.purge-grid{{grid-template-columns:1fr}}.purge-heading-row{{align-items:stretch;flex-direction:column}}}}
#purgeView .purge-grid{{grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}}
#purgeView .purge-card{{padding:10px}}
#purgeView .purge-card .latest{{display:none}}
#purgeView .purge-card .person-state{{margin:8px 0 7px}}
#purgeView .purge-card .metric-strip{{padding:6px 0}}
#purgeView .purge-card .signals{{margin:6px 0 0}}
#purgeView .purge-card .card-foot{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px 5px;margin-top:6px;padding-top:6px}}
#purgeView .purge-card .processed-label,#purgeView .purge-card .protection-note{{grid-column:1;grid-row:1;min-width:0}}
#purgeView .purge-card .evidence-button{{grid-column:2;grid-row:1;justify-self:end}}
#purgeView .purge-card .processed-label,#purgeView .purge-card .protection-note,#purgeView .purge-card .remove-selected{{font-size:9px}}
#purgeView .purge-card .remove-selected{{grid-column:2;grid-row:2;justify-self:end;border:1px solid #f3d5d1;border-radius:6px;background:#fff0ee;color:#b6564c;padding:5px 9px;font-weight:700}}
#purgeView .purge-card .remove-selected:hover{{background:#ffe3df;border-color:#eab9b2;color:#9e4037}}
#purgeView .purge-card .remove-selected:focus-visible{{outline:2px solid #bd5d50;outline-offset:2px}}
#purgeView .purge-card:not(.protected){{cursor:pointer}}
#purgeView .purge-card.processed{{background:#f2faf4;border-color:#a8d4b5;box-shadow:0 4px 16px rgba(35,131,90,.09)}}
#purgeView .purge-card.protected{{cursor:default;background:#fff;border-color:var(--line)}}
@media(max-width:1350px){{#purgeView .purge-grid{{grid-template-columns:repeat(4,minmax(0,1fr))}}}}
@media(max-width:850px){{#purgeView .purge-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:560px){{#purgeView .purge-grid{{grid-template-columns:1fr}}}}
.leaderboard{{margin:0 0 18px}}
.leader-heading{{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin:0 0 9px}}
.leader-heading h2{{margin:0;color:var(--ink);font-size:17px;line-height:1.2}}
.leader-heading p{{margin:4px 0 0;color:#8795a4;font-size:11px}}
.leader-grid{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px;list-style:none;margin:0;padding:0}}
.leader-card{{display:grid;grid-template-columns:27px minmax(0,1fr) auto;grid-template-rows:auto auto;align-items:start;gap:4px 8px;min-width:0;min-height:92px;padding:10px 11px;border:1px solid var(--line);border-radius:10px;background:#fff;box-shadow:0 2px 10px rgba(31,37,45,.025)}}
.leader-card.leader-top{{border-color:#c8e4d3;background:#fcfefd}}
.leader-rank{{display:grid;place-items:center;grid-row:1/3;width:26px;height:26px;border-radius:7px;background:#edf2f5;color:#647789;font-size:11px;font-weight:850;font-variant-numeric:tabular-nums}}
.leader-top .leader-rank{{background:#e0f3e8;color:var(--green)}}
.leader-person{{grid-column:2;grid-row:1;min-width:0}}
.leader-person strong,.leader-person code{{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.leader-person strong{{font-size:12px;line-height:1.3}}
.leader-person code{{margin-top:2px;color:#97a4b1;font-size:9px}}
.leader-volume{{grid-column:3;grid-row:1/3;align-self:center;text-align:right;white-space:nowrap}}
.leader-volume strong{{display:block;color:var(--blue);font-size:19px;line-height:1.1;font-variant-numeric:tabular-nums}}
.leader-volume span{{color:#8e9ba8;font-size:10px}}
.leader-detail{{display:flex;gap:10px;grid-column:2;grid-row:2;color:#8896a4;font-size:10px;white-space:nowrap}}
.leader-detail b{{color:var(--green);font-weight:800}}
.leader-empty{{grid-column:1/-1;padding:18px;border:1px dashed var(--line);border-radius:10px;color:#8291a0;text-align:center}}
@media(max-width:1050px){{.leader-grid{{grid-template-columns:repeat(4,minmax(0,1fr))}}}}
@media(max-width:800px){{.leader-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:520px){{.leader-grid{{grid-template-columns:1fr}}}}
.status-filter-control{{position:relative;flex:none;width:176px}}
.tools .status-filter-trigger{{width:100%;justify-content:space-between;gap:16px;padding:9px 12px;background:#fff;color:#475465;font-weight:650;text-align:left}}
.status-filter-trigger span:first-child{{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.status-filter-chevron{{flex:none;width:7px;height:7px;margin-right:2px;margin-top:-4px;border-right:1.6px solid #718093;border-bottom:1.6px solid #718093;transform:rotate(45deg)}}
.status-filter-trigger[aria-expanded=true]{{border-color:#a8cdb9;background:#f9fdfb;box-shadow:0 0 0 3px rgba(35,131,90,.08)}}
.status-filter-trigger[aria-expanded=true] .status-filter-chevron{{margin-top:3px;transform:rotate(225deg)}}
.status-filter-menu{{position:absolute;top:calc(100% + 6px);left:0;z-index:10;width:100%;margin:0;padding:5px;border:1px solid #dce5e0;border-radius:10px;background:#fff;box-shadow:0 10px 32px rgba(31,37,45,.12)}}
.tools .status-filter-option{{display:flex;width:100%;min-height:35px;justify-content:space-between;gap:10px;margin:0;border:0;border-radius:6px;background:transparent;padding:8px 9px;color:#526174;font-size:12px;font-weight:500;text-align:left}}
.tools .status-filter-option:hover,.tools .status-filter-option:focus-visible{{background:#f1f5f4;color:var(--ink);outline:none}}
.tools .status-filter-option[aria-selected=true]{{background:#eaf5ef;color:#1d7650;font-weight:750}}
.status-filter-check{{visibility:hidden;flex:none;width:6px;height:10px;margin:0 3px 2px 0;border-right:1.7px solid currentColor;border-bottom:1.7px solid currentColor;transform:rotate(45deg)}}
.status-filter-option[aria-selected=true] .status-filter-check{{visibility:visible}}
.status-filter-trigger:focus-visible{{outline:2px solid #93bfa8;outline-offset:2px}}
.status-filter-control[hidden],.status-filter-menu[hidden],.tools select[hidden]{{display:none!important}}
</style></head><body><main id='dashboardView'>
<header class='page-header'><div><h1>{html.escape(group_name)} · 净化行动工作台</h1><p class='lead'>统计周期：{html.escape(date_range)}</p></div></header>
<div class='summary'>
  <div class='summary-card'><span class='summary-icon' aria-hidden='true'>{icons['people']}</span><div><strong>{payload['members_total']}</strong><span class='label'>群成员</span><small>统计时的成员总数</small></div></div>
  <div class='summary-card'><span class='summary-icon blue' aria-hidden='true'>{icons['new']}</span><div><strong>{counts.get('recent_joiner',0)}</strong><span class='label'>新成员保护</span><small>{'入群不足 24 小时' if counts.get('recent_joiner',0) else '暂无新成员记录'}</small></div></div>
  <div class='summary-card'><span class='summary-icon orange' aria-hidden='true'>{icons['chat']}</span><div><strong>{counts.get('confirmed_inactive',0)}</strong><span class='label'>无发言候选</span><small>本周期没有群内发言</small></div></div>
  <div class='summary-card'><span class='summary-icon red' aria-hidden='true'>{icons['alert']}</span><div><strong>{counts.get('confirmed_low_invalid',0)}</strong><span class='label'>低质互动候选</span><small>仍需人工核对原消息</small></div></div>
  <div class='summary-card'><span class='summary-icon' aria-hidden='true'>{icons['shield']}</span><div><strong>{counts.get('excluded',0)}</strong><span class='label'>已排除</span><small>含管理成员及长期豁免</small></div></div>
</div>
{leaderboard_html}
<div class='tools'><input id='search' type='search' placeholder='搜索成员昵称或 ID' aria-label='搜索成员'><select id='statusFilter' aria-label='筛选成员状态'><option value='all'>全部状态</option><option value='candidates'>净化候选</option><option value='recent_joiner'>新成员保护</option>{special_keep_option}<option value='low_activity_needs_review'>人工复核</option><option value='excluded'>已排除</option></select><div id='statusFilterControl' class='status-filter-control' hidden><button id='statusFilterTrigger' class='status-filter-trigger' type='button' role='combobox' aria-label='筛选成员状态' aria-haspopup='listbox' aria-expanded='false' aria-controls='statusFilterMenu'><span id='statusFilterLabel'>全部状态</span><span class='status-filter-chevron' aria-hidden='true'></span></button><div id='statusFilterMenu' class='status-filter-menu' role='listbox' aria-label='成员状态' hidden></div></div><button id='resetFilters' type='button'>重置筛选</button><button id='openAnnouncement' type='button'>编写群公告</button><button id='goPurge' class='go-purge' type='button' disabled>前往净化 →</button></div>
{''.join(sections)}</main>{purge_view_html}{announcement_html}{evidence_html}
<script>
const key={js_literal('wechat-hygiene-review::' + storage_scope)};
const picks=[...document.querySelectorAll('.pick')]; let saved={{}};
try {{ saved=JSON.parse(localStorage.getItem(key)||'{{}}');if(!saved||typeof saved!=='object'||Array.isArray(saved))saved={{}}; }} catch (_) {{}}
const cardById=new Map([...document.querySelectorAll('#dashboardView .member')].map(card=>[card.dataset.id,card]));
function selectedPicks(){{return picks.filter(x=>x.checked);}}
function isReviewOnly(pick){{return ['recent_joiner','special_keep','excluded'].includes(pick.dataset.status);}}
function updateSelectionControls(){{
  const total=selectedPicks().length;
  const button=document.getElementById('goPurge');
  button.disabled=total===0;
  button.textContent=total ? '前往净化 · '+total+' 人 →' : '前往净化 →';
  updateSectionSelectionControls();
}}
picks.forEach(x=>{{
  x.checked=!!saved[x.dataset.id];
  x.onchange=()=>{{
    saved[x.dataset.id]=x.checked;
    try {{localStorage.setItem(key,JSON.stringify(saved));}} catch (_) {{}}
    updateSelectionControls();
  }};
}});
document.querySelectorAll('#dashboardView .member').forEach(card=>{{
  card.addEventListener('click',event=>{{
    if(event.target.closest('input,button,label,a,summary,details')) return;
    if(window.getSelection && window.getSelection().toString()) return;
    card.querySelector('.pick').click();
  }});
}});
updateSelectionControls();
function updateSectionSelectionControls(){{
  document.querySelectorAll('.section-select-all').forEach(button=>{{
    const section=document.getElementById(button.dataset.section);
    const sectionPicks=[...section.querySelectorAll('.pick')];
    const allSelected=sectionPicks.length>0&&sectionPicks.every(pick=>pick.checked);
    button.textContent=allSelected?'取消全选':'全选';
    button.disabled=sectionPicks.length===0;
    button.setAttribute('aria-pressed',String(allSelected));
    button.setAttribute('aria-label',button.textContent+section.querySelector('h2').textContent);
  }});
}}
function selectSection(sectionId){{
  const section=document.getElementById(sectionId);
  if(!section)return;
  const sectionPicks=[...section.querySelectorAll('.pick')];
  if(!sectionPicks.length)return;
  const checked=!sectionPicks.every(pick=>pick.checked);
  sectionPicks.forEach(pick=>{{pick.checked=checked;saved[pick.dataset.id]=checked;}});
  try {{localStorage.setItem(key,JSON.stringify(saved));}} catch (_) {{}}
  updateSelectionControls();
}}
document.querySelectorAll('.section-select-all').forEach(button=>button.addEventListener('click',()=>selectSection(button.dataset.section)));
function applyFilters(){{
  const q=document.getElementById('search').value.trim().toLowerCase();
  const selected=document.getElementById('statusFilter').value;
  document.querySelectorAll('#dashboardView .member-section').forEach(section=>{{
    let visible=0;
    section.querySelectorAll('.member').forEach(card=>{{
      const status=card.dataset.status;
      const matchesStatus=selected==='all'||selected===status||(selected==='candidates'&&(status==='confirmed_inactive'||status==='confirmed_low_invalid'));
      const show=matchesStatus&&(!q||card.dataset.search.includes(q));
      card.classList.toggle('hidden',!show);if(show)visible++;
    }});
    section.classList.toggle('hidden',visible===0);
  }});
}}
document.getElementById('search').oninput=applyFilters;
document.getElementById('statusFilter').onchange=applyFilters;
const statusFilterSelect=document.getElementById('statusFilter');
const statusFilterControl=document.getElementById('statusFilterControl');
const statusFilterTrigger=document.getElementById('statusFilterTrigger');
const statusFilterMenu=document.getElementById('statusFilterMenu');
const statusFilterOptions=[...statusFilterSelect.options].map(option=>{{
  const button=document.createElement('button');
  button.type='button';button.className='status-filter-option';button.tabIndex=-1;
  button.setAttribute('role','option');button.dataset.value=option.value;
  const label=document.createElement('span');label.textContent=option.textContent;
  const check=document.createElement('span');check.className='status-filter-check';check.setAttribute('aria-hidden','true');
  button.append(label,check);
  button.addEventListener('click',()=>{{
    statusFilterSelect.value=option.value;
    statusFilterSelect.dispatchEvent(new Event('change',{{bubbles:true}}));
    closeStatusFilter(true);
  }});
  statusFilterMenu.append(button);
  return button;
}});
function syncStatusFilter(){{
  const selected=statusFilterOptions.find(option=>option.dataset.value===statusFilterSelect.value);
  document.getElementById('statusFilterLabel').textContent=selected?.querySelector('span').textContent||'全部状态';
  statusFilterOptions.forEach(option=>option.setAttribute('aria-selected',String(option.dataset.value===statusFilterSelect.value)));
}}
function closeStatusFilter(restoreFocus=false){{
  statusFilterMenu.hidden=true;
  statusFilterTrigger.setAttribute('aria-expanded','false');
  if(restoreFocus)statusFilterTrigger.focus();
}}
function openStatusFilter(index){{
  syncStatusFilter();
  statusFilterMenu.hidden=false;
  statusFilterTrigger.setAttribute('aria-expanded','true');
  const selectedIndex=statusFilterOptions.findIndex(option=>option.dataset.value===statusFilterSelect.value);
  statusFilterOptions[index??Math.max(0,selectedIndex)]?.focus();
}}
statusFilterTrigger.addEventListener('click',()=>statusFilterMenu.hidden?openStatusFilter():closeStatusFilter(true));
statusFilterTrigger.addEventListener('keydown',event=>{{
  if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){{
    event.preventDefault();openStatusFilter(event.key==='Home'?0:event.key==='End'?statusFilterOptions.length-1:undefined);
  }}else if(event.key==='Escape')closeStatusFilter();
}});
statusFilterMenu.addEventListener('keydown',event=>{{
  const index=statusFilterOptions.indexOf(document.activeElement);
  if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){{
    event.preventDefault();
    const next=event.key==='Home'?0:event.key==='End'?statusFilterOptions.length-1:(index+(event.key==='ArrowDown'?1:-1)+statusFilterOptions.length)%statusFilterOptions.length;
    statusFilterOptions[next]?.focus();
  }}else if(event.key==='Escape'){{
    event.preventDefault();event.stopPropagation();closeStatusFilter(true);
  }}else if(event.key==='Tab')closeStatusFilter(true);
}});
document.addEventListener('pointerdown',event=>{{if(!statusFilterControl.contains(event.target))closeStatusFilter();}});
statusFilterSelect.addEventListener('change',syncStatusFilter);
statusFilterSelect.hidden=true;statusFilterControl.hidden=false;syncStatusFilter();
document.getElementById('resetFilters').onclick=()=>{{document.getElementById('search').value='';statusFilterSelect.value='all';applyFilters();syncStatusFilter();closeStatusFilter();}};
const evidenceDialog=document.getElementById('evidenceDialog');
let evidenceOrigin=null;
function releaseEvidenceLock(){{
  document.documentElement.classList.remove('modal-open');
  document.body.classList.remove('modal-open');
}}
function openEvidence(id,origin){{
  const card=cardById.get(id);
  if(!card) return;
  evidenceOrigin=origin;
  document.getElementById('evidenceTitle').textContent=card.querySelector('h3').textContent+' · 发言证据';
  document.getElementById('evidenceSubtitle').textContent=card.querySelector('code').textContent+' · '+card.querySelector('.badge').textContent;
  document.getElementById('evidenceBody').innerHTML=card.querySelector('.evidence-template').innerHTML;
  evidenceDialog.showModal();
  document.documentElement.classList.add('modal-open');
  document.body.classList.add('modal-open');
}}
document.addEventListener('click',event=>{{
  const button=event.target.closest('.evidence-button');
  if(button) openEvidence(button.dataset.id,button);
}});
document.getElementById('closeEvidence').addEventListener('click',()=>evidenceDialog.close());
evidenceDialog.addEventListener('click',event=>{{if(event.target===evidenceDialog) evidenceDialog.close();}});
evidenceDialog.addEventListener('cancel',releaseEvidenceLock);
evidenceDialog.addEventListener('close',()=>{{releaseEvidenceLock();if(evidenceOrigin?.isConnected) evidenceOrigin.focus();}});

const processedKey={js_literal('wechat-hygiene-processed::' + storage_scope)};
let processed={{}};
try {{processed=JSON.parse(localStorage.getItem(processedKey)||'{{}}');if(!processed||typeof processed!=='object'||Array.isArray(processed))processed={{}};}} catch (_) {{}}
function saveProcessed(){{try {{localStorage.setItem(processedKey,JSON.stringify(processed));}} catch (_) {{}}}}
function updateProcessedTotal(){{
  const actionIds=selectedPicks().filter(x=>!isReviewOnly(x)).map(x=>x.dataset.id);
  document.getElementById('processedTotal').textContent=String(actionIds.filter(id=>processed[id]).length);
  const allProcessed=actionIds.length>0&&actionIds.every(id=>Boolean(processed[id]));
  const button=document.getElementById('purgeSelectAll');
  button.textContent=allProcessed?'取消全选':'全选';
  button.disabled=actionIds.length===0;
  button.setAttribute('aria-pressed',String(allProcessed));
  button.setAttribute('aria-label',button.textContent+'待手工核对成员的处理标记');
}}
function togglePurgeProcessed(){{
  const actionIds=selectedPicks().filter(x=>!isReviewOnly(x)).map(x=>x.dataset.id);
  if(!actionIds.length)return;
  const checked=!actionIds.every(id=>Boolean(processed[id]));
  actionIds.forEach(id=>{{processed[id]=checked;}});
  saveProcessed();
  renderPurgePage();
}}
document.getElementById('purgeSelectAll').addEventListener('click',togglePurgeProcessed);
function buildPurgeCard(card,reviewOnly){{
  const id=card.dataset.id;
  const clone=card.cloneNode(true);
  clone.classList.add('purge-card');
  clone.classList.remove('hidden');
  if(reviewOnly) clone.classList.add('protected');
  clone.querySelector('.select-label')?.remove();
  const foot=clone.querySelector('.card-foot');
  if(reviewOnly){{
    const note=document.createElement('span');note.className='protection-note';note.textContent='仅供复核';foot.prepend(note);
  }} else {{
    const label=document.createElement('label');label.className='processed-label';
    const box=document.createElement('input');box.type='checkbox';box.checked=Boolean(processed[id]);box.setAttribute('aria-label','标记 '+card.querySelector('h3').textContent+' 已在微信处理');
    clone.classList.toggle('processed',box.checked);
    const setProcessed=value=>{{box.checked=value;processed[id]=value;clone.classList.toggle('processed',value);saveProcessed();updateProcessedTotal();}};
    box.addEventListener('change',()=>setProcessed(box.checked));
    clone.addEventListener('click',event=>{{
      if(event.target.closest('button,input,label,a,summary,details')) return;
      if(window.getSelection && window.getSelection().toString()) return;
      setProcessed(!box.checked);
    }});
    clone.tabIndex=0;
    clone.addEventListener('keydown',event=>{{
      if(event.target===clone&&(event.key==='Enter'||event.key===' ')){{event.preventDefault();setProcessed(!box.checked);}}
    }});
    label.append(box,document.createTextNode('已在微信处理'));foot.prepend(label);
  }}
  const remove=document.createElement('button');remove.type='button';remove.className='remove-selected';remove.textContent='移出';remove.setAttribute('aria-label','将 '+card.querySelector('h3').textContent+' 移出名单');
  remove.addEventListener('click',()=>{{const original=card.querySelector('.pick');original.checked=false;original.dispatchEvent(new Event('change',{{bubbles:true}}));renderPurgePage();}});
  foot.append(remove);
  return clone;
}}
function renderPurgePage(){{
  const selected=selectedPicks();
  const actions=selected.filter(x=>!isReviewOnly(x));
  const protectedMembers=selected.filter(isReviewOnly);
  const actionList=document.getElementById('purgeActionList');const protectedList=document.getElementById('purgeProtectedList');
  actionList.replaceChildren();protectedList.replaceChildren();
  actions.forEach(x=>actionList.append(buildPurgeCard(cardById.get(x.dataset.id),false)));
  protectedMembers.forEach(x=>protectedList.append(buildPurgeCard(cardById.get(x.dataset.id),true)));
  document.getElementById('selectedTotal').textContent=String(selected.length);
  document.getElementById('actionTotal').textContent=String(actions.length);
  document.getElementById('protectedTotal').textContent=String(protectedMembers.length);
  document.getElementById('actionCount').textContent=actions.length+' 人';
  document.getElementById('protectedCount').textContent=protectedMembers.length+' 人';
  document.getElementById('purgeActionSection').hidden=actions.length===0;
  document.getElementById('purgeProtectedSection').hidden=protectedMembers.length===0;
  document.getElementById('purgeEmpty').hidden=selected.length!==0;
  updateProcessedTotal();
}}
function syncView(){{
  const purge=location.hash==='#purge';
  document.getElementById('dashboardView').hidden=purge;
  document.getElementById('purgeView').hidden=!purge;
  if(purge) renderPurgePage();
  window.scrollTo(0,0);
}}
document.getElementById('goPurge').addEventListener('click',()=>{{
  if(!selectedPicks().length) return;
  history.pushState({{view:'purge'}},'', '#purge');syncView();
}});
document.getElementById('backReview').addEventListener('click',()=>{{
  if(history.state?.view==='purge') history.back();
  else {{history.replaceState({{view:'review'}},'', '#review');syncView();}}
}});
window.addEventListener('popstate',syncView);
syncView();
const announcementDialog=document.getElementById('announcementDialog');
const announcementTrigger=document.getElementById('openAnnouncement');
announcementTrigger.addEventListener('click',()=>{{
  if(announcementDialog.open) return;
  announcementDialog.showModal();
  document.documentElement.classList.add('modal-open');
  document.body.classList.add('modal-open');
}});
document.getElementById('closeAnnouncement').addEventListener('click',()=>announcementDialog.close());
announcementDialog.addEventListener('click',event=>{{if(event.target===announcementDialog) announcementDialog.close();}});
function releaseAnnouncementLock(){{
  document.documentElement.classList.remove('modal-open');
  document.body.classList.remove('modal-open');
}}
announcementDialog.addEventListener('cancel',releaseAnnouncementLock);
announcementDialog.addEventListener('close',()=>{{
  releaseAnnouncementLock();
  announcementTrigger.focus();
}});
{announcement_script}
</script></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent,
            prefix=f".{output.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(document)
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="从已核验的分析 JSON 生成单文件净化行动工作台；不读取微信、不修改群")
    parser.add_argument("--analysis-json", type=Path, required=True, help="含成员、证据、统计周期的分析 JSON")
    parser.add_argument("--output-html", type=Path, help="输出路径；默认写入分析 JSON 所在目录")
    parser.add_argument("--chatroom-id", help="指定稳定群 ID；未提供时必须由 JSON 提供")
    parser.add_argument("--group-name", help="指定群名称；未提供时必须由 JSON 提供")
    args = parser.parse_args()
    payload = json.loads(args.analysis_json.read_text(encoding="utf-8"))
    start, end = validate_payload(payload)
    payload_chatroom = str(payload.get("chatroom_id") or "").strip()
    payload_name = str(payload.get("group_name") or "").strip()
    if args.chatroom_id and payload_chatroom and args.chatroom_id != payload_chatroom:
        parser.error("指定的群 ID 与分析 JSON 不一致，已停止以防跨群误用")
    if args.group_name and payload_name and args.group_name != payload_name:
        parser.error("指定的群名称与分析 JSON 不一致，已停止以防跨群误用")
    chatroom_id = (args.chatroom_id or payload_chatroom).strip()
    group_name = (args.group_name or payload_name).strip()
    if not chatroom_id or not group_name:
        parser.error("必须由 JSON 或显式参数提供稳定群 ID 和群名称；没有默认群")
    if not re.fullmatch(r"[A-Za-z0-9_@.-]+", chatroom_id):
        parser.error("群 ID 格式无效")
    safe_name = safe_group_stem(group_name, chatroom_id)
    output = args.output_html or args.analysis_json.with_name(f"{safe_name}_activity_summary_{start}_{end}.html")
    render_html(payload, output, group_name, f"{payload['date_range']['start']} 至 {payload['date_range']['end']}", chatroom_id)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
