RCS を組織アカウントへ移植済み（2026-09-23）。MCP サーバー追加（2026-09-27）。

• アカウント: `765959262011` / ユーザー: `miyamoto` / profile: `rcs-org`
• UI: https://rcs.cobrac.site/（CloudFront `EQ1U5DPE1OAUA`、DNS は個人アカウント Route 53 `cobrac.site`）
• API: https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates
• MCP: https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/mcp（Lambda `rcs-mcp`）

## 権限依頼の履歴

| 日付 | 内容 | 状態 |
|---|---|---|
| 2026-09-27 | Secrets Manager（MCP Bearer トークン管理） | **付与済み**。シークレット `rcs/mcp-bearer-token` を作成し、`rcs-mcp` はここから読む |

cobrac-web（同アカウントの CDK スタック `CobracAgents`）の worker がこのシークレットを使う場合は、
cobrac-web 側の CDK で worker タスクのロールに `rcs/mcp-bearer-token` の `secretsmanager:GetSecretValue` を付与する
（`ecs.Secret.fromSecretsManager` を使えば CDK が自動付与）。RCS 側で追加の権限依頼は不要。

運用手順は `docs/aws_operations_guide.md` を参照。
