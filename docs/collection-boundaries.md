# Collection boundaries / 采集边界

This repository ships the offline renderer only. The earlier local tool included a collector using an older `wechat-cli` interface; that collector has not been migrated to the newer interface and is not distributed here. No CLI installation, live collection command, or supported-version claim is offered by this release.

本仓库只提供离线渲染器。原有采集链路使用旧版命令接口，尚未完成迁移，因此未打包采集脚本、旧API实测说明或私人采集配置。这里不提供实时采集命令，也不承诺任何微信客户端版本可用。

If you already have a report, check these upstream facts independently before using it:

1. The stable group ID actually corresponds to the displayed community.
2. Current member baseline and reporting dates are correct.
3. All message pages are collected; an independently verified total matches the collected count.
4. Sender labels are mapped to stable identities; ambiguous mappings remain unresolved, not guessed.
5. Protection and exemption rules belong to this specific group.
6. Activity classifications have sufficient evidence and do not turn unknown data into zero.

If an upstream manifest exists, inspect the checks that its actual collection process defines; do not assume a particular key or fabricate a pass. Structural JSON validation does not replace those checks.

Messages and identities are sensitive. Use only data that you are authorized to process. Never submit real input or output to a public issue or pull request; reproduce problems with fictional data.
