import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const EMPTY_FILTERS = {
  q: "",
  video_id: "",
  target_kind: "",
  referent_type: "",
  confidence: "",
  status: "",
  human_review_status: "",
  menu_label: "",
  menu_instance: "",
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

function postJson(path, payload) {
  return api(path, { method: "POST", body: JSON.stringify(payload) });
}

function toLines(value) {
  return Array.isArray(value) ? value.join("\n") : value || "";
}

function fromLines(value) {
  return String(value || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function formatRange(value) {
  if (!Array.isArray(value)) return "";
  return value.map((item) => Number(item).toFixed(2)).join(" - ");
}

function parseRange(start, end) {
  const a = Number(start);
  const b = Number(end);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  return [a, b];
}

function confidenceClass(value) {
  if (value === "high") return "ok";
  if (value === "medium") return "warn";
  if (value === "low") return "bad";
  return "";
}

function humanReviewClass(value) {
  if (value === "verified") return "ok";
  if (value === "needs_fix") return "bad";
  return "muted";
}

function App() {
  const [datasets, setDatasets] = useState([]);
  const [scenario, setScenario] = useState("");
  const [dataset, setDataset] = useState(null);
  const [cases, setCases] = useState([]);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [detail, setDetail] = useState(null);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    loadDatasets();
  }, []);

  useEffect(() => {
    if (!scenario) return;
    loadScenario(scenario);
  }, [scenario]);

  useEffect(() => {
    if (!scenario) return;
    loadCases();
  }, [scenario, filters]);

  useEffect(() => {
    if (!scenario || !selectedCaseId) {
      setDetail(null);
      return;
    }
    loadCase(selectedCaseId);
  }, [scenario, selectedCaseId]);

  async function loadDatasets() {
    setLoading(true);
    setError("");
    try {
      const payload = await api("/api/datasets");
      const rows = payload.datasets || [];
      setDatasets(rows);
      if (rows.length) setScenario(rows[0].scenario);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadScenario(nextScenario) {
    setLoading(true);
    setError("");
    try {
      const payload = await api(`/api/datasets/${encodeURIComponent(nextScenario)}`);
      setDataset(payload);
      setSelectedCaseId("");
      setDetail(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadCases() {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    try {
      const payload = await api(`/api/datasets/${encodeURIComponent(scenario)}/cases?${params}`);
      const rows = payload.cases || [];
      setCases(rows);
      if (!selectedCaseId && rows.length) setSelectedCaseId(rows[0].case_id);
      if (selectedCaseId && !rows.some((row) => row.case_id === selectedCaseId)) {
        setSelectedCaseId(rows[0]?.case_id || "");
      }
    } catch (err) {
      setError(err.message);
    }
  }

  async function loadCase(caseId) {
    setError("");
    try {
      const payload = await api(
        `/api/datasets/${encodeURIComponent(scenario)}/cases/${encodeURIComponent(caseId)}`,
      );
      setDetail(payload);
    } catch (err) {
      setError(err.message);
    }
  }

  async function refreshCurrent() {
    await Promise.all([loadScenario(scenario), loadCases()]);
    if (selectedCaseId) await loadCase(selectedCaseId);
  }

  function updateFilter(key, value) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function clearFilters() {
    setFilters(EMPTY_FILTERS);
  }

  function selectNextCase() {
    const index = cases.findIndex((item) => item.case_id === selectedCaseId);
    if (index < 0) return;
    const next = cases[index + 1] || cases[index];
    if (next?.case_id) setSelectedCaseId(next.case_id);
  }

  const options = useMemo(() => buildFilterOptions(dataset), [dataset]);

  return (
    <div className="appShell">
      <aside className="sidebar">
        <header className="brand">
          <div>
            <h1>Clean v2 GT Review</h1>
            <p>Observer dataset calibration</p>
          </div>
          <button className="smallButton" onClick={refreshCurrent} disabled={!scenario}>
            Refresh
          </button>
        </header>

        <section className="panel">
          <label>Scenario</label>
          <select value={scenario} onChange={(event) => setScenario(event.target.value)}>
            {datasets.map((item) => (
              <option key={item.scenario} value={item.scenario}>
                {item.scenario} ({item.case_count})
              </option>
            ))}
          </select>
          <DatasetStats dataset={dataset} />
        </section>

        <section className="panel filters">
          <label>Search</label>
          <input
            value={filters.q}
            onChange={(event) => updateFilter("q", event.target.value)}
            placeholder="case id, value, hint..."
          />
          <label>Video</label>
          <select value={filters.video_id} onChange={(event) => updateFilter("video_id", event.target.value)}>
            <option value="">All videos</option>
            {options.videoIds.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
          <div className="twoCols">
            <div>
              <label>Target</label>
              <select value={filters.target_kind} onChange={(event) => updateFilter("target_kind", event.target.value)}>
                <option value="">All</option>
                {options.targetKinds.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label>Referent</label>
              <select
                value={filters.referent_type}
                onChange={(event) => updateFilter("referent_type", event.target.value)}
              >
                <option value="">All</option>
                {options.referentTypes.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="twoCols">
            <div>
              <label>Confidence</label>
              <select value={filters.confidence} onChange={(event) => updateFilter("confidence", event.target.value)}>
                <option value="">All</option>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </div>
            <div>
              <label>Status</label>
              <select value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}>
                <option value="">All</option>
                {options.statuses.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <label>Human review</label>
          <select
            value={filters.human_review_status}
            onChange={(event) => updateFilter("human_review_status", event.target.value)}
          >
            <option value="">All</option>
            {options.humanReviewStatuses.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
          <div className="twoCols">
            <div>
              <label>Menu</label>
              <select value={filters.menu_label} onChange={(event) => updateFilter("menu_label", event.target.value)}>
                <option value="">All</option>
                {options.menuLabels.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label>Menu #</label>
              <select
                value={filters.menu_instance}
                onChange={(event) => updateFilter("menu_instance", event.target.value)}
              >
                <option value="">All</option>
                {options.menuInstances.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button className="fullButton" onClick={clearFilters}>
            Clear filters
          </button>
        </section>

        <section className="casePanel">
          <div className="casePanelHeader">
            <div>
              <h2>Cases</h2>
              <p>{cases.length} matching</p>
            </div>
          </div>
          <CaseList cases={cases} selectedCaseId={selectedCaseId} onSelect={setSelectedCaseId} />
        </section>

        {loading && <div className="notice">Loading...</div>}
        {error && <div className="notice error">{error}</div>}
        {message && <div className="notice success">{message}</div>}
      </aside>

      <main className="main">
        <section className="detailPane">
          {detail ? (
            <CaseDetail
              detail={detail}
              scenario={scenario}
              onSaved={async (text) => {
                setMessage(text);
                setTimeout(() => setMessage(""), 3500);
                await refreshCurrent();
              }}
              onError={setError}
              onAdvance={selectNextCase}
            />
          ) : (
            <div className="emptyState">
              <h2>Select a case</h2>
              <p>Choose a case to inspect video evidence, key frame, visual query, and GT fields.</p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function buildFilterOptions(dataset) {
  if (!dataset) {
    return {
      videoIds: [],
      targetKinds: [],
      referentTypes: [],
      statuses: [],
      humanReviewStatuses: [],
      menuLabels: [],
      menuInstances: [],
    };
  }
  return {
    videoIds: dataset.video_ids || [],
    targetKinds: Object.keys(dataset.target_kind_counts || {}).sort(),
    referentTypes: Object.keys(dataset.referent_type_counts || {}).sort(),
    statuses: Object.keys(dataset.status_counts || {}).sort(),
    humanReviewStatuses: Object.keys(dataset.human_review_status_counts || {}).sort(),
    menuLabels: Object.keys(dataset.menu_label_counts || {}).filter((value) => value !== "unknown").sort(),
    menuInstances: Object.keys(dataset.menu_instance_counts || {}).filter((value) => value !== "unknown").sort(),
  };
}

function DatasetStats({ dataset }) {
  if (!dataset) return <div className="stats">No dataset loaded.</div>;
  return (
    <div className="stats">
      <div>
        <strong>{dataset.case_count}</strong> active cases
      </div>
      <div>{dataset.gt_ready_case_count} GT-ready</div>
      <div>{dataset.excluded_count} excluded</div>
      <div>{dataset.video_ids?.length || 0} videos</div>
      <div className="pathText">{dataset.path}</div>
    </div>
  );
}

function CaseList({ cases, selectedCaseId, onSelect }) {
  return (
    <div className="caseList">
      {cases.map((item) => (
        <button
          type="button"
          className={`caseItem ${item.case_id === selectedCaseId ? "active" : ""}`}
          key={item.case_id}
          onClick={() => onSelect(item.case_id)}
        >
          <div className="caseItemTop">
            <span>{item.case_id}</span>
            <span className="pillGroup">
              <span className={`pill ${humanReviewClass(item.human_review_status)}`}>{item.human_review_status}</span>
              <span className={`pill ${confidenceClass(item.detail_confidence)}`}>{item.detail_confidence}</span>
            </span>
          </div>
          <div className="caseValue">{item.canonical_value || "UNKNOWN"}</div>
          <div className="caseMeta">
            <span>{item.video_id}</span>
            {item.menu_instance && <span>{item.menu_instance}</span>}
            {item.menu_label && <span>{item.menu_label}</span>}
            <span>{item.target_kind}</span>
            <span>{item.referent_type}</span>
          </div>
          <div className="caseHint">{item.content_hint}</div>
        </button>
      ))}
    </div>
  );
}

function CaseDetail({ detail, scenario, onSaved, onError, onAdvance }) {
  const caseData = detail.case;
  const videoRef = useRef(null);
  const [eventForm, setEventForm] = useState(() => eventToForm(caseData.event_gt));
  const [detailForm, setDetailForm] = useState(() => detailToForm(caseData.detail_gt));
  const [reviewForm, setReviewForm] = useState(() => reviewToForm(caseData));
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(Number(caseData.event_gt?.key_frame_time || 0));
  const [saving, setSaving] = useState("");

  useEffect(() => {
    setEventForm(eventToForm(caseData.event_gt));
    setDetailForm(detailToForm(caseData.detail_gt));
    setReviewForm(reviewToForm(caseData));
    setCurrentTime(Number(caseData.event_gt?.key_frame_time || 0));
  }, [caseData.case_id]);

  function seekTo(timeValue) {
    const video = videoRef.current;
    const time = Number(timeValue);
    if (!video || !Number.isFinite(time)) return;
    video.currentTime = Math.max(time, 0);
    setCurrentTime(Math.max(time, 0));
  }

  function setRangeField(field, value) {
    setEventForm((current) => ({ ...current, [field]: Number(value).toFixed(2) }));
  }

  function setPrimaryFromCurrent(edge) {
    const time = Number(currentTime || 0);
    if (edge === "start") {
      setEventForm((current) => ({
        ...current,
        primaryStart: time.toFixed(2),
        keyFrameTime: clampKeyFrame(current.keyFrameTime, time, Number(current.primaryEnd || time)),
      }));
    } else {
      setEventForm((current) => ({
        ...current,
        primaryEnd: time.toFixed(2),
        keyFrameTime: clampKeyFrame(current.keyFrameTime, Number(current.primaryStart || time), time),
      }));
    }
  }

  function setKeyFrameFromCurrent() {
    setEventForm((current) => ({ ...current, keyFrameTime: Number(currentTime || 0).toFixed(2) }));
  }

  function syncExpectedToPrimary() {
    setEventForm((current) => ({
      ...current,
      expectedStart: current.primaryStart,
      expectedEnd: current.primaryEnd,
    }));
  }

  function resetTimelineToGt() {
    setEventForm((current) => ({
      ...current,
      ...eventToForm(caseData.event_gt),
      reviewNote: current.reviewNote,
    }));
    seekTo(caseData.event_gt?.key_frame_time || 0);
  }

  function buildEventPayload() {
    return {
      primary_content_range: parseRange(eventForm.primaryStart, eventForm.primaryEnd),
      expected_time_range: parseRange(eventForm.expectedStart, eventForm.expectedEnd),
      allowed_transition_range: eventForm.allowedStart || eventForm.allowedEnd
        ? parseRange(eventForm.allowedStart, eventForm.allowedEnd)
        : null,
      key_frame_time: Number(eventForm.keyFrameTime),
      expected_region: {
        description: eventForm.regionDescription,
        coarse_region: eventForm.regionCoarse,
        notes: eventForm.regionNotes,
      },
      confidence: eventForm.confidence,
      evidence: eventForm.evidence,
      review_note: eventForm.reviewNote,
    };
  }

  function buildDetailPayload() {
    return {
      target_kind: detailForm.targetKind,
      canonical_value: detailForm.canonicalValue,
      acceptable_aliases: fromLines(detailForm.aliases),
      negative_neighbors: fromLines(detailForm.negativeNeighbors),
      confidence: detailForm.confidence,
      evidence: detailForm.evidence,
      review_note: detailForm.reviewNote,
    };
  }

  async function saveEvent() {
    setSaving("event");
    onError("");
    try {
      await postJson(
        `/api/datasets/${encodeURIComponent(scenario)}/cases/${encodeURIComponent(caseData.case_id)}/event-gt`,
        buildEventPayload(),
      );
      onSaved("Event GT saved");
    } catch (err) {
      onError(err.message);
    } finally {
      setSaving("");
    }
  }

  async function saveDetail() {
    setSaving("detail");
    onError("");
    try {
      await postJson(
        `/api/datasets/${encodeURIComponent(scenario)}/cases/${encodeURIComponent(caseData.case_id)}/detail-gt`,
        buildDetailPayload(),
      );
      onSaved("Detail GT saved");
    } catch (err) {
      onError(err.message);
    } finally {
      setSaving("");
    }
  }

  async function saveReview() {
    setSaving("review");
    onError("");
    try {
      await postJson(
        `/api/datasets/${encodeURIComponent(scenario)}/cases/${encodeURIComponent(caseData.case_id)}/review`,
        {
          review_note: reviewForm.reviewNote,
          gt_status: reviewForm.gtStatus,
          human_review_status: reviewForm.humanReviewStatus,
          human_reviewer: reviewForm.humanReviewer,
        },
      );
      onSaved("Human review status saved");
    } catch (err) {
      onError(err.message);
    } finally {
      setSaving("");
    }
  }

  async function markHumanReview(status) {
    setSaving(status);
    onError("");
    try {
      await postJson(
        `/api/datasets/${encodeURIComponent(scenario)}/cases/${encodeURIComponent(caseData.case_id)}/event-gt`,
        buildEventPayload(),
      );
      await postJson(
        `/api/datasets/${encodeURIComponent(scenario)}/cases/${encodeURIComponent(caseData.case_id)}/detail-gt`,
        buildDetailPayload(),
      );
      await postJson(
        `/api/datasets/${encodeURIComponent(scenario)}/cases/${encodeURIComponent(caseData.case_id)}/review`,
        {
          review_note: status === "verified" ? "Marked verified from quick review button." : "Marked needs_fix from quick review button.",
          gt_status: reviewForm.gtStatus,
          human_review_status: status,
          human_reviewer: reviewForm.humanReviewer,
        },
      );
      await onSaved(status === "verified" ? "Marked as verified" : "Marked as needs_fix");
      if (status === "verified") onAdvance();
    } catch (err) {
      onError(err.message);
    } finally {
      setSaving("");
    }
  }

  const primary = caseData.event_gt?.primary_content_range || [];
  const keyFrameTime = caseData.event_gt?.key_frame_time;
  const previewFrameUrl = detail.video?.path
    ? `/api/frame/${encodeURIComponent(detail.video.path)}?t=${encodeURIComponent(eventForm.keyFrameTime || keyFrameTime || 0)}`
    : detail.frame?.url;
  const visualQuery = caseData.visual_query_v1 || {};
  const referent = visualQuery.referent || {};
  const target = visualQuery.target || {};
  const scope = visualQuery.scope || {};

  return (
    <div className="detailStack">
      <header className="caseHeader">
        <div>
          <h2>{caseData.case_id}</h2>
          <p>
            {caseData.video_id} · {caseData.problem_type}
          </p>
        </div>
        <div className="reviewActions">
          <button className="verifyButton" onClick={() => markHumanReview("verified")} disabled={saving === "verified"}>
            Mark verified
          </button>
          <button className="needsFixButton" onClick={() => markHumanReview("needs_fix")} disabled={saving === "needs_fix"}>
            Needs fix
          </button>
          <span className={`pill ${humanReviewClass(caseData.human_review_status || "unreviewed")}`}>
            {caseData.human_review_status || "unreviewed"}
          </span>
        </div>
      </header>

      <section className="reviewWorkspace">
        <div className="videoCard">
          <video
            ref={videoRef}
            src={detail.video.url}
            controls
            preload="metadata"
            onLoadedMetadata={(event) => setDuration(event.currentTarget.duration || 0)}
            onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime || 0)}
          />
          <div className="timeWorkbench">
            <div className="timeReadout">
              <strong>{Number(currentTime || 0).toFixed(2)}s</strong>
              <span>Duration {duration ? duration.toFixed(2) : "--"}s</span>
              <span>Primary {formatRange([eventForm.primaryStart, eventForm.primaryEnd])}</span>
            </div>
            <EditableTimeline
              duration={duration}
              currentTime={currentTime}
              primaryStart={eventForm.primaryStart}
              primaryEnd={eventForm.primaryEnd}
              keyFrame={eventForm.keyFrameTime}
              onSeek={seekTo}
              onChange={(field, value) => setRangeField(field, value)}
            />
            <div className="timelineActions">
              <button onClick={() => seekTo(primary[0])}>Go primary</button>
              <button onClick={() => seekTo(eventForm.keyFrameTime || keyFrameTime)}>Go key</button>
              <button onClick={() => seekTo((videoRef.current?.currentTime || 0) - 0.5)}>-0.5s</button>
              <button onClick={() => seekTo((videoRef.current?.currentTime || 0) + 0.5)}>+0.5s</button>
              <button onClick={() => setPrimaryFromCurrent("start")}>Set start</button>
              <button onClick={setKeyFrameFromCurrent}>Set key</button>
              <button onClick={() => setPrimaryFromCurrent("end")}>Set end</button>
              <button onClick={syncExpectedToPrimary}>Sync expected</button>
              <button onClick={resetTimelineToGt}>Reset to GT</button>
            </div>
          </div>
        </div>
        <div className="sideStack">
          <div className="frameCard">
            {previewFrameUrl ? <img src={previewFrameUrl} alt="Key frame" /> : <div>No key frame</div>}
            <p>{eventForm.regionDescription}</p>
          </div>
          <InfoBlock
            title="Visual Query"
            rows={[
              ["target", `${target.kind || ""} / ${target.selection_unit || ""}`],
              ["referent", `${referent.type || ""} / ${referent.action || ""} / ${referent.ordinal || ""}`],
              ["menu", [scope.menu_instance, scope.menu_label].filter(Boolean).join(" / ")],
              ["hint", referent.appearance?.content_hint],
              ["surface", visualQuery.surface],
            ]}
          />
        </div>
      </section>

      <section className="summaryGrid">
        <InfoBlock
          title="Detail GT"
          rows={[
            ["value", caseData.detail_gt?.canonical_value],
            ["kind", caseData.detail_gt?.target_kind],
            ["confidence", caseData.detail_gt?.confidence],
            ["aliases", toLines(caseData.detail_gt?.acceptable_aliases)],
          ]}
        />
        <InfoBlock
          title="Human Review"
          rows={[
            ["status", caseData.human_review_status || "unreviewed"],
            ["reviewed_at", caseData.human_reviewed_at],
            ["reviewer", caseData.human_reviewer],
            ["gt_status", caseData.gt_status],
          ]}
        />
      </section>

      <section className="editorGrid">
        <EditorCard title="Event GT" onSave={saveEvent} saving={saving === "event"}>
          <div className="threeCols">
            <Field label="Primary start" value={eventForm.primaryStart} onChange={(v) => setEventForm({ ...eventForm, primaryStart: v })} />
            <Field label="Primary end" value={eventForm.primaryEnd} onChange={(v) => setEventForm({ ...eventForm, primaryEnd: v })} />
            <Field label="Key frame" value={eventForm.keyFrameTime} onChange={(v) => setEventForm({ ...eventForm, keyFrameTime: v })} />
          </div>
          <div className="twoCols">
            <Field label="Expected start" value={eventForm.expectedStart} onChange={(v) => setEventForm({ ...eventForm, expectedStart: v })} />
            <Field label="Expected end" value={eventForm.expectedEnd} onChange={(v) => setEventForm({ ...eventForm, expectedEnd: v })} />
          </div>
          <div className="twoCols">
            <Field label="Allowed start" value={eventForm.allowedStart} onChange={(v) => setEventForm({ ...eventForm, allowedStart: v })} />
            <Field label="Allowed end" value={eventForm.allowedEnd} onChange={(v) => setEventForm({ ...eventForm, allowedEnd: v })} />
          </div>
          <Field label="Region description" value={eventForm.regionDescription} onChange={(v) => setEventForm({ ...eventForm, regionDescription: v })} />
          <div className="twoCols">
            <Field label="Coarse region" value={eventForm.regionCoarse} onChange={(v) => setEventForm({ ...eventForm, regionCoarse: v })} />
            <SelectField
              label="Confidence"
              value={eventForm.confidence}
              values={["low", "medium", "high"]}
              onChange={(v) => setEventForm({ ...eventForm, confidence: v })}
            />
          </div>
          <TextArea label="Evidence" value={eventForm.evidence} onChange={(v) => setEventForm({ ...eventForm, evidence: v })} />
          <TextArea label="Review note" value={eventForm.reviewNote} onChange={(v) => setEventForm({ ...eventForm, reviewNote: v })} />
        </EditorCard>

        <EditorCard title="Detail GT" onSave={saveDetail} saving={saving === "detail"}>
          <div className="twoCols">
            <Field label="Target kind" value={detailForm.targetKind} onChange={(v) => setDetailForm({ ...detailForm, targetKind: v })} />
            <SelectField
              label="Confidence"
              value={detailForm.confidence}
              values={["low", "medium", "high"]}
              onChange={(v) => setDetailForm({ ...detailForm, confidence: v })}
            />
          </div>
          <Field label="Canonical value" value={detailForm.canonicalValue} onChange={(v) => setDetailForm({ ...detailForm, canonicalValue: v })} />
          <TextArea label="Acceptable aliases" value={detailForm.aliases} onChange={(v) => setDetailForm({ ...detailForm, aliases: v })} />
          <TextArea label="Negative neighbors" value={detailForm.negativeNeighbors} onChange={(v) => setDetailForm({ ...detailForm, negativeNeighbors: v })} />
          <TextArea label="Evidence" value={detailForm.evidence} onChange={(v) => setDetailForm({ ...detailForm, evidence: v })} />
          <TextArea label="Review note" value={detailForm.reviewNote} onChange={(v) => setDetailForm({ ...detailForm, reviewNote: v })} />
        </EditorCard>
      </section>

      <section className="sourceGrid">
        <EditorCard title="Case Review" onSave={saveReview} saving={saving === "review"}>
          <div className="twoCols">
            <SelectField
              label="Human review status"
              value={reviewForm.humanReviewStatus}
              values={["unreviewed", "verified", "needs_fix"]}
              onChange={(v) => setReviewForm({ ...reviewForm, humanReviewStatus: v })}
            />
            <Field
              label="Reviewer"
              value={reviewForm.humanReviewer}
              onChange={(v) => setReviewForm({ ...reviewForm, humanReviewer: v })}
            />
          </div>
          <Field
            label="GT status"
            value={reviewForm.gtStatus}
            onChange={(v) => setReviewForm({ ...reviewForm, gtStatus: v })}
          />
          <TextArea
            label="Add review note"
            value={reviewForm.reviewNote}
            onChange={(v) => setReviewForm({ ...reviewForm, reviewNote: v })}
          />
        </EditorCard>
        <InfoBlock title="Source Instructions" rows={(caseData.source_instruction_snippets || []).map((item, index) => [`#${index + 1}`, item])} />
      </section>

      <details className="jsonDetails">
        <summary>Raw JSON</summary>
        <pre>{JSON.stringify(caseData, null, 2)}</pre>
      </details>
    </div>
  );
}

function eventToForm(eventGt = {}) {
  const primary = eventGt.primary_content_range || [];
  const expected = eventGt.expected_time_range || [];
  const allowed = eventGt.allowed_transition_range || [];
  const region = eventGt.expected_region || {};
  return {
    primaryStart: primary[0] ?? "",
    primaryEnd: primary[1] ?? "",
    expectedStart: expected[0] ?? "",
    expectedEnd: expected[1] ?? "",
    allowedStart: allowed[0] ?? "",
    allowedEnd: allowed[1] ?? "",
    keyFrameTime: eventGt.key_frame_time ?? "",
    regionDescription: region.description || "",
    regionCoarse: region.coarse_region || "",
    regionNotes: region.notes || "",
    confidence: eventGt.confidence || "medium",
    evidence: eventGt.evidence || "",
    reviewNote: "",
  };
}

function detailToForm(detailGt = {}) {
  return {
    targetKind: detailGt.target_kind || "",
    canonicalValue: detailGt.canonical_value || "",
    aliases: toLines(detailGt.acceptable_aliases),
    negativeNeighbors: toLines(detailGt.negative_neighbors),
    confidence: detailGt.confidence || "medium",
    evidence: detailGt.evidence || "",
    reviewNote: "",
  };
}

function clampKeyFrame(value, start, end) {
  const key = Number(value);
  const lo = Math.min(Number(start), Number(end));
  const hi = Math.max(Number(start), Number(end));
  if (!Number.isFinite(key)) return Number(start).toFixed(2);
  return Math.min(Math.max(key, lo), hi).toFixed(2);
}

function EditableTimeline({ duration, currentTime, primaryStart, primaryEnd, keyFrame, onSeek, onChange }) {
  const trackRef = useRef(null);
  const [dragging, setDragging] = useState(null);
  const total = Math.max(Number(duration || 0), Number(primaryEnd || 0), Number(keyFrame || 0), 1);
  const startValue = Number(primaryStart || 0);
  const endValue = Number(primaryEnd || 0);
  const keyValue = Number(keyFrame || 0);
  const currentValue = Number(currentTime || 0);
  const start = percent(startValue, total);
  const end = Math.max(start, percent(endValue, total));
  const key = percent(keyValue, total);
  const current = percent(currentValue, total);

  useEffect(() => {
    if (!dragging) return undefined;

    function onMove(event) {
      updateFromPointer(dragging, event.clientX);
    }

    function onUp() {
      setDragging(null);
    }

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [dragging, primaryStart, primaryEnd, keyFrame, duration]);

  function timeFromClientX(clientX) {
    const rect = trackRef.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0) return 0;
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    return ratio * total;
  }

  function updateFromPointer(kind, clientX) {
    applyTime(kind, timeFromClientX(clientX));
  }

  function applyTime(kind, rawTime) {
    let time = Math.max(0, Math.min(total, rawTime));
    const startTime = Number(primaryStart || 0);
    const endTime = Number(primaryEnd || 0);
    const width = Math.max(0, endTime - startTime);
    if (kind === "primaryStart") {
      const nextStart = Math.max(0, Math.min(total, time));
      let nextEnd = endTime;
      if (nextEnd < nextStart) nextEnd = nextStart;
      if (nextEnd > total) nextEnd = total;
      onChange("primaryStart", nextStart);
      onChange("primaryEnd", nextEnd);
      if (Number(keyFrame || 0) < nextStart || Number(keyFrame || 0) > nextEnd) {
        onChange("keyFrameTime", Math.min(Math.max(Number(keyFrame || nextStart), nextStart), nextEnd));
      }
      onSeek(nextStart);
      return;
    }
    if (kind === "primaryEnd") {
      const nextEnd = Math.max(0, Math.min(total, time));
      let nextStart = startTime;
      if (nextStart > nextEnd) nextStart = nextEnd;
      if (nextStart < 0) nextStart = 0;
      onChange("primaryStart", nextStart);
      onChange("primaryEnd", nextEnd);
      if (Number(keyFrame || 0) < nextStart || Number(keyFrame || 0) > nextEnd) {
        onChange("keyFrameTime", Math.min(Math.max(Number(keyFrame || nextEnd), nextStart), nextEnd));
      }
      onSeek(nextEnd);
      return;
    }
    if (kind === "primaryRange") {
      const half = width / 2;
      let nextStart = Math.max(0, Math.min(total - width, time - half));
      let nextEnd = Math.min(total, nextStart + width);
      onChange("primaryStart", nextStart);
      onChange("primaryEnd", nextEnd);
      onChange("keyFrameTime", Math.min(Math.max(Number(keyFrame || time), nextStart), nextEnd));
      onSeek(time);
      return;
    }
    if (kind === "keyFrameTime") {
      onChange("keyFrameTime", time);
      onSeek(time);
      return;
    }
    onSeek(time);
  }

  return (
    <div
      ref={trackRef}
      className="timelineEditor"
      onPointerDown={(event) => {
        if (event.target !== event.currentTarget) return;
        updateFromPointer("seek", event.clientX);
      }}
    >
      <div
        className="rangeFill"
        style={{ left: `${start}%`, width: `${Math.max(end - start, 0.5)}%` }}
        onPointerDown={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setDragging("primaryRange");
          updateFromPointer("primaryRange", event.clientX);
        }}
        title="Drag primary range"
      />
      <div className="currentMarker" style={{ left: `${current}%` }} />
      <div className="keyMarker" style={{ left: `${key}%` }} />
      <TimelineHandle
        kind="primaryStart"
        label="start"
        left={start}
        onDragStart={(kind, event) => {
          event.preventDefault();
          event.stopPropagation();
          setDragging(kind);
          updateFromPointer(kind, event.clientX);
        }}
      />
      <TimelineHandle
        kind="keyFrameTime"
        label="key"
        left={key}
        onDragStart={(kind, event) => {
          event.preventDefault();
          event.stopPropagation();
          setDragging(kind);
          updateFromPointer(kind, event.clientX);
        }}
      />
      <TimelineHandle
        kind="primaryEnd"
        label="end"
        left={end}
        onDragStart={(kind, event) => {
          event.preventDefault();
          event.stopPropagation();
          setDragging(kind);
          updateFromPointer(kind, event.clientX);
        }}
      />
    </div>
  );
}

function TimelineHandle({ kind, label, left, onDragStart }) {
  return (
    <button
      type="button"
      className={`timelineHandle ${kind}`}
      style={{ left: `${left}%` }}
      onPointerDown={(event) => onDragStart(kind, event)}
      title={`Drag ${label}`}
    >
      {label}
    </button>
  );
}

function percent(value, total) {
  return Math.max(0, Math.min(100, (Number(value || 0) / Math.max(total, 1)) * 100));
}

function reviewToForm(caseData = {}) {
  return {
    humanReviewStatus: caseData.human_review_status || "unreviewed",
    humanReviewer: caseData.human_reviewer || "manual_review",
    gtStatus: caseData.gt_status || "gt_video_annotated",
    reviewNote: "",
  };
}

function InfoBlock({ title, rows }) {
  return (
    <section className="card">
      <h3>{title}</h3>
      <div className="kv">
        {rows.map(([key, value]) => (
          <React.Fragment key={`${key}-${String(value).slice(0, 20)}`}>
            <dt>{key}</dt>
            <dd>{Array.isArray(value) ? value.join(", ") : value || ""}</dd>
          </React.Fragment>
        ))}
      </div>
    </section>
  );
}

function EditorCard({ title, children, onSave, saving }) {
  return (
    <section className="card">
      <div className="cardHeader">
        <h3>{title}</h3>
        <button onClick={onSave} disabled={saving}>
          {saving ? "Saving..." : "Save"}
        </button>
      </div>
      <div className="formStack">{children}</div>
    </section>
  );
}

function Field({ label, value, onChange }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function SelectField({ label, value, values, onChange }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {values.map((item) => (
          <option key={item} value={item}>
            {item}
          </option>
        ))}
      </select>
    </label>
  );
}

function TextArea({ label, value, onChange }) {
  return (
    <label className="field">
      <span>{label}</span>
      <textarea value={value} onChange={(event) => onChange(event.target.value)} rows={4} />
    </label>
  );
}

createRoot(document.getElementById("root")).render(<App />);
