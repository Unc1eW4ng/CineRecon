from pathlib import Path
import re
from .common import DIMENSIONS, LEVELS, inside, read, require, sha
from .sampling import frames_for


def validate_annotation(a):
    require(a["start_frame"] == 0 and a["end_frame"] >= 0 and a["fps"] > 0, "Invalid clip range")
    require(a["source_frame_offset"] >= 0, "Invalid source offset")
    entities = {e["source_entity_id"] for e in a["entities"]}
    require(len(entities) == len(a["entities"]), "Duplicate entity IDs")
    keys = set()
    for e in a["entities"]:
        require(isinstance(e["identification"], str) and bool(e["identification"]), "Missing identification")
        first = e["first_appearance_frame"]
        require(first is None or 0 <= first <= a["end_frame"], "Invalid first appearance")
    for i in a["items"]:
        require(i["item_key"] not in keys, "Duplicate item key")
        keys.add(i["item_key"])
        require(bool(i["statement"]) and i["category"] in set.union(*DIMENSIONS.values()), "Invalid item")
        require(bool(i["levels"]) and set(i["levels"]) <= set(LEVELS), "Invalid levels")
        require(set(i["subject_ids"]) <= entities, "Unresolved entity reference")
        require(0 <= i["start_frame"] <= i["end_frame"] <= a["end_frame"], "Invalid item frames")
        require(all(0 <= f <= a["end_frame"] for f in i["evidence_frames"]), "Invalid evidence")
    for level in LEVELS:
        require(any(level in i["levels"] for i in a["items"]), "Empty setting checklist")
        frames_for(a, level)


def validate(root, media=False):
    root = Path(root)
    manifest = read(root / "data/manifest.json")
    counts = {"videos": len(manifest["videos"]), "clips": 0, "unique_items": 0, "setting_checks": 0}
    by_id = {}
    for row in manifest["clips"]:
        p = inside(root, row["annotations"]["en"])
        require(sha(p) == row["sha256"]["en"], f"Annotation checksum mismatch: {p.name}")
        a = read(p)
        require(not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", p.read_text(encoding="utf-8")), "Unexpected non-English text")
        validate_annotation(a)
        require(a["clip_id"] == row["clip_id"], "Clip ID mismatch")
        require(a["clip_id"] not in by_id, "Duplicate clip")
        by_id[a["clip_id"]] = a
        counts["clips"] += 1
        counts["unique_items"] += len(a["items"])
        counts["setting_checks"] += sum(len(i["levels"]) for i in a["items"])
    for a in by_id.values():
        for e in a["entities"]:
            for context in e.get("identity_context", []):
                target = by_id[context["clip_id"]]
                require(target["video_id"] == a["video_id"], "Identity context crosses videos")
                require(all(0 <= f <= target["end_frame"] for f in context["frames"]), "Invalid context frames")
    for key, value in counts.items():
        require(value == manifest["counts"][key], f"Count mismatch: {key}")
    if media:
        for video in manifest["videos"]:
            p = inside(root, video["path"])
            require(p.exists(), f"Reference video missing: {video['video_id']}")
            require(sha(p) == video["sha256"], f"Reference video changed: {video['video_id']}")
    return dict(valid=True, media_verified=media, **counts)
