# Input and interaction contract / 输入与交互契约

The renderer accepts an already checked single-group analysis object. It checks structural consistency, not source collection completeness. 本脚本只校验输入格式和提供的人数一致性，不能证明采集、身份映射或状态判断正确。

## Top-level fields

| Field | Required / meaning |
| --- | --- |
| `chatroom_id` | Stable nonempty group identity, or explicit `--chatroom-id`; no default. Allowed characters: letters, digits, underscore, `@`, period, hyphen. |
| `group_name` | Nonempty group display name, or explicit `--group-name`; no default. |
| `date_range.start/end` | Valid `YYYY-MM-DD` dates (time suffix allowed); start must not follow end. |
| `rows` | Complete current member array; each `username` unique. |
| `members_total` | Integer exactly equal to row count. |
| `status_counts` | Count by supported status; must match the rows. Absent supported statuses mean zero; unknown statuses are rejected. |
| `announcement_context` | Optional object of plain-text announcement overrides; see below. |

Identity supplied as explicit arguments must match any JSON identity. 缺少群 ID 或名称会停止生成，显式值冲突也会停止。程序不会套用实际群或演示群。

## Member rows

Each row requires all of:

| Field | Meaning |
| --- | --- |
| `username` | Unique stable nonempty member identifier; synthetic identifiers only in public examples. |
| `display_name` | Display text; not an identity key. |
| `status`, `status_label` | Supported status key and its display text. |
| `message_count`, `valid_count`, `invalid_count`, `replies_sent` | Nonnegative integers; missing data must not be filled with invented zeroes. |
| `has_direct_dialogue` | Boolean supplied by the source analysis. |
| `samples` | Array of evidence objects; may be empty for known absence. Each evidence requires string `time`, `quality`, `text`, `reason`. |

Optional: `joined_at` display text; `ai_review` object with string `recommendation` and `reason`. AI-review explanation is supplied input, not a model call.

Supported statuses: `confirmed_inactive`, `confirmed_low_invalid`, `low_activity_needs_review`, `low_activity_kept`, `recent_joiner`, `special_keep`, `normal_activity`, `excluded`.

`recent_joiner`, `special_keep`, and `excluded` may be selected for inspection but only enter the protected review area, without a processing toggle. Other selections enter the manual review area; this does not establish a removal decision.

## Storage and output isolation

Selection, processing marks, and drafts use full group ID + start/end dates in their local-storage keys. No private-group migration branch exists. Same group and period retain the same keys; changing group or period changes the scope. Browser file-origin behavior can still affect persistence.

Default output filename includes sanitized group name, sanitized full group ID, and a SHA-256 ID digest to avoid collisions after sanitization. Explicit output paths are the user's responsibility. Invalid input does not overwrite an existing output; valid output is atomically replaced from a temporary file in the same directory.

## Announcement text

Allowed `announcement_context` fields: `salutation`, `member_noun`, `community_label`, `valid_rule`, `invalid_rule`, `closing`, `policy_text`. Each value must be text. No invitation policy is enabled or prefilled by default. Rules are editable examples of wording, not proof that this community agreed to them. Review and adjust the announcement for the actual policy before copying.

Example with fictional context:

```json
{"announcement_context":{"salutation":"各位伙伴","community_label":"演示项目群","policy_text":""}}
```

The announcement rate uses actual removed count divided by original membership. Copying never sends a message. 聊天证据进行 HTML 转义，JavaScript 文本防止闭合脚本注入。

## UI invariants

- Responsive six-column cards; search by display name and username; status selector supports keyboard and outside-click closing.
- Top 10 speaking members include protected/management members; sorted by message count, valid count, then username. This is volume, not quality.
- Module select-all includes filtered cards and changes only that module. Second-level processing select-all never affects protected members.
- Removing from the shortlist cancels current selection but preserves historical handling marks. State for members absent from a newer report is retained locally.
- Evidence opens separately without selecting a member. There is no list-export button, remote script, account action, or cross-device synchronization.

## Validation

Use `python3 -B -m unittest discover -s tests -p 'test_render_review_workbench.py' -v`. The tests use fictional data and synthetic DOM interactions only; no WeChat or real browser validation is performed.
