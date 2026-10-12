# Generation prompts and representation settings

This document describes the reconstruction task, prompts, representation settings, and Blender MCP environment.

## Input and task

The reconstruction input is the complete reference video. The agent creates an editable Blender scene and renders a complete reconstruction video. The evaluation clips are temporal intervals used for scoring after reconstruction; they are not separate generation inputs. Evaluation annotations, entity tables, checklists, and answers must not be supplied to the reconstruction agent.

Choose the appropriate prompt:

| Setting | Prompt | Representation requirement |
|---|---|---|
| L1: Proxy | [L1.txt](../prompts/reconstruction/en/L1.txt) | A small number of simple primitives or simple combinations; preserve subject counts, identity correspondence, coarse proportions, relative size, major colors, and necessary moving parts. Detailed category-specific shape and fine appearance are not required. |
| L2: Simplified | [L2.txt](../prompts/reconstruction/en/L2.txt) | Recognizable objects with low-complexity geometry; approximately match category cues, silhouettes, important components, major colors, salient patterns, and material categories. Fine textures, small decorations, and other secondary details may be simplified. |
| L3: Detailed | [L3.txt](../prompts/reconstruction/en/L3.txt) | Reconstruct the specific visible instances, including local shape, structure, appearance, materials, articulated actions, and relevant imaging effects. Matching only the object category is insufficient. |

These settings vary the required representation fidelity. They do not relax the requirement to reproduce spatial relations, action events, contact, motion timing, camera changes, or shot transitions. Even under Proxy, clearly visible articulated actions must not be replaced entirely by whole-object rigid motion. L3 follows the reference's visual style; it does not require converting stylized footage into photorealism.

Representation settings are separate from model reasoning-effort settings. `L1`, `L2`, and `L3` do not mean low, medium, and high model reasoning effort. The evaluator's default `high` reasoning effort applies to the VLM judge, not the reconstruction representation.

## Blender MCP and runtime settings

This section describes the environment used to generate reconstructions. Evaluating existing videos does not require Blender or Blender MCP.

The generation setup uses `ahujasid/blender-mcp` as the bridge between the agent and a running Blender instance. The agent's MCP client starts the local `blender-mcp` process; that process connects to the Blender add-on's socket server. This provides the scene inspection, editing, and visual feedback used during reconstruction. The prompts explicitly require `get_scene_info` before work and again before completion, with scene inspections and screenshots after substantial changes.

| Component | Configuration |
|---|---|
| Blender | Version 5.2.1; the task prompts specify the Blender 5.2 series |
| MCP integration | `blender-mcp` 1.9.1 and its installed Blender add-on |
| MCP connection | Local MCP subprocess connected to the add-on at `BLENDER_HOST=127.0.0.1`; `BLENDER_PORT` selects the task's Blender worker |
| Task isolation | A dedicated Blender process, socket port, working directory, and output directory per active task; the worker is assigned a GPU |
| Server startup timeout | 30 seconds |
| MCP tool-call timeout | 300 seconds per call; this is not the total reconstruction time budget |
| MCP telemetry | Disabled with `BLENDER_MCP_DISABLE_TELEMETRY=1` |
| Display environment | Blender runs with an X11 virtual display through Xvfb, allowing viewport inspection on the server |
| Rendering | Cycles, CUDA GPU, and denoising, as required by the generation prompts |
| External generation integration | The optional external 3D-generation MCP integration is disabled in the baseline; the prompts prohibit external asset and generation services |

Use matching socket ports for the MCP bridge and its Blender worker, and separate ports for simultaneous workers. Choose port numbers and filesystem locations for your deployment.

Blender MCP is used for reconstruction only. The VLM judge does not connect to Blender MCP or run an agent loop: it receives prepared frame pairs and the applicable checklist in one model request per evaluation clip. Evaluation's default 8 workers and 20 requests per minute are independent of the generation worker configuration.

## Shared reconstruction requirements

The agent chooses its local analysis tools and how to prepare reference material, using the Blender MCP environment described above.

All three prompts require:

- Editable 3D scene objects, without replacing reconstruction with the reference video, background frames, or projected reference images.
- The reference frame rate, frame count, duration, timeline, resolution, and aspect ratio. Lower-resolution test renders are allowed; the final render must use the reference resolution.
- Persistent subject correspondence, spatial and occlusion relations, support and contact, action ordering, and correct image-left/image-right relationships.
- Camera composition and motion aligned to the reference, without substituting incorrect subject translation or scaling for camera changes.
- No temporal shifts, speed changes, frame interpolation, or repeated frames to hide mismatches.
- No external asset or generation services, other tasks' outputs, or evaluation-side annotations and answers.

The standard prompts include a render-inspect-revise process: inspect the initial scene, compare selected frames or intervals at matching times, correct visible discrepancies within the chosen setting, and verify the final scene and files. The agent selects inspection views covering shots, state changes, and important events.

## Placeholders and deliverables

Replace `<VIDEO_PATH>` with the complete reference-video path and `<OUTPUT_DIR>` with a dedicated output directory for one model configuration, reference video, and setting. Use a separate directory for each run. The prompts request:

```text
<OUTPUT_DIR>/
├── scene.blend
├── reconstruction.mp4
├── comparison/
│   ├── original_vs_reconstruction.mp4
│   └── original_vs_reconstruction_contact_sheet.jpg
└── report.md
```

The comparison video places ORIGINAL on the left and RECONSTRUCTION on the right, with synchronized timelines and preserved aspect ratios. The report records implementation, inspection evidence, revisions, and final verification; it does not replace actual reconstruction or correction.

## Passing results to evaluation

The evaluator reads `reconstruction.mp4`, the reference video, and the evaluation annotations. It does not read the generated report or comparison video as scoring evidence. The `.blend` file remains a reconstruction deliverable, but this video-based evaluator does not inspect its contents.

Set the cases-file `generated` field to the complete rendered video's path and `level` to the setting used for generation. Videos produced with another directory layout or filename are also accepted. The evaluator prepares all annotated clips automatically; do not manually cut or retime the generated video. See [batch evaluation](../README.md#batch-evaluation) for the cases-file format and commands.
