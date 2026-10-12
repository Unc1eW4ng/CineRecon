"""The frozen max-50 evidence selection rule used in the original evaluator."""
import math
from .common import require

SAMPLING_VERSION = "mandatory_evidence_then_temporal_coverage_max50_v1"


def frames_for(annotation, level):
    a = annotation
    frames = {0, a["end_frame"]}
    for item in a["items"]:
        if level in item["levels"]:
            frames.update(item["evidence_frames"] + [item["start_frame"], item["end_frame"], (item["start_frame"] + item["end_frame"]) // 2])
    frames.update(a["evaluation_sample_frames"])
    for cut in a["evaluation_cut_frames"]:
        frames.update(f for f in [cut - 1, cut, cut + 1] if 0 <= f <= a["end_frame"])
    frames.update(round(i * a["fps"] / 8) for i in range(math.ceil((a["end_frame"] + 1) * 8 / a["fps"])) if round(i * a["fps"] / 8) <= a["end_frame"])
    require(min(frames) >= 0 and max(frames) <= a["end_frame"], "Out-of-range evidence")
    if len(frames) > 50:
        required = {0, a["end_frame"]}
        for item in a["items"]:
            if level in item["levels"]:
                required.update(item["evidence_frames"] + [item["start_frame"], item["end_frame"]])
        for cut in a["evaluation_cut_frames"]:
            required.update(f for f in [cut - 1, cut, cut + 1] if 0 <= f <= a["end_frame"])
        require(len(required) <= 50, "Mandatory evidence exceeds the 50-image limit; do not drop items")
        while len(required) < 50:
            remaining = frames - required
            if not remaining:
                break
            required.add(max(remaining, key=lambda f: (min(abs(f-r) for r in required), -f)))
        frames = required
    return sorted(frames)
