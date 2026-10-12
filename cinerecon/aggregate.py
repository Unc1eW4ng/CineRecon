from collections import defaultdict
from pathlib import Path
from statistics import mean
from .common import DIMENSIONS, LABELS, LEVELS, read, require


def scores(rows):
    dimensions = {}
    for name, categories in DIMENSIONS.items():
        values = []
        for row in rows:
            items = [i["score"] for i in row["items"] if i["category"] in categories]
            require(all(type(v) in (float, int) and v in (0, .5, 1) for v in items), "Unexpected rating value")
            if items:
                values.append(mean(items) * 100)
        dimensions[name] = {"score": mean(values) if values else None, "clips": len(values)}
    means = [v["score"] for v in dimensions.values()]
    category_scores = {}
    for dimension, categories in DIMENSIONS.items():
        for category in sorted(categories):
            clip_means, item_count = [], 0
            for row in rows:
                values = [i["score"] for i in row["items"] if i["category"] == category]
                if values:
                    clip_means.append(mean(values) * 100)
                    item_count += len(values)
            category_scores[category] = dict(dimension=dimension,
                                            score=mean(clip_means) if clip_means else None,
                                            clips=len(clip_means), items=item_count)
    return dict(valid_clips=len(rows), valid_videos=len({r["video_id"] for r in rows}),
                dimensions=dimensions, categories=category_scores,
                overall=mean(means) if all(v is not None for v in means) else None)


def summarize(paths):
    paths = list(paths)
    groups = defaultdict(list)
    exclusions, seen, languages, judges, configurations = [], set(), set(), set(), set()
    jobs = []
    for folder in paths:
        folder = Path(folder)
        job = read(folder/"job.json")
        key = (job["configuration"], job["level"], job["clip_id"])
        require(key not in seen, f"Duplicate configuration/setting/clip: {key}")
        seen.add(key)
        configurations.add(job["configuration"])
        languages.add(job["language"])
        jobs.append(job)
        if not (folder/"result.json").exists():
            exclusions.append(dict(configuration=key[0], level=key[1], clip_id=key[2], status="missing"))
            continue
        r = read(folder/"result.json")
        require((r["configuration"], r["level"], r["clip_id"]) == key, "Result/job mismatch")
        if r["status"] != "success":
            exclusions.append(dict(configuration=key[0], level=key[1], clip_id=key[2], status=r["status"], error=r.get("error")))
            continue
        from .common import checksum
        if r.get("fingerprint_version", 1) == 2:
            from .evaluation import request
            fingerprint = checksum(dict(job=job, request=request(job, folder, inline=False, judge_model=r["judge_model"]), endpoint=r["endpoint"]))
        else:
            require(r.get("fingerprint_version", 1) == 1, "Unknown fingerprint version")
            fingerprint = checksum(dict(job=job, judge_model=r["judge_model"]))
        require(r["request_fingerprint"] == fingerprint, "Result no longer matches job")
        expected = [i for i in job["annotation"]["items"] if job["level"] in i["levels"]]
        require([{k:v for k,v in i.items() if k not in {"label", "score"}} for i in r["items"]] == expected, "Result item mismatch")
        require(bool(r["items"]), "Empty successful result")
        require(r["language"] == job["language"], "Result language mismatch")
        require(all(i.get("label") in LABELS[r["language"]] and i["score"] == .5*LABELS[r["language"]].index(i["label"]) for i in r["items"]), "Label/score mismatch")
        judges.add(r["judge_model"])
        groups[(key[0], key[1])].append(r)
    require(len(languages) <= 1 and len(judges) <= 1, "Do not mix judge languages/models in one summary")
    output = []
    for configuration in sorted(configurations):
        levels = {l: scores(groups[(configuration,l)]) for l in LEVELS}
        values = [levels[l]["overall"] for l in LEVELS]
        output.append(dict(configuration=configuration, levels=levels,
                           overall=mean(values) if all(v is not None for v in values) else None))
    return dict(method="Item mean within each clip/dimension, clip macro mean per dimension, equal three dimensions, equal L1/L2/L3; own available coverage for each configuration.",
                configurations=output, exclusions=exclusions, missing_or_failed_not_zero=True,
                expected_jobs_in_this_run=len(jobs), scope="Coverage is computed over the supplied job directories.")
