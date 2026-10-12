"""Portable one-request-per-clip judge; no tools or agent loop in evaluation."""
import base64
import datetime
import fcntl
import http.client
import io
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
from pathlib import Path
from .common import LABELS, checksum, inside, loads, read, require, save, sha
from .dataset import validate_annotation
from .media import extract, mapping, pair_image, probe
from .sampling import SAMPLING_VERSION, frames_for


DEFAULT_MODEL = "openai/gpt-5.6-sol"
DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def prepare(root, clip_id, level, language, reference, generated, output, model_config):
    """Publish only complete preparation bundles; extraction failures leave no partial job."""
    output = Path(output)
    require(not output.exists() or (output.is_dir() and not any(output.iterdir())), "Use an empty job directory; existing results are immutable")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=output.parent) as temporary:
        stage = Path(temporary)
        result = _prepare_inplace(root, clip_id, level, language, reference, generated, stage, model_config)
        if output.exists():
            output.rmdir()
        stage.rename(output)
    result["directory"] = str(output)
    return result


def _prepare_inplace(root, clip_id, level, language, reference, generated, output, model_config):
    require(language == "en", "This distribution uses English evaluation only")
    root, output = Path(root), Path(output)
    a = read(root / "data/annotations" / language / f"{clip_id}.json")
    validate_annotation(a)
    require(not output.exists() or not any(output.iterdir()), "Use an empty job directory; existing results are immutable")
    source_hash, generated_hash = sha(reference), sha(generated)
    require(source_hash == a["source_sha256"], "Reference SHA256 mismatch")
    ref_meta, gen_meta = probe(reference), probe(generated)
    require(abs(ref_meta["fps"]-a["fps"]) < 1e-6, "Reference FPS mismatch")
    require(a["source_frame_offset"] + a["end_frame"] < ref_meta["frames"], "Reference clip unavailable")
    pairs = mapping(a, gen_meta, frames_for(a, level))
    output.mkdir(parents=True, exist_ok=True)
    (output / "pairs").mkdir()
    with tempfile.TemporaryDirectory() as temp:
        refs = extract(reference, [p["source_absolute_frame"] for p in pairs], Path(temp)/"reference")
        renders = extract(generated, [p["generated_absolute_frame"] for p in pairs], Path(temp)/"rendered")
        for p in pairs:
            path = output / "pairs" / f"pair_{p['source_local_frame']:05d}.jpg"
            pair_image(refs[p["source_absolute_frame"]], renders[p["generated_absolute_frame"]], path, clip_id, p["source_local_frame"], p["source_local_sec"])
            p.update(path=path.relative_to(output).as_posix(), sha256=sha(path))
    prompt = (root / "prompts/evaluation" / language / f"{level}.txt").read_text(encoding="utf-8")
    job = dict(schema_version=1, clip_id=clip_id, video_id=a["video_id"], level=level, language=language,
               configuration=model_config, annotation=a, prompt=prompt, pairs=pairs,
               source_sha256=source_hash, generated_sha256=generated_hash,
               source_video=ref_meta, generated_video=gen_meta, sampling=SAMPLING_VERSION)
    save(output/"job.json", job)
    save(output/"request_preview.json", request(job, output, inline=False))
    return dict(clip_id=clip_id, items=len([i for i in a["items"] if level in i["levels"]]), images=len(pairs), directory=str(output))


def request(job, folder, inline=True, judge_model=DEFAULT_MODEL):
    a = job["annotation"]
    items = [i for i in a["items"] if job["level"] in i["levels"]]
    refs = [dict(entity_id=e["source_entity_id"], name=e["name"], source_name=e["name"],
                 source_identification=e["identification"], first_appearance_frame=e["first_appearance_frame"],
                 identity_context=e.get("identity_context"), numbered=e["numbered"], reference_only=True) for e in a["entities"]]
    rows = []
    for i in items:
        row = {k: i[k] for k in ["statement", "category", "start_frame", "end_frame", "subject_ids", "evidence_frames"]}
        row.update(assertion_id=i["item_key"].split(":", 1)[-1], clip_id=a["clip_id"], required_subject_ids=i["subject_ids"],
                   local_start_sec=i["start_frame"]/a["fps"], local_end_exclusive_sec=(i["end_frame"]+1)/a["fps"])
        rows.append(row)
    require(len({r["assertion_id"] for r in rows}) == len(rows), "Duplicate assertion IDs")
    payload = dict(frame_space="clip_local", frame_index_base=0, fps=a["fps"], first_appearance_definition=a["first_appearance_definition"],
                   reference_entities=refs, items=rows, judge_input_modality="aligned_frame_pairs",
                   input_media=dict(source_full_sha256=job["source_sha256"], generated_full_sha256=job["generated_sha256"]),
                   frame_pairs=[{k:p[k] for k in ["source_local_frame", "generated_local_frame", "source_local_sec", "generated_local_sec"]} for p in job["pairs"]])
    text = "The subsequent images are arranged in increasing temporal order. The upper half of each image is SOURCE, and the lower half is GENERATED; compare the same local moment."
    content = [{"type":"text", "text":job["prompt"]}, {"type":"text", "text":text}]
    for p in job["pairs"]:
        path = inside(folder, p["path"])
        require(sha(path) == p["sha256"], "Prepared image changed")
        url = "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode() if inline else "[inline image bytes omitted]"
        content.append({"type":"image_url", "image_url":{"url":url, "detail":"high"}})
    content.append({"type":"text", "text":json.dumps(payload, ensure_ascii=False)})
    return dict(model=judge_model, messages=[{"role":"user", "content":content}], reasoning_effort="high", stream=False,
                provider={"only":["openai"], "allow_fallbacks":False, "require_parameters":True},
                response_format={"type":"json_schema", "json_schema":{"name":"clip_checklist_judgments", "strict":True,
                "schema":{"type":"object", "properties":{"results":{"type":"array", "items":{"type":"string", "enum":LABELS[job["language"]]}}}, "required":["results"], "additionalProperties":False}}})


def parse_response(raw, job):
    choices = raw.get("choices", [])
    require(len(choices) == 1, "Wrong number of choices")
    choice = choices[0]
    message = choice.get("message", {})
    if choice.get("finish_reason") == "content_filter" or message.get("refusal"):
        raise PermissionError("content_safety_refusal")
    require(choice.get("finish_reason") == "stop", "Incomplete response")
    require(not message.get("tool_calls"), "Unexpected tool call")
    parsed = loads(message["content"])
    require(isinstance(parsed, dict) and set(parsed) == {"results"}, "Invalid response fields")
    items = [i for i in job["annotation"]["items"] if job["level"] in i["levels"]]
    labels = parsed["results"]
    require(isinstance(labels, list) and len(labels) == len(items), "Incomplete label count")
    require(all(isinstance(v, str) and v in LABELS[job["language"]] for v in labels), "Invalid label")
    return [dict(i, label=v, score=LABELS[job["language"]].index(v)*.5) for i,v in zip(items,labels)]


def judge(folder, endpoint=None, judge_model=DEFAULT_MODEL, execute=False, response_file=None, retry_failed=False, rate_limiter=None, timeout=600):
    folder = Path(folder)
    endpoint = endpoint or os.environ.get("CINERECON_JUDGE_URL") or DEFAULT_ENDPOINT
    with (folder/"judge.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        job = read(folder/"job.json")
        preview = request(job, folder, inline=False, judge_model=judge_model)
        fingerprint = checksum(dict(job=job, request=preview, endpoint=endpoint))
        previous = folder/"result.json"
        if previous.exists():
            result = read(previous)
            require(result["request_fingerprint"] == fingerprint, "Existing result belongs to another request")
            if result["status"] == "success":
                return dict(status="cached_success", clip_id=job["clip_id"])
            require(result["status"] != "refused", "Content refusal is terminal; no automatic retry")
            require(retry_failed, "Failed request exists; explicitly select --retry-failed to retry")
        if not execute and response_file is None:
            return dict(status="dry_run", clip_id=job["clip_id"], images=len(job["pairs"]), request=preview)
        if response_file is None:
            url = urllib.parse.urlsplit(endpoint)
            require(url.scheme in {"https", "http"} and bool(url.hostname) and not url.username and not url.password and not url.query and not url.fragment, "Use an endpoint without embedded credentials or query parameters")
            api_key = os.environ.get("CINERECON_API_KEY")
            require(bool(api_key), "Set CINERECON_API_KEY in the environment")
        attempts = sorted((folder/"attempts").glob("*.json")) if (folder/"attempts").exists() else []
        if attempts and not previous.exists():
            require(retry_failed, "Previous request outcome unknown; inspect the attempt and use --retry-failed explicitly")
        number = len(attempts) + 1
        record = dict(attempt=number, started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      status="running", request_fingerprint=fingerprint, response_model=None,
                      origin="imported_response" if response_file else "live_single_call")
        audit_path = folder/"attempts"/f"{number:04d}.json"
        save(audit_path, record)
        start = time.monotonic()
        result = {k:job[k] for k in ["clip_id", "video_id", "level", "language", "configuration", "source_sha256", "generated_sha256"]}
        result.update(request_fingerprint=fingerprint, fingerprint_version=2, endpoint=endpoint, judge_model=judge_model, items=[], origin=record["origin"], status="failed")
        try:
            if response_file:
                raw = read(response_file)
            else:
                body = request(job, folder, inline=True, judge_model=judge_model)
                if rate_limiter:
                    rate_limiter()
                connection_type = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
                connection = connection_type(url.hostname, url.port, timeout=timeout)
                try:
                    connection.request("POST", url.path or "/", body=json.dumps(body, ensure_ascii=False).encode(),
                                       headers={"Content-Type":"application/json", "Authorization":"Bearer "+api_key})
                    response = connection.getresponse()
                    record["http_status"] = response.status
                    data = response.read()
                    # Direct requests do not follow redirects or retry automatically.
                    if response.status != 200:
                        raise urllib.error.HTTPError(endpoint, response.status, "Judge request failed", response.headers, io.BytesIO(data))
                    raw = loads(data.decode())
                finally:
                    connection.close()
            record.update(response_model=raw.get("model"), provider=raw.get("provider"))
            import re
            actual_model = (raw.get("model") or "").split("/")[-1]
            expected_model = judge_model.split("/")[-1]
            require(actual_model == expected_model or re.fullmatch(re.escape(expected_model)+r"-\d{4}-\d{2}-\d{2}", actual_model), "Unexpected response model")
            result["items"] = parse_response(raw, job)
            result["status"] = "success"
            record["status"] = "success"
        except PermissionError:
            result["status"] = record["status"] = "refused"
            record["error"] = "content_safety_refusal"
        except urllib.error.HTTPError as error:
            record["http_status"] = error.code
            # Do not store provider error text, which may echo credentials.
            body = error.read().decode(errors="replace").lower()
            refused = any(x in body for x in ("content_filter", "content policy", "content_policy", "safety refusal", "responsibleaipolicyviolation"))
            result["status"] = record["status"] = "refused" if refused else "failed"
            record["error"] = "content_safety_refusal" if refused else ("rate_limit" if error.code == 429 else "http_error")
        except Exception as error:
            record["status"] = "failed"
            record["error"] = type(error).__name__
        finally:
            record["elapsed_sec"] = time.monotonic() - start
            result.update(response_model=record["response_model"], provider=record.get("provider"), error=record.get("error"), attempt=number)
            save(audit_path, record)
            save(previous, result)
        return result
