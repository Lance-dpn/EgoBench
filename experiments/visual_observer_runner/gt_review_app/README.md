# Clean v2 GT Review App

Local React web app for reviewing and correcting observer clean-v2 GT datasets.

## Data Source

The app reads and writes:

```text
experiments/visual_observer_runner/eval/observer_dataset_clean_v2/{scenario}/05_observer_dataset_with_gt.json
```

Supported scenarios are `order`, `retail`, `restaurant`, and `kitchen`.

## Build

Run from this directory:

```bash
cd experiments/visual_observer_runner/gt_review_app/frontend
npm install
npm run build
```

## Start

Run from the repository root:

```bash
python experiments/visual_observer_runner/gt_review_app/server.py --host 127.0.0.1 --port 18100
```

Open:

```text
http://127.0.0.1:18100
```

For React development, start the Python API server on `18100`, then run:

```bash
cd experiments/visual_observer_runner/gt_review_app/frontend
npm run dev
```

Open the Vite dev server URL. API calls are proxied to `127.0.0.1:18100`.

## Review Workflow

1. Select a scenario.
2. Filter by video, target kind, referent type, confidence, status, or search text.
3. Select a case.
4. Inspect the video, key frame, visual query, source instruction, Event GT, and Detail GT.
5. Edit Event GT or Detail GT fields.
6. Use the timeline controls to seek video frames and set primary start, key frame, and primary end.
7. Mark the human review status as `verified`, `needs_fix`, or `unreviewed`.
8. Save the edited section.

The case header includes quick actions for `Mark verified` and `Needs fix`.
Use `Mark verified` when the visible evidence and GT are correct and no field
edits are needed.

The app directly updates the active clean-v2 dataset JSON. Before every save, it
creates a backup under:

```text
experiments/visual_observer_runner/eval/observer_dataset_clean_v2/{scenario}/review_backups/
```

## Validation

Save operations validate that:

- event time ranges are `[start, end]`;
- event ranges are no longer than two seconds;
- `key_frame_time` is inside `primary_content_range`;
- `detail_gt.target_kind` matches `visual_query_v1.target.kind`;
- the dataset can be parsed after writing.

## Human Review State

Each case can carry a case-level human review state:

```json
{
  "human_review_status": "verified",
  "human_reviewed_at": "2026-06-06T00:00:00+00:00",
  "human_reviewer": "manual_review"
}
```

Missing `human_review_status` is treated as `unreviewed` in the UI and API. The
field is written only when a reviewer saves the Case Review panel.

## Notes

- This app intentionally has no authentication. Bind only to trusted local or LAN interfaces.
- Key frame images are extracted on demand with `ffmpeg` and cached under `experiments/visual_observer_runner/cache/gt_review_frames/`.
- The previous bootstrap review UI has been replaced; this app is clean-v2 only.
