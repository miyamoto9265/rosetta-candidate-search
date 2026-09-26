RCS を組織アカウントへ移植済み（2026-09-23）。MCP サーバー追加（2026-09-27）。

• アカウント: `765959262011` / ユーザー: `miyamoto` / profile: `rcs-org`
• UI: https://rcs.cobrac.site/（CloudFront `EQ1U5DPE1OAUA`、DNS は個人アカウント Route 53 `cobrac.site`）
• API: https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates
• MCP: https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/mcp（Lambda `rcs-mcp`）

## 追加の権限依頼（未付与・2026-09-27）

MCP の Bearer トークンを Secrets Manager で管理し、cobrac-web（同アカウントの CDK スタック `CobracAgents`）の
worker に ECS secrets として渡すため、IAM ユーザー `miyamoto` に次の権限が必要。現状は拒否されるため、
トークンは Lambda `rcs-mcp` の環境変数にのみ保存している。

| アクション | リソース |
|---|---|
| `secretsmanager:CreateSecret`, `PutSecretValue`, `GetSecretValue`, `DescribeSecret`, `TagResource` | `arn:aws:secretsmanager:ap-northeast-1:765959262011:secret:rcs/*` |

（代替: `ssm:PutParameter` / `GetParameter` on `arn:aws:ssm:ap-northeast-1:765959262011:parameter/rcs/*`）

運用手順は `docs/aws_operations_guide.md` を参照。
