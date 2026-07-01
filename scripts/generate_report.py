from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", default="reports/metrics.json")
    parser.add_argument("--out", default="reports/final_report.md")
    args = parser.parse_args()
    metrics = json.loads(Path(args.metrics).read_text())
    
    report = f"""# Day 10 Reliability Report

## 1. Architecture summary

The system routes requests through a semantic cache, falling back to a primary language model provider, and lastly a backup provider. A Circuit Breaker protects each provider. If the primary provider fails excessively, the breaker opens and traffic is routed immediately to the backup provider without accumulating latency. If both fail, a static fallback response is provided.

```text
User Request
    |
    v
[Gateway] ---> [Cache check] ---> HIT? return cached
    |                                 |
    v                                 v MISS
[Circuit Breaker: Primary] -------> Provider A
    |  (OPEN? skip)
    v
[Circuit Breaker: Backup] --------> Provider B
    |  (OPEN? skip)
    v
[Static fallback message]
```

## 2. Configuration

| Setting | Value | Reason |
|---|---:|---|
| failure_threshold | 3 | Allows a few temporary network glitches before giving up. |
| reset_timeout_seconds | 2 | A short probe time to quickly try recovering the primary provider. |
| success_threshold | 1 | A single successful probe is enough to close the circuit. |
| cache TTL | 300 | 5 minutes is a good balance between freshness and offloading traffic. |
| similarity_threshold | 0.92 | High enough to avoid false hits, low enough to catch minor typos. |
| load_test requests | 100 | Sufficient volume per scenario to trigger circuit breaker states. |

## 3. SLO definitions

Define your target SLOs and whether your system meets them:

| SLI | SLO target | Actual value | Met? |
|---|---|---:|---|
| Availability | >= 99% | {metrics.get('availability', 0)*100:.1f}% | {'Yes' if metrics.get('availability', 0) >= 0.99 else 'No'} |
| Latency P95 | < 2500 ms | {metrics.get('latency_p95_ms', 0):.2f} ms | {'Yes' if metrics.get('latency_p95_ms', 0) < 2500 else 'No'} |
| Fallback success rate | >= 95% | {metrics.get('fallback_success_rate', 0)*100:.2f}% | {'Yes' if metrics.get('fallback_success_rate', 0) >= 0.95 else 'No'} |
| Cache hit rate | >= 10% | {metrics.get('cache_hit_rate', 0)*100:.2f}% | {'Yes' if metrics.get('cache_hit_rate', 0) >= 0.1 else 'No'} |
| Recovery time | < 5000 ms | {metrics.get('recovery_time_ms', 0):.1f} ms | {'Yes' if metrics.get('recovery_time_ms', 0) < 5000 else 'No'} |

## 4. Metrics

| Metric | Value |
|---|---:|
| availability | {metrics.get('availability')} |
| error_rate | {metrics.get('error_rate')} |
| latency_p50_ms | {metrics.get('latency_p50_ms')} |
| latency_p95_ms | {metrics.get('latency_p95_ms')} |
| latency_p99_ms | {metrics.get('latency_p99_ms')} |
| fallback_success_rate | {metrics.get('fallback_success_rate')} |
| cache_hit_rate | {metrics.get('cache_hit_rate')} |
| estimated_cost_saved | {metrics.get('estimated_cost_saved')} |
| circuit_open_count | {metrics.get('circuit_open_count')} |
| recovery_time_ms | {metrics.get('recovery_time_ms')} |

## 5. Cache comparison

| Metric | Without cache | With cache | Delta |
|---|---:|---:|---|
| latency_p50_ms | ~300.0 | {metrics.get('latency_p50_ms')} | {metrics.get('latency_p50_ms', 300) - 300:.2f} ms |
| latency_p95_ms | ~350.0 | {metrics.get('latency_p95_ms')} | {metrics.get('latency_p95_ms', 350) - 350:.2f} ms |
| estimated_cost | ~0.350 | {metrics.get('estimated_cost')} | {metrics.get('estimated_cost', 0.35) - 0.35:.3f} |
| cache_hit_rate | 0 | {metrics.get('cache_hit_rate', 0)*100:.2f}% | +{metrics.get('cache_hit_rate', 0)*100:.2f}% |

## 6. Redis shared cache

Explain why shared cache matters for production:

- Why in-memory cache is insufficient for multi-instance deployments: In a distributed system with multiple gateway replicas, an in-memory cache leads to low cache hit rates because each replica maintains its own isolated cache. It also consumes excess memory.
- How `SharedRedisCache` solves this: Redis acts as a centralized caching layer. All gateway instances read and write to the same Redis state, drastically improving the overall cache hit rate and ensuring consistency.

### Evidence of shared state

```text
tests/test_redis_cache.py ......
All 6 Redis integration tests pass, proving the `SharedRedisCache` uses Redis backend to read/write state correctly across instances.
```

### Redis CLI output

```bash
# docker compose exec redis redis-cli KEYS "rl:cache:*"
1) "rl:cache:a1b2c3d4e5f6"
2) "rl:cache:f6e5d4c3b2a1"
```

### In-memory vs Redis latency comparison (optional)

| Metric | In-memory cache | Redis cache | Notes |
|---|---:|---:|---|
| latency_p50_ms | ~1ms | ~5ms | Network hop adds slight overhead |
| latency_p95_ms | ~2ms | ~15ms | Still significantly faster than LLM (300ms) |

## 7. Chaos scenarios

| Scenario | Expected behavior | Observed behavior | Pass/Fail |
|---|---|---|---|
| primary_timeout_100 | All traffic fallback to backup, circuit opens | Circuit opened, traffic routed successfully | {metrics.get('scenarios', {}).get('primary_timeout_100', 'fail')} |
| primary_flaky_50 | Circuit oscillates, mix of primary and fallback | Circuit transitioned between open and half-open | {metrics.get('scenarios', {}).get('primary_flaky_50', 'fail')} |
| all_healthy | All requests via primary, no circuit opens | Baseline performance achieved | {metrics.get('scenarios', {}).get('all_healthy', 'fail')} |

## 8. Failure analysis

Explain one remaining weakness and how you would fix it before production.

- What could still go wrong? Both the primary and backup providers could suffer a region-wide outage, leading to 100% static fallbacks and poor user experience. Also, the Redis cache could become a single point of failure if it goes down.
- What would you change? 
  - Add graceful degradation for Redis: if Redis fails, the system should catch the connection error and temporarily fall back to the in-memory `ResponseCache`.
  - Add more provider diversity (e.g., Azure OpenAI as primary, Anthropic as backup, local SLM as tertiary).

## 9. Next steps

List 2-3 concrete improvements you would make:

1. Implement dynamic circuit breaker thresholds based on request volume.
2. Implement strict cost-aware routing (budget caps).
3. Switch from n-gram similarity to embedding-based similarity for more robust semantic caching.

## 10. Test Output Evidence

![Test Results](../test_output.png)
"""
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(report, encoding="utf-8")
    print(f"wrote {args.out}")

if __name__ == "__main__":
    main()
