import hashlib
import json
import os
import tempfile
from pathlib import Path

LEVELS = ("L1", "L2", "L3")
DIMENSIONS = {
    "camera": {"camera_target", "camera_position", "camera_translation", "camera_rotation", "camera_zoom", "cut_count"},
    "static": {"object_presence", "object_appearance", "object_relation"},
    "dynamic": {"action_event", "object_motion"},
}
LABELS = {
    "en": ["Unsatisfied", "Partially satisfied", "Fully satisfied"],
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def loads(text):
    return json.loads(text, object_pairs_hook=unique)


def read(path):
    return loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
        temporary = f.name
    os.replace(temporary, path)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checksum(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def inside(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    require(path.is_relative_to(root), "Path escapes its bundle")
    return path
