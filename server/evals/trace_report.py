"""Summarize .data/traces.jsonl: speed, cost, cache hits, tool errors, slowest requests.

    uv run python -m evals.trace_report
    uv run python -m evals.trace_report --last 50
"""

import argparse
import json
import statistics
from collections import Counter, defaultdict

from dock_server.tracing import TRACE_FILE


def percentile(values: list[float], share: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(share * len(values)))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--last", type=int, default=0, help="only the last N requests")
    args = parser.parse_args()
    if not TRACE_FILE.exists():
        raise SystemExit(f"No traces yet ({TRACE_FILE}). Ask Dock something first.")

    records = [json.loads(line) for line in TRACE_FILE.read_text().splitlines() if line.strip()]
    requests = [r for r in records if r["kind"] == "voice"]
    if args.last:
        requests = requests[-args.last:]
    if not requests:
        raise SystemExit("No voice requests in the traces yet.")
    steps = [s for r in requests for s in r["steps"]]
    models = [s for s in steps if s["type"] == "model"]
    tools = [s for s in steps if s["type"] == "tool"]
    fixes = [s for s in steps if s["type"] == "fix"]
    seconds = [r["seconds"] for r in requests]
    costs = [r["cost"] for r in requests]
    first_model = [next((s["seconds"] for s in r["steps"] if s["type"] == "model"), 0) for r in requests]

    print(f"Requests: {len(requests)} ({requests[0]['at']} to {requests[-1]['at']})")
    print(f"Errors: {sum(1 for r in requests if r.get('error'))}")
    print("\nSpeed (whole request, seconds)")
    print(f"  median {statistics.median(seconds):.2f} · p95 {percentile(seconds, 0.95):.2f} · slowest {max(seconds):.2f}")
    print(f"  understanding the request (first model call): median {statistics.median(first_model):.2f}")
    print("\nCost (estimated, US$)")
    print(f"  per request: mean {statistics.mean(costs):.4f} · median {statistics.median(costs):.4f} · "
          f"p95 {percentile(costs, 0.95):.4f} · total {sum(costs):.3f}")

    cached = sum(s["cache_read"] for s in models)
    prompt = sum(s["input"] + s["cache_read"] + s["cache_write"] for s in models)
    print(f"\nPrompt caching: {cached / prompt:.0%} of prompt tokens came from the cache" if prompt else "")

    print("\nModel calls, by job")
    by_job = defaultdict(list)
    for s in models:
        by_job[s["purpose"]].append(s)
    for job, calls in sorted(by_job.items(), key=lambda kv: -len(kv[1])):
        rate = [s["tokens_per_sec"] for s in calls if s["tokens_per_sec"]]
        print(f"  {job:18} {len(calls):4} calls · median {statistics.median(s['seconds'] for s in calls):.2f} s · "
              f"{statistics.median(rate) if rate else 0:.0f} tokens/s out · ${sum(s['cost'] for s in calls):.4f}")

    print("\nTools")
    for name, count in Counter(s["name"] for s in tools).most_common():
        runs = [s for s in tools if s["name"] == name]
        failed = sum(1 for s in runs if not s.get("ok"))
        print(f"  {name:22} {count:4} · median {statistics.median(s.get('seconds', 0) for s in runs):.2f} s"
              + (f" · {failed} failed" if failed else ""))
    if fixes:
        print(f"\nCorrected by fix_call: {len(fixes)} of {len(requests)} requests")
        for (before, after), count in Counter((s["from"], s["to"]) for s in fixes).most_common(5):
            print(f"  {before} -> {after}: {count}")

    print("\nSlowest requests")
    for r in sorted(requests, key=lambda r: -r["seconds"])[:5]:
        print(f"  {r['seconds']:5.2f} s  {r['said'][:60]!r}  "
              + " → ".join(s.get("name") or s.get("purpose", "") for s in r["steps"] if s["type"] != "fix"))


if __name__ == "__main__":
    main()
