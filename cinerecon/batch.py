from pathlib import Path
from .common import inside, read, require, save, sha
from .evaluation import prepare


def prepare_cases(root, cases_file, output, language="en"):
    root, cases_file, output = Path(root), Path(cases_file), Path(output)
    manifest = read(root/"data/manifest.json")
    videos = {v["video_id"]:v for v in manifest["videos"]}
    cases = read(cases_file)["cases"]
    seen = set()
    for case in cases:
        key = (case["configuration"], case["level"], case["video_id"])
        require(key not in seen, "Duplicate reconstruction case")
        seen.add(key)
        require(case["video_id"] in videos and case["level"] in {"L1","L2","L3"}, "Invalid case")
        require(all(x.isalnum() or x in "_-" for x in case["configuration"]), "Use a simple configuration ID")
    rows = []
    for case in cases:
        generated = Path(case["generated"])
        if not generated.is_absolute():
            generated = cases_file.resolve().parent / generated
        video = videos[case["video_id"]]
        reference = inside(root, video["path"])
        for clip in video["clip_ids"]:
            folder = output/case["configuration"]/case["level"]/clip
            row = dict(configuration=case["configuration"], level=case["level"], clip_id=clip, video_id=case["video_id"])
            try:
                if (folder/"job.json").exists():
                    prior = read(folder/"job.json")
                    expected_annotation = read(root/"data/annotations"/language/f"{clip}.json")
                    expected_prompt = (root/"prompts/evaluation"/language/(case["level"]+".txt")).read_text(encoding="utf-8")
                    require(prior["language"] == language and prior["generated_sha256"] == sha(generated) and prior["source_sha256"] == sha(reference), "Cached media/language changed")
                    require(prior["annotation"] == expected_annotation and prior["prompt"] == expected_prompt, "Cached protocol changed")
                    row["status"] = "cached_prepared"
                else:
                    prepare(root,clip,case["level"],language,reference,generated,folder,case["configuration"])
                    row["status"] = "prepared"
            except Exception as error:
                row.update(status="prepare_failed", error=type(error).__name__, reason=str(error))
            rows.append(row)
            save(output/"preparation_report.json",dict(language=language,cases=len(cases),expected_jobs=sum(len(videos[c["video_id"]]["clip_ids"]) for c in cases),jobs=rows))
    return dict(prepared=sum(r["status"] in {"prepared","cached_prepared"} for r in rows), failed=sum(r["status"]=="prepare_failed" for r in rows), report=str(output/"preparation_report.json"))
