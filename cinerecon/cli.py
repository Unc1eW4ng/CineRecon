import argparse
import collections
import concurrent.futures
import json
import os
import threading
import time
from pathlib import Path
from .common import LEVELS, save
from .evaluation import DEFAULT_MODEL


def main():
    parser = argparse.ArgumentParser(description="CineRecon release tools")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("validate", help="Validate dataset and optional reference media")
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--media", action="store_true")
    p = sub.add_parser("prepare", help="Prepare a complete single-clip evaluation request locally")
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--clip", required=True)
    p.add_argument("--level", choices=LEVELS, required=True)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--generated", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--configuration", required=True)
    p = sub.add_parser("prepare-batch", help="Prepare all clips for a manifest of reconstructed full videos")
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--cases", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("judge", help="Preview by default; --execute makes a single paid API request per job")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--job", type=Path)
    group.add_argument("--jobs-root", type=Path)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--response-file", type=Path, help="Import an archived response, or a synthetic response for smoke tests")
    p.add_argument("--retry-failed", action="store_true")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--rpm", type=int, default=20)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--output", type=Path)
    p = sub.add_parser("summarize", help="Summarize prepared jobs including missing/failed coverage")
    p.add_argument("--jobs-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate":
        from .dataset import validate
        result = validate(args.root, args.media)
    elif args.command == "prepare":
        from .evaluation import prepare
        result = prepare(args.root, args.clip, args.level, "en", args.reference, args.generated, args.output, args.configuration)
    elif args.command == "prepare-batch":
        from .batch import prepare_cases
        result = prepare_cases(args.root,args.cases,args.output,"en")
    elif args.command == "judge":
        from .evaluation import judge
        if args.workers < 1 or args.rpm < 1:
            parser.error("workers and rpm must be positive")
        if args.response_file and (args.jobs_root or args.execute):
            parser.error("response-file requires one --job and cannot be combined with --execute")
        paths = [args.job] if args.job else sorted(p.parent for p in args.jobs_root.rglob("job.json"))
        if not paths:
            parser.error("No prepared jobs found")
        times, lock = collections.deque(), threading.Lock()
        def rate_limit():
            while True:
                with lock:
                    now = time.monotonic()
                    while times and now-times[0] >= 60:
                        times.popleft()
                    if len(times) < args.rpm:
                        times.append(now)
                        return
                    delay = max(.05, 60-(now-times[0]))
                time.sleep(min(delay, 1))
        def work(path):
            try:
                return judge(path, endpoint=os.environ.get("CINERECON_JUDGE_URL"), judge_model=args.model,
                             execute=args.execute, response_file=args.response_file, retry_failed=args.retry_failed, rate_limiter=rate_limit)
            except Exception as e:
                return dict(job=str(path), status="not_executed", error=type(e).__name__, reason=str(e))
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            result = list(pool.map(work, paths))
        if args.output:
            save(args.output, result)
    elif args.command == "summarize":
        from .aggregate import summarize
        paths = sorted(p.parent for p in args.jobs_root.rglob("job.json"))
        result = summarize(paths)
        from .common import read
        report = args.jobs_root/"preparation_report.json"
        if report.exists():
            preparation = read(report)
            result["preparation_failures"] = [r for r in preparation["jobs"] if r["status"] == "prepare_failed"]
            result["requested_jobs"] = preparation["expected_jobs"]
        elif not paths:
            parser.error("No prepared jobs found")
        save(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "judge" and any(r.get("status") in {"failed", "refused", "not_executed"} for r in result):
        raise SystemExit(1)
    if args.command == "prepare-batch" and result["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
