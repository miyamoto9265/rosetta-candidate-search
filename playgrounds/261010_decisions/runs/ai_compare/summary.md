# Decisions / luna comparison (ai_compare, 2026-10-10 17:26)

## Preprocess -> RCS top-1

| arm/queries | n | top-1 | top-10 | p50 s | p95 s | $/1k | errors |
|---|---|---|---|---|---|---|---|
| deepseek/clean | 132 | 91.7% | 98.5% | 0.895 | 1.464 | 0.0346 | 0 |
| deepseek/dirty | 132 | 91.7% | 98.5% | 1.021 | 1.337 | 0.0472 | 0 |
| luna/clean | 132 | 91.7% | 98.5% | 1.176 | 1.676 | 0.0557 | 0 |
| luna/dirty | 132 | 91.7% | 98.5% | 1.578 | 2.463 | 0.0802 | 0 |
| none/clean | 132 | 91.7% | 98.5% | 0.0 | 0.0 | 0.0 | 0 |
| none/dirty | 132 | 87.9% | 95.5% | 0.0 | 0.0 | 0.0 | 0 |

## Postprocess (same RCS top-10, no preprocess)

| arm | n | RCS top-1 | AI top-1 | AI top-1 (reachable) | abstain | p50 s | p95 s | $/1k | errors |
|---|---|---|---|---|---|---|---|---|---|
| decisions | 132 | 91.7% | 93.9% | 95.4% | 0.0% | 0.238 | 0.299 | 0.2233 | 0 |
| deepseek | 132 | 91.7% | 97.0% | 98.5% | 0.0% | 1.091 | 1.445 | 0.0622 | 0 |
| luna | 132 | 91.7% | 97.0% | 98.5% | 0.0% | 1.679 | 2.579 | 0.1205 | 0 |

Decisions by confidence (share answered, top-1 among them):

- confidence >= 0.5: 95.5% answered, top-1 97.6%
- confidence >= 0.7: 92.4% answered, top-1 99.2%
- confidence >= 0.8: 92.4% answered, top-1 99.2%
- confidence >= 0.9: 90.1% answered, top-1 99.2%
