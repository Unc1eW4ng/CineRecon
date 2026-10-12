# Dataset specification

The dataset contains 50 complete reference videos and 360 evaluation clips. Clips last at most two seconds and may overlap or cross shot boundaries. Each evaluation clip has a stable `video*_cp*` identifier.

All evaluation clips and checklist statements were initially annotated by Codex powered by GPT-6, followed by multiple rounds of human review and refinement.

## Coordinates and entity references

The fields below are already included in the supplied annotations and are read automatically by the evaluator. You do not need to fill them in or modify them to evaluate reconstruction videos.

- Frame indices are zero-based and local to the clip; `end_frame` is inclusive.
- `source_frame_offset + local_frame` identifies a frame in the complete reference video.
- Local time is `local_frame / fps`; the interval ends at `(end_frame + 1) / fps`.
- `evaluation_sample_frames` and `evaluation_cut_frames` specify sampling frames and shot boundaries.
- Each clip has its own entity table. `source_entity_id` preserves identity; `name` is its local designation. `identification` and `first_appearance_frame` are reference-only identity cues.
- Optional `identity_context` points to related clips and frames within the same reference video, with an explanation of their relevance.

Each checklist item contains `item_key`, `statement`, `category`, applicable `levels`, frame endpoints, `evidence_frames`, and `subject_ids`. Entity descriptions identify the reference subjects; they do not add independent appearance requirements to Proxy scoring.

## Counts

| Count | Value |
|---|---:|
| Annotation files | 360 |
| Distinct checklist records | 35,836 |
| L1 checks | 9,647 |
| L2 checks | 20,021 |
| L3 checks | 20,000 |
| Setting-expanded checks | 49,668 |

A record shared by L2 and L3 counts once in the distinct-record total. Each annotation file contains checklist statements, stable IDs, categories, frame coordinates, source hashes, and entity references. The schema is `data/annotation.schema.json`; the validator additionally checks reference integrity and frame bounds.

## Reference media

Reference videos belong at `media/reference/video1.mp4` through `video50.mp4`. Run `python -m cinerecon validate --media` to check their hashes. The release includes all 50 reference videos. Redistribution permissions remain under review.
