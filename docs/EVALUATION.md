# Evaluation protocol

The default judge is GPT-5.6 Sol with high reasoning effort. One call evaluates all applicable checklist items for one clip under one representation setting. This package accepts already-generated videos and uses the provided annotations and judge instructions.

## Evidence and alignment

The evaluator automatically selects and extracts reference and generated frames at corresponding times. No manual frame selection or alignment is needed. If a generated video is too short to cover an evaluation clip, that clip is recorded as a preparation failure.

The following steps describe the internal frame-selection algorithm, `mandatory_evidence_then_temporal_coverage_max50_v1`:

1. Include clip endpoints, item evidence and interval endpoints/midpoints, annotated sample frames, cut-adjacent frames, and approximately 8 Hz temporal samples.
2. Above 50 unique frames, retain all mandatory evidence, item endpoints, clip endpoints, and cut-adjacent frames. Fill remaining slots by maximizing distance from retained frames, with deterministic tie breaking.
3. Fail preparation if mandatory evidence alone exceeds 50; do not silently drop evidence or checks.

Reference frames are decoded from the full video using the source offset. Generated frames are aligned using rounded interval boundaries and nearest local time, with a maximum local mismatch of 0.51 generated-frame periods. Alignment follows video timestamps; it does not search for matching actions or change their timing.

Each selected instant becomes a 960 × 1136 JPEG: reference above and generated below, with aspect-preserving thumbnails and frame/time labels. Images are submitted chronologically with high image detail. The text payload contains the reference entity table and the applicable items. Identity-context references are included as text; images from other clips are not appended.

Frames are decoded from the complete videos, and each prepared image is hashed for integrity checks.

## Parsing and aggregation

The only labels are Unsatisfied, Partially satisfied, and Fully satisfied, mapped to 0, 0.5, and 1. Their number and order must match the applicable checklist exactly. Invalid output, incomplete answers, unexpected tool calls, a wrong model, refusals, and transport errors do not yield a numerical zero.

For each dimension, average item scores within each clip, then average those clip means equally for each configuration and setting. Clips with no items in a dimension are excluded from that dimension's denominator. Average camera, static, and dynamic scores equally, then average L1/L2/L3 equally. An absent required dimension or setting produces `null`. Scores use a 0–100 scale. Configurations use their own available coverage, without a common-case intersection.

You can evaluate just one setting. An L2-only run, for example, still reports the available L2 dimension and category scores; only the configuration-wide overall score across L1/L2/L3 is unavailable (`null`).

The summary includes prepared jobs with missing responses and batch preparation failures. Report coverage alongside scores. Do not combine duplicate configuration/setting/clip jobs, different judges, or repeated trials in one summary.

Each configuration's L1/L2/L3 summary also contains a `categories` breakdown. Each category reports its parent `dimension`, `score` on a 0–100 scale, contributing `clips`, and total scored `items`. Category scores average items within each clip, then average those clip means equally. An absent category has `score: null`, `clips: 0`, and `items: 0`. Only successful evaluations contribute.

| Dimension | Categories |
|---|---|
| Static | `object_presence`, `object_appearance`, `object_relation` |
| Dynamic | `action_event`, `object_motion` |
| Camera | `camera_target`, `camera_position`, `camera_translation`, `camera_rotation`, `camera_zoom`, `cut_count` |

The category breakdown is supplementary: dimension scores continue to use all applicable items within each clip, rather than an equal average of category scores. The overall scoring rule is unchanged.

## Execution and resumption

`judge` previews locally unless `--execute` is provided. `--response-file` imports an existing response without contacting a model service. Live execution sends a direct HTTPS POST to `https://openrouter.ai/api/v1/chat/completions` using `openai/gpt-5.6-sol`. It fixes `provider.only` to `["openai"]`, disables fallbacks and streaming, requires parameter support, and uses high reasoning effort and strict JSON-schema output. Authentication comes from `CINERECON_API_KEY`. An optional `CINERECON_JUDGE_URL` override must accept the same request fields. Credentials are not stored; endpoint URLs must not embed credentials, and redirects are refused.

The batch command defaults to 8 workers and 20 requests per minute within one process. Adjust these limits with `--workers` and `--rpm`. `configs/evaluator.json` records the defaults for reference; the CLI does not automatically load it.

To resume, rerun the same `judge` command with the same inputs and settings; successful jobs are skipped. Add `--retry-failed` to retry failed or interrupted requests. Content safety refusals are not retried by this option. When changing a reconstruction video or judge settings, prepare jobs in a new output directory.

Per-job locks prevent concurrent duplicate execution. The evaluator checks request fingerprints and image hashes before reusing results. Each invocation sends at most one request per selected job.

Saved outputs contain ratings, response-model identity, returned provider identity, status, timing, source hashes, and request fingerprints. Fingerprints include the request configuration and endpoint. Extra fields returned by the provider are discarded.

## Batch inputs

The cases manifest lists `configuration`, `level`, `video_id`, and `generated` for each reconstructed full video. Relative paths resolve against the cases file. Every annotated clip for that source video is prepared. Preparation does not contact the judge.

```bash
python -m cinerecon prepare-batch --cases my_cases.json --output runs/evaluation
python -m cinerecon judge --jobs-root runs/evaluation --workers 8 --rpm 20 --execute --output runs/judge_status.json
python -m cinerecon summarize --jobs-root runs/evaluation --output runs/summary.json
```

Keep different generated versions, judges, and repeated trials in separate run roots.
