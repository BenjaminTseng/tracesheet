import { h, render } from 'preact';
import { useState, useEffect, useRef, useCallback, useMemo } from 'preact/hooks';
import htm from 'htm';

const html = htm.bind(h);

/**
 * Consistent crisp 1.6px-stroke SVG icon primitives (no raw Unicode/emoji glyphs).
 */
function Icon({ name, size = 14 }) {
  const props = {
    width: size,
    height: size,
    viewBox: '0 0 16 16',
    fill: 'none',
    stroke: 'currentColor',
    'stroke-width': '1.5',
    'stroke-linecap': 'square',
    'stroke-linejoin': 'miter',
    'aria-hidden': 'true',
    style: 'flex-shrink: 0;',
  };
  switch (name) {
    case 'comment':
      return html`<svg ...${props}><path d="M2.5 3h11v7.5h-6L4.5 13v-2.5h-2V3z" /></svg>`;
    case 'source':
      return html`<svg ...${props}><path d="M3 2h7l3 3v9H3V2z" /><path d="M10 2v3h3" /><path d="M5.5 8.5h5M5.5 11h3.5" /></svg>`;
    case 'link':
      return html`<svg ...${props}><path d="M3 8h10M9.5 4.5L13 8l-3.5 3.5" /></svg>`;
    case 'close':
      return html`<svg ...${props}><path d="M4 4l8 8M12 4l-8 8" /></svg>`;
    case 'plus':
      return html`<svg ...${props}><path d="M8 3v10M3 8h10" /></svg>`;
    case 'more':
      return html`<svg ...${props}><circle cx="3.5" cy="8" r="1" fill="currentColor" stroke="none" /><circle cx="8" cy="8" r="1" fill="currentColor" stroke="none" /><circle cx="12.5" cy="8" r="1" fill="currentColor" stroke="none" /></svg>`;
    case 'check':
      return html`<svg ...${props}><path d="M3.5 8.5L6.5 11.5L12.5 4.5" /></svg>`;
    case 'chevronRight':
      return html`<svg ...${props}><path d="M6 3.5L10.5 8L6 12.5" /></svg>`;
    case 'chevronDown':
      return html`<svg ...${props}><path d="M3.5 6L8 10.5L12.5 6" /></svg>`;
    case 'trash':
      return html`<svg ...${props}><path d="M2.5 4.5h11M6 4.5V3h4v1.5M4.5 4.5l.7 8.5h5.6l.7-8.5" /></svg>`;
    case 'folder':
      return html`<svg ...${props}><path d="M2.5 3.5h4l1.5 1.5h5.5v7.5h-11V3.5z" /></svg>`;
    case 'play':
      return html`<svg ...${props}><path d="M4.5 3.5L12.5 8l-8 4.5V3.5z" /></svg>`;
    default:
      return null;
  }
}

function formatAuditStatus(status) {
  const map = {
    verified: 'Verified',
    extrapolation: 'Extrapolation',
    assumption: 'Assumption',
    disputed: 'Disputed',
    unverified: 'Unverified',
  };
  return map[status] || status;
}

function isCaveatStatus(status) {
  return (
    status === 'extrapolation' ||
    status === 'assumption' ||
    status === 'disputed' ||
    status === 'unverified'
  );
}

function formatNodeRole(type) {
  const map = {
    claim: 'Claim',
    evidence: 'Direct Evidence',
    reasoning: 'Logical Inference',
    calculation: 'Calculation',
    assumption: 'Baseline Assumption',
    authority: 'Controlling Rule',
  };
  return map[type] || type;
}

function getLinkRoleMeta(targetNode) {
  const status = targetNode?.audit?.status || 'verified';
  if (isCaveatStatus(status)) {
    return { label: 'Caveat', toneClass: 'is-caveat', stroke: '#B45309' };
  }
  switch (targetNode?.type) {
    case 'calculation':
      return { label: 'Math', toneClass: 'is-math', stroke: '#14532D' };
    case 'authority':
      return { label: 'Rule', toneClass: 'is-rule', stroke: '#B84A27' };
    case 'reasoning':
      return { label: 'Logic', toneClass: '', stroke: '#14284B' };
    case 'assumption':
      return { label: 'Caveat', toneClass: 'is-caveat', stroke: '#B45309' };
    default:
      return { label: 'Fact', toneClass: '', stroke: '#14284B' };
  }
}

function formatScopeTag(comment, nodesMap) {
  if (comment.scope === 'document' || comment.section_id === '__document__') {
    return { label: 'Overall Memo', cls: 'is-document' };
  }
  if (comment.scope === 'section' || comment.node_id === '__section__') {
    return { label: 'Section', cls: '' };
  }
  if (comment.scope === 'link') {
    return { label: 'Logical Link', cls: 'is-link' };
  }
  const node = nodesMap?.[comment.node_id];
  return { label: node ? formatNodeRole(node.type) : 'Node', cls: '' };
}

function formatReliabilityTier(tier) {
  switch (tier) {
    case 'primary_record':
      return { label: 'Primary Record', cls: 'is-primary' };
    case 'secondary_analysis':
      return { label: 'Secondary Analysis', cls: 'is-secondary' };
    case 'self_reported':
      return { label: 'Self-Reported', cls: 'is-self-reported' };
    default:
      return null;
  }
}

function formatProvenanceParts(locator) {
  if (!locator) return { label: '', coord: '' };
  switch (locator.source_type) {
    case 'pdf':
      return {
        label: locator.file_name || 'Filing.pdf',
        coord: `p. ${locator.page || 1}`,
      };
    case 'spreadsheet':
      return {
        label: `${locator.file_name || 'Model.xlsx'} (${locator.sheet || 'Sheet1'})`,
        coord: locator.cell_range || 'A1',
      };
    case 'api':
      return {
        label: 'API Telemetry',
        coord: `${locator.method || 'GET'} ${locator.endpoint || '/api'}`,
      };
    case 'internal_db':
      return {
        label: 'SQL Verification',
        coord: `${locator.database || 'db'}.${locator.table || 'table'} [${locator.row_id || 'row'}]`,
      };
    case 'web':
      return {
        label: 'Archival Snapshot',
        coord: locator.locator_key || '',
      };
    case 'markdown':
      return {
        label: locator.file_name || 'Document.md',
        coord: locator.locator_key || '',
      };
    case 'docx':
      return {
        label: locator.file_name || 'Document.docx',
        coord: locator.locator_key || '',
      };
    default:
      return { label: locator.source_type || '', coord: '' };
  }
}

function formatApiError(detailOrErr) {
  if (!detailOrErr) return 'An unexpected error occurred.';
  if (typeof detailOrErr === 'string') return detailOrErr;
  const detail = detailOrErr.detail !== undefined ? detailOrErr.detail : detailOrErr;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === 'string') return item;
        const loc = Array.isArray(item?.loc) ? item.loc.slice(1).join('.') : '';
        return loc ? `${loc}: ${item.msg || 'invalid value'}` : item?.msg || JSON.stringify(item);
      })
      .join('; ');
  }
  return detailOrErr.message || JSON.stringify(detail);
}

function resolveSourceFileUrl(node, bundle, mattersList, canonicalAuths) {
  if (!node) return null;
  const loc = node.locator;

  if (node.type === 'authority') {
    const matchedAuth = (canonicalAuths || []).find(
      (a) =>
        (loc?.locator_key && a.auth_id === loc.locator_key) ||
        (node.title && a.title === node.title)
    );
    const docId = matchedAuth?.doc_id || loc?.file_name || '';
    if (docId && docId.includes('/')) {
      const parts = docId.split('/');
      const domain = parts[0];
      const fileName = parts.slice(1).join('/');
      return {
        url: `/api/canonical/files/${encodeURIComponent(domain)}/${encodeURIComponent(fileName)}/raw`,
        existsOnDisk: true,
        isSampleFixture: false,
        label: 'Open Controlling Rule ↗',
        fileName,
      };
    }
  }

  const fileName = loc?.file_name;
  if (!fileName) return null;

  const matterId = bundle?.matter_id || null;
  const metaFiles = Array.isArray(bundle?.artifact?.metadata?.available_raw_files)
    ? bundle.artifact.metadata.available_raw_files
    : null;
  const matterObj = (mattersList || []).find((m) => m.matter_id === matterId);
  const availableFiles = metaFiles !== null ? metaFiles : matterObj?.raw_files || [];
  const existsOnDisk = Boolean(matterId && availableFiles.includes(fileName));

  if (existsOnDisk) {
    const baseUrl = `/api/matters/${encodeURIComponent(matterId)}/files/${encodeURIComponent(fileName)}/raw`;
    const isPdf = loc.source_type === 'pdf' || fileName.toLowerCase().endsWith('.pdf');
    const url = isPdf && loc.page ? `${baseUrl}#page=${loc.page}` : baseUrl;
    const label =
      isPdf && loc.page
        ? `Open Original PDF (p. ${loc.page}) ↗`
        : 'Open / Download Source File ↗';
    return {
      url,
      existsOnDisk: true,
      isSampleFixture: false,
      label,
      fileName,
    };
  }

  return {
    url: null,
    existsOnDisk: false,
    isSampleFixture: true,
    label: 'Sample Fixture (No Raw File on Disk)',
    fileName,
  };
}

const ACTIVE_RUN_STORAGE_KEY = 'jd_screen_active_run_id';

function saveActiveRunId(runId) {
  try {
    if (runId) {
      window.localStorage?.setItem(ACTIVE_RUN_STORAGE_KEY, runId);
    } else {
      window.localStorage?.removeItem(ACTIVE_RUN_STORAGE_KEY);
    }
  } catch {
    // Ignore storage access errors in restricted frames
  }
}

function loadActiveRunId() {
  try {
    return window.localStorage?.getItem(ACTIVE_RUN_STORAGE_KEY) || null;
  } catch {
    return null;
  }
}

function formatBytes(bytes) {
  if (bytes == null || Number.isNaN(Number(bytes))) return '—';
  const n = Number(bytes);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function formatRunStatusLabel(status) {
  const map = {
    running: 'Running',
    awaiting_stage1_approval: 'Paused: Stage 1 Outline',
    awaiting_stage2_approval: 'Paused: Stage 2 Facts',
    completed: 'Completed',
    failed: 'Failed',
  };
  return map[status] || status || 'Unknown';
}

/**
 * Consumes a `text/event-stream` response body frame-by-frame and invokes `onEvent`.
 */
async function readSSEStream(res, onEvent) {
  if (!res.ok || !res.body) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(
      typeof errData.detail === 'string'
        ? errData.detail
        : JSON.stringify(errData.detail || `HTTP ${res.status}`)
    );
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let lastPayload = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';
    for (const chunk of parts) {
      const dataLine = chunk.split('\n').find((ln) => ln.startsWith('data: '));
      if (!dataLine) continue;
      const evt = JSON.parse(dataLine.slice(6));
      if (evt.event === 'error') {
        throw new Error(evt.detail || 'Streaming request failed');
      }
      lastPayload = evt;
      onEvent?.(evt);
    }
  }
  return lastPayload;
}

/**
 * Executes an SSE-streaming pipeline request and returns `{ bundle, run }`.
 */
async function _consumePipelineSSE(res, { onProgress, onRunStarted, onCheckpoint }) {
  let resultBundle = null;
  let resultRun = null;

  await readSSEStream(res, (evt) => {
    if (evt.event === 'run_started' && evt.run) {
      resultRun = evt.run;
      saveActiveRunId(evt.run.run_id);
      onRunStarted?.(evt.run);
    } else if (evt.event === 'progress') {
      onProgress?.({ stage: evt.stage, message: evt.message });
    } else if (evt.event === 'checkpoint' && evt.run) {
      resultRun = evt.run;
      saveActiveRunId(evt.run.run_id);
      onCheckpoint?.(evt.run);
    } else if (evt.event === 'bundle') {
      resultBundle = evt.bundle;
      if (evt.run) {
        resultRun = evt.run;
      }
      saveActiveRunId(null);
    } else if (evt.event === 'run_state' && evt.run) {
      resultRun = evt.run;
    }
  });

  return { bundle: resultBundle, run: resultRun };
}

/**
 * Streams the 4-stage SSE pipeline from `/api/matters/:matter_id/ask/stream`.
 */
async function streamAskPipeline({
  matterId,
  question,
  bundleId,
  checkpointMode = false,
  canonicalDomains = null,
  blueprintId = null,
  blueprintMode = 'none',
  onProgress,
  onRunStarted,
  onCheckpoint,
}) {
  const res = await fetch(`/api/matters/${matterId}/ask/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: question.trim(),
      bundle_id: bundleId || null,
      smooth_transitions: true,
      checkpoint_mode: Boolean(checkpointMode),
      canonical_domains: canonicalDomains,
      blueprint_id: blueprintId || null,
      blueprint_mode: blueprintId ? blueprintMode || 'guided' : 'none',
    }),
  });
  return _consumePipelineSSE(res, { onProgress, onRunStarted, onCheckpoint });
}

/**
 * Streams resumption of a persisted/checkpointed run via `/api/runs/:run_id/resume/stream`.
 */
async function resumeRunStream({
  runId,
  outlinePlan = null,
  reharvestSectionIds = null,
  checkpointMode = null,
  onProgress,
  onRunStarted,
  onCheckpoint,
}) {
  const payload = {};
  if (outlinePlan !== null) payload.outline_plan = outlinePlan;
  if (reharvestSectionIds !== null) payload.reharvest_section_ids = reharvestSectionIds;
  if (checkpointMode !== null) payload.checkpoint_mode = checkpointMode;

  const res = await fetch(`/api/runs/${runId}/resume/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return _consumePipelineSSE(res, { onProgress, onRunStarted, onCheckpoint });
}

/**
 * Replays recorded events and subscribes to live updates on `GET /api/runs/:run_id/stream`.
 */
async function connectRunStream({ runId, onProgress, onRunStarted, onCheckpoint }) {
  const res = await fetch(`/api/runs/${runId}/stream`);
  return _consumePipelineSSE(res, { onProgress, onRunStarted, onCheckpoint });
}

/**
 * Streams an ingestion/upload SSE endpoint until its terminal `complete` payload.
 */
async function streamUploadOrIngest(url, fetchInit, onProgress) {
  const res = await fetch(url, fetchInit);
  let completePayload = null;
  await readSSEStream(res, (evt) => {
    if (evt.event === 'progress') {
      onProgress?.({ stage: evt.stage, message: evt.message });
    } else if (evt.event === 'complete') {
      completePayload = evt;
    }
  });
  return completePayload;
}

/**
 * Parses `<ref id='node_id'>clause</ref>` tags into interactive inline text highlights.
 */
function renderAnnotatedText({
  text,
  nodesMap,
  activeNodeIds,
  tensionClaimIds,
  auditFilter,
  onHoverRef,
  onLeaveRef,
  onClickRef,
  level = 0,
}) {
  if (!text) return null;
  const regex = /<ref\s+id=['"]([^'"]+)['"]>(.*?)<\/ref>/gs;
  const parts = [];
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const targetId = match[1];
    const innerText = match[2];
    const targetNode = nodesMap[targetId];
    const status = targetNode?.audit?.status || 'verified';
    const isActive = activeNodeIds.has(targetId);
    const isTensionPeer = tensionClaimIds.has(targetId);
    const hasCaveat = isCaveatStatus(status) || isTensionPeer;

    const matchesFilter =
      auditFilter === 'all' ||
      (auditFilter === 'caveats' && hasCaveat) ||
      (auditFilter === 'tension' && isTensionPeer);

    const classNames = [
      'clause-highlight',
      isActive ? 'is-active' : '',
      hasCaveat ? 'is-caveat' : '',
      !matchesFilter ? 'is-dimmed' : '',
    ]
      .filter(Boolean)
      .join(' ');

    parts.push(html`
      <button
        type="button"
        key="${targetId}-${match.index}"
        class=${classNames}
        data-ref-node-id=${targetId}
        data-ref-level=${level}
        aria-pressed=${isActive}
        onMouseEnter=${(e) => onHoverRef(targetId, e.currentTarget, level)}
        onMouseLeave=${onLeaveRef}
        onFocus=${(e) => onHoverRef(targetId, e.currentTarget, level)}
        onBlur=${onLeaveRef}
        onClick=${(e) => {
          e.stopPropagation();
          onClickRef(targetId, level);
        }}
      >
        ${innerText}
      </button>
    `);

    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts;
}

/**
 * Slide-Over Source Inspector Drawer.
 */
function SourceInspectorDrawer({ node, sourceLink, onClose }) {
  const closeBtnRef = useRef(null);

  useEffect(() => {
    if (!node) return undefined;
    const prevFocus = document.activeElement;
    requestAnimationFrame(() => closeBtnRef.current?.focus());
    return () => {
      if (prevFocus && typeof prevFocus.focus === 'function') {
        prevFocus.focus();
      }
    };
  }, [node?.id]);

  if (!node) return null;
  const loc = node.locator || {};
  const audit = node.audit || {};
  const status = audit.status || 'verified';

  return html`
    <div
      class="inspector-backdrop"
      onClick=${(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside
        class="source-inspector-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="inspector-drawer-title"
      >
        <div class="drawer-header">
          <h2 id="inspector-drawer-title" class="card-heading" style="font-size: 18px;">
            ${node.title}
          </h2>
          <button
            ref=${closeBtnRef}
            type="button"
            class="btn btn-icon-only"
            aria-label="Close source inspector"
            onClick=${onClose}
          >
            <${Icon} name="close" />
          </button>
        </div>

        <div class="drawer-body">
          <div class="card-meta-row" style="border-bottom: 1px solid var(--color-border-subtle); padding-bottom: 8px; flex-wrap: wrap;">
            <span style="display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <span class="arch-stamp ${isCaveatStatus(status) ? 'is-caveat' : ''}">
                ${formatAuditStatus(status)}
                <span class="font-mono-data">${Math.round((audit.score || 1) * 100)}%</span>
              </span>
              <span class="control-label">
                ${formatNodeRole(node.type)}${loc.source_type ? ` · ${loc.source_type}` : ''}
              </span>
            </span>
            <span class="provenance-caption">
              Verified by ${audit.evaluator_type || 'deterministic'} check
            </span>
          </div>

          ${(loc.reliability_tier || loc.origin_description) && html`
            <div class="provenance-origin-row">
              ${formatReliabilityTier(loc.reliability_tier) && html`
                <span class="reliability-pill ${formatReliabilityTier(loc.reliability_tier).cls}">
                  ${formatReliabilityTier(loc.reliability_tier).label}
                </span>
              `}
              ${loc.origin_description && html`
                <span class="provenance-origin-text">${loc.origin_description}</span>
              `}
            </div>
          `}

          ${sourceLink && html`
            <div class="provenance-origin-row">
              ${sourceLink.existsOnDisk && sourceLink.url ? html`
                <a
                  href=${sourceLink.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  class="btn btn-compact btn-primary"
                  style="text-decoration: none;"
                >
                  <${Icon} name="source" size=${12} />
                  <span>${sourceLink.label}</span>
                </a>
              ` : html`
                <span class="sample-fixture-badge" title="Referenced in sample bundle; raw file is not stored on disk">
                  ${sourceLink.label}
                </span>
              `}
            </div>
          `}

          ${audit.evaluator_note && html`
            <p class="card-body-prose">
              <strong>Audit Record:</strong> ${audit.evaluator_note}
            </p>
          `}

          ${loc.source_type === 'pdf' && html`
            <div class="pdf-page-simulator">
              <div class="card-meta-row">
                <span class="control-label">${loc.file_name}</span>
                <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                  PAGE ${loc.page || 1}
                </span>
              </div>
              <p class="provenance-caption">
                Locator: ${loc.locator_key || 'Verified Excerpt'}
              </p>
              <div class="pdf-bbox-highlight">
                ${loc.bounding_box && html`
                  <div class="font-mono-data" style="font-size: 10.5px; color: var(--color-accent-primary); margin-bottom: 4px;">
                    BBOX [${loc.bounding_box.join(', ')}]
                  </div>
                `}
                “${node.quote}”
              </div>
              ${loc.payload_hash && html`
                <p class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                  ${loc.payload_hash}
                </p>
              `}
            </div>
          `}

          ${loc.source_type === 'spreadsheet' && html`
            <div style="display: flex; flex-direction: column; gap: 10px;">
              <div class="card-meta-row">
                <span class="control-label">Workbook: ${loc.file_name}</span>
                <span class="font-mono-data" style="font-size: 11.5px; color: var(--color-text-secondary);">
                  ${loc.sheet}!${loc.cell_range}
                </span>
              </div>
              ${node.formula && html`
                <div class="formula-box">
                  <strong>fx</strong> ${node.formula}
                </div>
              `}
              <table class="sheet-table">
                <caption class="visually-hidden">
                  Excerpt from worksheet ${loc.sheet} around cell ${loc.cell_range}
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Cell</th>
                    <th scope="col">Line Item</th>
                    <th scope="col">Reported Display</th>
                    <th scope="col" class="cell-numeric">Raw Value</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td class="font-mono-data">${loc.cell_range || 'Target'}</td>
                    <td>${node.title}</td>
                    <td class="sheet-cell-active">${node.quote}</td>
                    <td class="cell-numeric">${JSON.stringify(loc.raw_value)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          `}

          ${loc.source_type === 'api' && html`
            <div style="display: flex; flex-direction: column; gap: 10px;">
              <div class="formula-box">
                <strong>${loc.method || 'GET'}</strong> ${loc.endpoint}
              </div>
              <div class="card-meta-row">
                <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-secondary);">
                  ${loc.json_path}
                </span>
                ${loc.payload_hash && html`
                  <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                    ${loc.payload_hash}
                  </span>
                `}
              </div>
              <figure class="evidence-figure">
                <figcaption class="evidence-figcaption">
                  <span>Captured API Payload</span>
                </figcaption>
                <pre tabindex="0" class="formula-box"><code class="language-json">${JSON.stringify(
                  {
                    request_params: loc.query_params || {},
                    extracted_path: loc.json_path,
                    verified_raw_value: loc.raw_value,
                    formatted_quote: node.quote,
                  },
                  null,
                  2
                )}</code></pre>
              </figure>
            </div>
          `}

          ${loc.source_type === 'internal_db' && html`
            <div style="display: flex; flex-direction: column; gap: 10px;">
              <div class="card-meta-row">
                <span class="font-mono-data" style="font-size: 11.5px; color: var(--color-text-secondary);">
                  ${loc.database}.${loc.table}
                </span>
                <span class="font-mono-data" style="font-size: 11.5px; color: var(--color-text-muted);">
                  ROW ${loc.row_id}
                </span>
              </div>
              <figure class="evidence-figure">
                <figcaption class="evidence-figcaption">Read-Only Verification Query</figcaption>
                <pre tabindex="0" class="formula-box"><code class="language-sql">${loc.query}</code></pre>
              </figure>
              <div class="evidence-figure">
                <blockquote class="evidence-blockquote">“${node.quote}”</blockquote>
              </div>
            </div>
          `}

          ${loc.source_type === 'web' && html`
            <div style="display: flex; flex-direction: column; gap: 10px;">
              <div class="card-meta-row">
                <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                  ${loc.snapshot_timestamp}
                </span>
                <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-secondary);">
                  ${loc.locator_key}
                </span>
              </div>
              <figure class="evidence-figure">
                <blockquote class="evidence-blockquote" cite=${loc.url}>
                  “${node.quote}”
                </blockquote>
                ${loc.url && html`
                  <figcaption class="evidence-figcaption">
                    <a
                      href=${loc.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      class="external-link"
                    >
                      Open Source URL ↗
                    </a>
                  </figcaption>
                `}
              </figure>
            </div>
          `}

          ${(loc.source_type === 'markdown' || loc.source_type === 'docx') && html`
            <div class="doc-excerpt-frame">
              <div class="card-meta-row">
                <span class="control-label">${loc.file_name}</span>
                <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                  ${loc.locator_key || 'EXCERPT'}
                </span>
              </div>
              <blockquote class="evidence-blockquote">
                “${node.quote}”
              </blockquote>
              ${loc.payload_hash && html`
                <p class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                  ${loc.payload_hash}
                </p>
              `}
            </div>
          `}

          ${!loc.source_type && html`
            <figure class="evidence-figure">
              ${node.quote && html`
                <blockquote class="evidence-blockquote" cite=${node.url || ''}>
                  “${node.quote}”
                </blockquote>
              `}
              ${node.body && html`<p class="card-body-prose">${node.body}</p>`}
              ${node.url && html`
                <figcaption class="evidence-figcaption">
                  <a
                    href=${node.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    class="external-link"
                  >
                    Open Controlling Authority ↗
                  </a>
                </figcaption>
              `}
            </figure>
          `}
        </div>
      </aside>
    </div>
  `;
}

/**
 * Reusable inline comment thread & composer anchored to a node or section.
 */
function InlineCommentPanel({
  targetKey,
  scope = 'node',
  nodeId = null,
  sectionId = null,
  targetLabel = '',
  placeholder = 'Write feedback or request a verification check...',
  comments,
  nodesMap,
  isOpen,
  onClose,
  onSubmit,
  onDelete,
  submitting,
  allowStatusOverride = true,
}) {
  const [draftText, setDraftText] = useState('');
  const [suggestedStatus, setSuggestedStatus] = useState('');

  const matchingComments = (comments || []).filter((c) => {
    if (scope === 'section') {
      return c.scope === 'section' && c.section_id === sectionId;
    }
    return c.node_id === nodeId && (c.scope || 'node') !== 'link';
  });

  const handleSave = async (e) => {
    e.preventDefault();
    if (!draftText.trim()) return;
    await onSubmit({
      scope,
      node_id: nodeId,
      section_id: sectionId,
      target_label: targetLabel,
      comment_text: draftText.trim(),
      suggested_status: suggestedStatus || null,
    });
    setDraftText('');
    setSuggestedStatus('');
    onClose();
  };

  if (matchingComments.length === 0 && !isOpen) return null;

  return html`
    <div class="inline-comment-well">
      ${matchingComments.length > 0 && html`
        <div class="comment-thread-list">
          ${matchingComments.map((c) => {
            const tag = formatScopeTag(c, nodesMap);
            return html`
              <div key=${c.comment_id} class="comment-item ${c.resolved ? 'is-resolved' : ''}">
                <div class="card-meta-row">
                  <span style="display: inline-flex; align-items: center; gap: 6px;">
                    <span class="scope-tag ${tag.cls}">${tag.label}</span>
                    <span class="provenance-caption">
                      ${c.resolved ? 'Resolved' : 'Queued'}
                      ${c.suggested_status ? ` · ${formatAuditStatus(c.suggested_status)}` : ''}
                    </span>
                  </span>
                  ${!c.resolved && html`
                    <button
                      type="button"
                      class="btn-link is-muted"
                      onClick=${() => onDelete(c.comment_id)}
                    >
                      Remove
                    </button>
                  `}
                </div>
                <p class="comment-item-text">${c.comment_text}</p>
              </div>
            `;
          })}
        </div>
      `}

      ${isOpen && html`
        <form onSubmit=${handleSave} style="display: flex; flex-direction: column; gap: 8px;">
          <label for=${`cmt-input-${targetKey}`} class="control-label">
            Add Feedback
          </label>
          <textarea
            id=${`cmt-input-${targetKey}`}
            class="comment-textarea"
            placeholder=${placeholder}
            value=${draftText}
            onInput=${(e) => setDraftText(e.target.value)}
            required
          ></textarea>
          <div class="card-meta-row" style="flex-wrap: wrap;">
            ${allowStatusOverride ? html`
              <select
                class="select-control"
                aria-label="Optional verification status override"
                value=${suggestedStatus}
                onChange=${(e) => setSuggestedStatus(e.target.value)}
              >
                <option value="">Keep Status</option>
                <option value="verified">Mark Verified</option>
                <option value="extrapolation">Flag Extrapolation</option>
                <option value="assumption">Flag Assumption</option>
                <option value="disputed">Flag Disputed</option>
              </select>
            ` : html`<span></span>`}
            <div style="display: flex; gap: 6px;">
              <button type="button" class="btn btn-compact" onClick=${onClose}>
                Cancel
              </button>
              <button type="submit" class="btn btn-primary btn-compact" disabled=${submitting}>
                ${submitting ? 'Saving…' : 'Queue Note'}
              </button>
            </div>
          </div>
        </form>
      `}
    </div>
  `;
}

/**
 * Anchored Logical-Link Popover triggered by clicking a Bezier curve or its midpoint handle.
 */
function LinkCommentPopover({
  link,
  nodesMap,
  comments,
  onClose,
  onSubmitComment,
  onDeleteComment,
  onOpenInspector,
  submitting,
}) {
  const [draftText, setDraftText] = useState('');
  const [suggestedStatus, setSuggestedStatus] = useState('');

  if (!link) return null;
  const targetNode = nodesMap[link.targetId];
  const sourceNode = nodesMap[link.sourceId];
  if (!targetNode) return null;

  const linkComments = (comments || []).filter(
    (c) => c.node_id === targetNode.id && c.scope === 'link'
  );
  const roleMeta = getLinkRoleMeta(targetNode);

  const left = Math.min(window.innerWidth - 388, Math.max(16, link.screenMidX - 185));
  const top = Math.min(window.innerHeight - 360, Math.max(64, link.screenMidY + 18));

  const handleSave = async (e) => {
    e.preventDefault();
    if (!draftText.trim()) return;
    await onSubmitComment({
      scope: 'link',
      node_id: targetNode.id,
      section_id: targetNode.section_id,
      target_label: `${sourceNode ? sourceNode.title : 'Claim'} → ${targetNode.title}`,
      comment_text: draftText.trim(),
      suggested_status: suggestedStatus || null,
    });
    setDraftText('');
    setSuggestedStatus('');
  };

  return html`
    <div
      class="link-popover-card"
      role="dialog"
      aria-label="Logical Link Details & Feedback"
      style=${{ top: `${top}px`, left: `${left}px` }}
    >
      <div class="card-meta-row">
        <span style="display: inline-flex; align-items: center; gap: 6px;">
          <span class="scope-tag is-link">Logical Link · ${roleMeta.label}</span>
        </span>
        <button
          type="button"
          class="btn btn-icon-only btn-compact"
          aria-label="Close link feedback popover"
          onClick=${onClose}
        >
          <${Icon} name="close" size=${12} />
        </button>
      </div>

      <div class="link-chain-preview">
        <div>
          <strong>From:</strong> ${sourceNode ? sourceNode.title : 'Document Claim'}
        </div>
        <div style="display: flex; align-items: flex-start; gap: 5px;">
          <${Icon} name="link" size=${13} />
          <span><strong>To:</strong> ${targetNode.title}</span>
        </div>
        ${(targetNode.body || targetNode.audit?.evaluator_note) && html`
          <div class="provenance-caption" style="margin-top: 3px; color: var(--color-text-body);">
            ${targetNode.body || targetNode.audit?.evaluator_note}
          </div>
        `}
      </div>

      ${linkComments.length > 0 && html`
        <div class="comment-thread-list">
          ${linkComments.map((c) => html`
            <div key=${c.comment_id} class="comment-item ${c.resolved ? 'is-resolved' : ''}">
              <div class="card-meta-row">
                <span class="provenance-caption">
                  ${c.resolved ? 'Resolved Link Note' : 'Queued Link Note'}
                  ${c.suggested_status ? ` · ${formatAuditStatus(c.suggested_status)}` : ''}
                </span>
                ${!c.resolved && html`
                  <button
                    type="button"
                    class="btn-link is-muted"
                    onClick=${() => onDeleteComment(c.comment_id)}
                  >
                    Remove
                  </button>
                `}
              </div>
              <p class="comment-item-text">${c.comment_text}</p>
            </div>
          `)}
        </div>
      `}

      <form onSubmit=${handleSave} style="display: flex; flex-direction: column; gap: 8px;">
        <label for="link-comment-input" class="control-label">
          Comment on This Connection
        </label>
        <textarea
          id="link-comment-input"
          class="comment-textarea"
          placeholder="E.g., Does this fact actually support this conclusion, or is it an extrapolation?"
          value=${draftText}
          onInput=${(e) => setDraftText(e.target.value)}
          required
        ></textarea>
        <div class="card-meta-row" style="flex-wrap: wrap;">
          <select
            class="select-control"
            aria-label="Flag connection audit status"
            value=${suggestedStatus}
            onChange=${(e) => setSuggestedStatus(e.target.value)}
          >
            <option value="">Keep Status</option>
            <option value="verified">Verified Link</option>
            <option value="extrapolation">Weak / Extrapolation</option>
            <option value="assumption">Unstated Assumption</option>
            <option value="disputed">Disputed Connection</option>
          </select>
          <div style="display: flex; gap: 6px;">
            ${(targetNode.locator || targetNode.quote || targetNode.url) && html`
              <button
                type="button"
                class="btn btn-compact"
                onClick=${() => {
                  onClose();
                  onOpenInspector(targetNode);
                }}
              >
                <${Icon} name="source" size=${12} />
                Source
              </button>
            `}
            <button type="submit" class="btn btn-primary btn-compact" disabled=${submitting}>
              ${submitting ? 'Saving…' : 'Queue Link Note'}
            </button>
          </div>
        </div>
      </form>
    </div>
  `;
}

/**
 * Streamlined Editorial Plate for Direct Evidence, Logical Inference, Calculations & Rules.
 */
function SpatialNodeCard({
  node,
  level,
  nodesMap,
  activeNodeIds,
  expandedLevel2Ids,
  tensionClaimIds,
  auditFilter,
  comments,
  commentingKey,
  onToggleComment,
  onSubmitComment,
  onDeleteComment,
  submittingComment,
  onHoverRef,
  onLeaveRef,
  onClickRef,
  onToggleSubtree,
  onOpenInspector,
  sourceLink,
  isFocused,
}) {
  if (!node) return null;
  const audit = node.audit || {};
  const status = audit.status || 'verified';
  const childIds = node.direct_child_ids || [];
  const hasChildren = childIds.length > 0;
  const areChildrenExpanded = hasChildren && childIds.some((id) => expandedLevel2Ids.includes(id));
  const provenance = formatProvenanceParts(node.locator);

  const isFinancial = node.type === 'calculation' || node.locator?.source_type === 'spreadsheet';
  const isAuthority = node.type === 'authority';
  const caveatFlag = isCaveatStatus(status);

  const plateToneClass = caveatFlag
    ? 'plate-caveat'
    : isFinancial
    ? 'plate-financial'
    : isAuthority
    ? 'plate-authority'
    : '';

  const roleToneClass = caveatFlag
    ? 'is-caveat'
    : isFinancial
    ? 'is-emerald'
    : isAuthority
    ? 'is-copper'
    : '';

  const nodeComments = (comments || []).filter((c) => c.node_id === node.id);
  const pendingCount = nodeComments.filter((c) => !c.resolved).length;
  const panelKey = `node:${node.id}`;
  const isCommentOpen = commentingKey === panelKey;

  const showAuditNote =
    audit.evaluator_note &&
    audit.evaluator_note !== 'Deterministic node compilation' &&
    (caveatFlag || audit.evaluator_type !== 'deterministic');

  return html`
    <article
      class="spatial-node-card ${plateToneClass} ${isFocused ? 'is-focused' : ''}"
      data-card-node-id=${node.id}
      data-card-level=${level}
    >
      <div class="plate-header-strip">
        <span class="plate-role-meta">
          <span class="plate-role-name ${roleToneClass}">${formatNodeRole(node.type)}</span>
          ${provenance.label && html`
            <span>· ${provenance.label}${provenance.coord ? `, ${provenance.coord}` : ''}</span>
          `}
        </span>
        <span class="arch-stamp ${caveatFlag ? 'is-caveat' : ''}">
          ${formatAuditStatus(status)}
        </span>
      </div>

      <div class="plate-body-stage">
        <h3 class="card-heading">${node.title}</h3>

        ${(node.locator?.reliability_tier || node.locator?.origin_description || sourceLink?.isSampleFixture) && html`
          <div class="provenance-origin-row">
            ${formatReliabilityTier(node.locator?.reliability_tier) && html`
              <span class="reliability-pill ${formatReliabilityTier(node.locator.reliability_tier).cls}">
                ${formatReliabilityTier(node.locator.reliability_tier).label}
              </span>
            `}
            ${node.locator?.origin_description && html`
              <span class="provenance-origin-text" title=${node.locator.origin_description}>
                ${node.locator.origin_description}
              </span>
            `}
            ${sourceLink?.isSampleFixture && html`
              <span class="sample-fixture-badge" title="Referenced in sample bundle; raw file is not stored on disk">
                Sample Fixture (No Raw File on Disk)
              </span>
            `}
          </div>
        `}

        ${node.quote && html`
          <figure class="evidence-figure">
            <blockquote class="evidence-blockquote" cite=${node.url || node.locator?.url || ''}>
              “${node.quote}”
            </blockquote>
            ${node.url && html`
              <figcaption class="evidence-figcaption">
                <a
                  href=${node.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  class="external-link"
                >
                  Open External Authority ↗
                </a>
              </figcaption>
            `}
          </figure>
        `}

        ${node.formula && html`
          <div class="formula-box" title="Verified Formula Expression">
            ${node.formula}
          </div>
        `}

        ${node.body && html`
          <p class="card-body-prose">
            ${renderAnnotatedText({
              text: node.body,
              nodesMap,
              activeNodeIds,
              tensionClaimIds,
              auditFilter,
              onHoverRef,
              onLeaveRef,
              onClickRef,
              level,
            })}
          </p>
        `}

        ${showAuditNote && html`
          <div class="card-evaluator-note">
            <span><strong>Audit Note:</strong> ${audit.evaluator_note}</span>
          </div>
        `}
      </div>

      <div class="plate-footer-row">
        <div class="plate-actions-group">
          <button
            type="button"
            class="plate-action-btn ${pendingCount > 0 ? 'has-notes' : ''}"
            onClick=${() => onToggleComment(isCommentOpen ? null : panelKey)}
          >
            <${Icon} name="comment" size=${13} />
            <span>
              ${isCommentOpen
                ? 'Close Note'
                : pendingCount > 0
                ? `Comment (${pendingCount})`
                : 'Comment'}
            </span>
          </button>

          ${(node.locator || node.url || node.quote) && html`
            <button
              type="button"
              class="plate-action-btn"
              onClick=${() => onOpenInspector(node)}
            >
              <${Icon} name="source" size=${13} />
              <span>Source</span>
            </button>
          `}

          ${sourceLink?.existsOnDisk && sourceLink.url && html`
            <a
              href=${sourceLink.url}
              target="_blank"
              rel="noopener noreferrer"
              class="plate-action-btn source-file-link"
              title=${`Open ${sourceLink.fileName || 'source file'} in new tab`}
            >
              <${Icon} name="link" size=${12} />
              <span>${sourceLink.label}</span>
            </a>
          `}
        </div>

        ${hasChildren && html`
          <button
            type="button"
            class="btn-link"
            onClick=${() => onToggleSubtree(node)}
          >
            <span>${areChildrenExpanded ? `Hide sources (${childIds.length})` : `Sources & Law (${childIds.length})`}</span>
            <${Icon} name="chevronRight" size=${12} />
          </button>
        `}
      </div>

      <${InlineCommentPanel}
        targetKey=${panelKey}
        scope="node"
        nodeId=${node.id}
        sectionId=${node.section_id}
        targetLabel=${node.title}
        comments=${comments}
        nodesMap=${nodesMap}
        isOpen=${isCommentOpen}
        onClose=${() => onToggleComment(null)}
        onSubmit=${onSubmitComment}
        onDelete=${onDeleteComment}
        submitting=${submittingComment}
      />
    </article>
  `;
}

const SAMPLE_TIER1_COMPILE_PAYLOAD = {
  bundle_id: 'live_compiled_demo',
  title: 'Q4 Cloud Infrastructure & Security Compliance Memo',
  summary: 'Compiled live via the Tier-1 SectionValidator, StitchInvariantGate, and CompiledGraphBuilder.',
  metadata: {
    document_type: 'Live Compiled Engineering Audit',
  },
  sections: [
    {
      section_id: 'sec_01_soc2',
      section_title: 'I. Zero-Trust Encryption & Audit Posture',
      text: "All production customer databases enforce <ref n='1'>AES-256 envelope encryption at rest with automated 90-day KMS key rotation</ref>.",
      supports: [
        {
          n: 1,
          title: 'KMS Envelope Encryption Compliance',
          items: [
            {
              type: 'evidence',
              title: 'AWS KMS Config Snapshot',
              quote: 'KeyRotationEnabled: true, RotationPeriodInDays: 90, Cipher: AES-256-GCM.',
              locator: {
                source_type: 'api',
                endpoint: 'GET /v1/kms/key-policies',
                method: 'GET',
                json_path: '$.keys[*].rotation_policy',
                raw_value: 90,
              },
            },
            {
              type: 'reasoning',
              title: 'SOC2 Type II Criterion CC6.1 Satisfaction',
              body: "Automated 90-day rotation satisfies the <ref n='101'>AICPA Trust Services Criteria CC6.1</ref> for cryptographic key lifecycle management.",
              sub_supports: [
                {
                  n: 101,
                  type: 'authority',
                  title: 'AICPA SOC2 Trust Services Criteria § CC6.1',
                  quote: 'Logical access security software, infrastructure, and architectures are implemented over protected information assets.',
                  url: 'https://www.aicpa-cima.com/resources/download/trust-services-criteria',
                },
              ],
            },
          ],
        },
      ],
    },
  ],
  smoothed_text:
    "As verified during the Q4 security review, all production customer databases enforce <ref n='1'>AES-256 envelope encryption at rest with automated 90-day KMS key rotation</ref>.",
};

/**
 * Slide-Over Review Queue Drawer summarizing all Overall Memo, Section, Logical Link,
 * Claim, and Evidence comments before batch regeneration.
 */
function ReviewQueueDrawer({
  isOpen,
  pendingComments,
  nodesMap,
  onClose,
  onJumpToComment,
  onDeleteComment,
  onRegenerate,
  regenerating,
}) {
  const closeBtnRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return undefined;
    const prevFocus = document.activeElement;
    requestAnimationFrame(() => closeBtnRef.current?.focus());
    return () => {
      if (prevFocus && typeof prevFocus.focus === 'function') {
        prevFocus.focus();
      }
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return html`
    <div
      class="inspector-backdrop"
      onClick=${(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside
        class="source-inspector-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-queue-title"
      >
        <div class="drawer-header">
          <h2 id="review-queue-title" class="card-heading" style="font-size: 18px;">
            Review Queue (${pendingComments.length})
          </h2>
          <button
            ref=${closeBtnRef}
            type="button"
            class="btn btn-icon-only"
            aria-label="Close review queue"
            onClick=${onClose}
          >
            <${Icon} name="close" />
          </button>
        </div>

        <div class="drawer-body">
          <p class="provenance-caption">
            Notes anchored to claims, evidence, logical connections, sections, or the overall memo
            are triaged together when you re-compile.
          </p>

          ${pendingComments.length === 0 ? html`
            <p class="card-body-prose" style="color: var(--color-text-muted);">
              No pending notes yet. Click any evidence card, Bezier curve handle, or use the bottom bar to leave feedback.
            </p>
          ` : html`
            <div class="comment-thread-list">
              ${pendingComments.map((c) => {
                const tag = formatScopeTag(c, nodesMap);
                const targetNode = nodesMap[c.node_id];
                const title = c.target_label || targetNode?.title || c.section_id;
                return html`
                  <div key=${c.comment_id} class="comment-item">
                    <div class="card-meta-row">
                      <span style="display: inline-flex; align-items: center; gap: 6px; min-width: 0;">
                        <span class="scope-tag ${tag.cls}">${tag.label}</span>
                        <span class="provenance-caption" style="color: var(--color-text-primary); font-weight: 500;">
                          ${title}
                        </span>
                      </span>
                    </div>
                    <p class="comment-item-text">${c.comment_text}</p>
                    <div class="card-meta-row" style="margin-top: 4px;">
                      <button
                        type="button"
                        class="btn-link"
                        onClick=${() => {
                          onJumpToComment(c);
                          onClose();
                        }}
                      >
                        Jump to Target
                      </button>
                      <button
                        type="button"
                        class="btn-link is-muted"
                        onClick=${() => onDeleteComment(c.comment_id)}
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                `;
              })}
            </div>
          `}

          ${pendingComments.length > 0 && html`
            <button
              type="button"
              class="btn btn-primary"
              disabled=${regenerating}
              onClick=${async () => {
                await onRegenerate();
                onClose();
              }}
            >
              ${regenerating
                ? 'Triaging & Regenerating…'
                : `Apply Feedback & Re-compile (${pendingComments.length})`}
            </button>
          `}
        </div>
      </aside>
    </div>
  `;
}

/**
 * Dedicated File & Controlling Rule Manager dialog for Canonical Corpus (b) and Matter Inputs (a).
 */
function CorpusManagerModal({
  dialogRef,
  activeMatterHint,
  initialTab = 'canonical',
  onCorpusChanged,
}) {
  const [activeTab, setActiveTab] = useState(initialTab);
  const [corpusStatus, setCorpusStatus] = useState(null);
  const [selectedDocId, setSelectedDocId] = useState(null);
  const [docDetail, setDocDetail] = useState(null);
  const [docLoading, setDocLoading] = useState(false);

  const [canonicalDomain, setCanonicalDomain] = useState('legal');
  const [canonicalBusy, setCanonicalBusy] = useState(false);
  const [canonicalProgress, setCanonicalProgress] = useState([]);

  const [matters, setMatters] = useState([]);
  const [selectedMatter, setSelectedMatter] = useState(activeMatterHint || 'legal_motion_1332');
  const [newMatterName, setNewMatterName] = useState('');
  const [matterFilesData, setMatterFilesData] = useState(null);
  const [matterBusy, setMatterBusy] = useState(false);
  const [matterProgress, setMatterProgress] = useState([]);
  const [uploadReliabilityTier, setUploadReliabilityTier] = useState('primary_record');
  const [uploadOriginDescription, setUploadOriginDescription] = useState('');
  const [rowMetaDrafts, setRowMetaDrafts] = useState({});
  const [editingMetaFile, setEditingMetaFile] = useState(null);
  const [savingMetaFile, setSavingMetaFile] = useState(null);

  const [errorMsg, setErrorMsg] = useState(null);

  useEffect(() => {
    const nextDrafts = {};
    for (const f of matterFilesData?.files || []) {
      nextDrafts[f.filename] = {
        reliability_tier: f.reliability_tier || 'primary_record',
        origin_description: f.origin_description || '',
      };
    }
    setRowMetaDrafts(nextDrafts);
  }, [matterFilesData]);

  useEffect(() => {
    setActiveTab(initialTab);
  }, [initialTab]);

  useEffect(() => {
    if (activeMatterHint) {
      setSelectedMatter(activeMatterHint);
    }
  }, [activeMatterHint]);

  const refreshCanonical = useCallback(async () => {
    const res = await fetch('/api/canonical');
    if (res.ok) {
      const data = await res.json();
      setCorpusStatus(data);
    }
  }, []);

  const refreshMatters = useCallback(async () => {
    const res = await fetch('/api/matters');
    if (res.ok) {
      const data = await res.json();
      const list = data.matters || [];
      setMatters(list);
      if (list.length > 0 && !list.some((m) => m.matter_id === selectedMatter)) {
        setSelectedMatter(list[0].matter_id);
      }
    }
  }, [selectedMatter]);

  const refreshMatterFiles = useCallback(async (matterId) => {
    if (!matterId) return;
    const res = await fetch(`/api/matters/${matterId}/files`);
    if (res.ok) {
      setMatterFilesData(await res.json());
    }
  }, []);

  useEffect(() => {
    refreshCanonical();
    refreshMatters();
  }, [refreshCanonical, refreshMatters]);

  useEffect(() => {
    if (selectedMatter) {
      refreshMatterFiles(selectedMatter);
    }
  }, [selectedMatter, refreshMatterFiles]);

  const handleInspectCanonicalDoc = async (docId) => {
    setSelectedDocId(docId);
    setDocLoading(true);
    setErrorMsg(null);
    try {
      const encodedPath = docId
        .split('/')
        .map((seg) => encodeURIComponent(seg))
        .join('/');
      const res = await fetch(`/api/canonical/documents/${encodedPath}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Failed to load ${docId}`);
      }
      setDocDetail(await res.json());
    } catch (err) {
      setErrorMsg(err.message);
      setDocDetail(null);
    } finally {
      setDocLoading(false);
    }
  };

  const handleCanonicalUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setCanonicalBusy(true);
    setErrorMsg(null);
    setCanonicalProgress([{ stage: 'upload', message: `Uploading ${file.name}…` }]);
    try {
      const formData = new FormData();
      formData.append('domain', canonicalDomain.trim() || 'general');
      formData.append('file', file);
      const data = await streamUploadOrIngest(
        '/api/canonical/upload/stream',
        { method: 'POST', body: formData },
        (ev) => setCanonicalProgress((prev) => [...prev, ev])
      );
      if (data) {
        setCorpusStatus(data);
        await onCorpusChanged?.();
      }
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setCanonicalBusy(false);
      e.target.value = '';
    }
  };

  const handleRebuildCanonical = async (purgeEncoded) => {
    setCanonicalBusy(true);
    setErrorMsg(null);
    setCanonicalProgress([
      {
        stage: 'ingest',
        message: purgeEncoded ? 'Purging & re-encoding canonical corpus…' : 'Rebuilding canonical index…',
      },
    ]);
    try {
      const data = await streamUploadOrIngest(
        '/api/canonical/ingest/stream',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ purge_encoded: Boolean(purgeEncoded) }),
        },
        (ev) => setCanonicalProgress((prev) => [...prev, ev])
      );
      if (data) {
        setCorpusStatus(data);
        if (selectedDocId) {
          handleInspectCanonicalDoc(selectedDocId);
        }
        await onCorpusChanged?.();
      }
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setCanonicalBusy(false);
    }
  };

  const handleDeleteCanonical = async (domain, filename, docId) => {
    if (!window.confirm(`Delete canonical rule file '${domain}/${filename}' and rebuild INDEX.md?`)) {
      return;
    }
    setCanonicalBusy(true);
    setErrorMsg(null);
    try {
      const res = await fetch(
        `/api/canonical/files/${encodeURIComponent(domain)}/${encodeURIComponent(filename)}`,
        { method: 'DELETE' }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Failed to delete ${filename}`);
      }
      const data = await res.json();
      setCorpusStatus(data);
      if (docId && selectedDocId === docId) {
        setSelectedDocId(null);
        setDocDetail(null);
      }
      await onCorpusChanged?.();
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setCanonicalBusy(false);
    }
  };

  const handleCreateMatter = async () => {
    if (!newMatterName.trim()) return;
    setErrorMsg(null);
    const res = await fetch('/api/matters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ matter_id: newMatterName.trim() }),
    });
    if (res.ok) {
      const created = await res.json();
      setNewMatterName('');
      await refreshMatters();
      setSelectedMatter(created.matter_id);
      await onCorpusChanged?.();
    } else {
      const err = await res.json().catch(() => ({}));
      setErrorMsg(formatApiError(err));
    }
  };

  const handleMatterUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file || !selectedMatter) return;
    setMatterBusy(true);
    setErrorMsg(null);
    setMatterProgress([{ stage: 'upload', message: `Uploading ${file.name} to ${selectedMatter}…` }]);
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('reliability_tier', uploadReliabilityTier || 'primary_record');
      if (uploadOriginDescription.trim()) {
        formData.append('origin_description', uploadOriginDescription.trim());
      }
      const data = await streamUploadOrIngest(
        `/api/matters/${selectedMatter}/upload/stream`,
        { method: 'POST', body: formData },
        (ev) => setMatterProgress((prev) => [...prev, ev])
      );
      if (data) {
        setMatterFilesData(data);
        setUploadOriginDescription('');
        await refreshMatters();
        await onCorpusChanged?.();
      }
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setMatterBusy(false);
      e.target.value = '';
    }
  };

  const handleSaveFileMetadata = async (filename) => {
    if (!selectedMatter || !filename) return;
    const draft = rowMetaDrafts[filename];
    if (!draft) return;
    setSavingMetaFile(filename);
    setErrorMsg(null);
    try {
      const res = await fetch(
        `/api/matters/${selectedMatter}/files/${encodeURIComponent(filename)}/metadata`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            reliability_tier: draft.reliability_tier,
            origin_description: draft.origin_description.trim() || null,
          }),
        }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Failed to update metadata for ${filename}`);
      }
      const updated = await res.json();
      setMatterFilesData(updated);
      setEditingMetaFile(null);
      await refreshMatters();
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setSavingMetaFile(null);
    }
  };

  const handleReindexMatter = async () => {
    if (!selectedMatter) return;
    setMatterBusy(true);
    setErrorMsg(null);
    setMatterProgress([{ stage: 'ingest', message: `Indexing coordinates in ${selectedMatter}…` }]);
    try {
      const data = await streamUploadOrIngest(
        `/api/matters/${selectedMatter}/ingest/stream`,
        { method: 'POST' },
        (ev) => setMatterProgress((prev) => [...prev, ev])
      );
      if (data) {
        setMatterFilesData(data);
        await refreshMatters();
      }
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setMatterBusy(false);
    }
  };

  const handleDeleteMatterFile = async (filename) => {
    if (!selectedMatter) return;
    if (!window.confirm(`Delete '${filename}' from matter '${selectedMatter}' and re-index?`)) {
      return;
    }
    setMatterBusy(true);
    setErrorMsg(null);
    try {
      const res = await fetch(
        `/api/matters/${selectedMatter}/files/${encodeURIComponent(filename)}`,
        { method: 'DELETE' }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Failed to delete ${filename}`);
      }
      setMatterFilesData(await res.json());
      await refreshMatters();
      await onCorpusChanged?.();
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setMatterBusy(false);
    }
  };

  const catalogDocs = corpusStatus?.catalog?.documents || [];
  const rawFiles = corpusStatus?.raw_files || [];
  const rawByDomainStem = {};
  for (const rf of rawFiles) {
    const stem = rf.filename.replace(/\.[^.]+$/, '').toLowerCase();
    rawByDomainStem[`${rf.domain}/${stem}`] = rf;
  }

  return html`
    <dialog
      ref=${dialogRef}
      class="compiler-dialog is-wide"
      closedby="any"
      aria-labelledby="corpus-dialog-title"
    >
      <div class="dialog-inner">
        <div class="modal-header-row">
          <h2 id="corpus-dialog-title" class="card-heading" style="font-size: 18px;">
            Corpus & File Manager
          </h2>
          <form method="dialog">
            <button
              type="submit"
              class="btn btn-icon-only"
              aria-label="Close file manager"
              disabled=${canonicalBusy || matterBusy}
            >
              <${Icon} name="close" />
            </button>
          </form>
        </div>

        <div class="modal-tabs" role="tablist" aria-label="Corpus sections">
          <button
            type="button"
            role="tab"
            aria-selected=${activeTab === 'canonical'}
            class="modal-tab-btn ${activeTab === 'canonical' ? 'is-active' : ''}"
            onClick=${() => setActiveTab('canonical')}
          >
            Controlling Rules (${corpusStatus?.total_authorities ?? 0} authorities)
          </button>
          <button
            type="button"
            role="tab"
            aria-selected=${activeTab === 'matter'}
            class="modal-tab-btn ${activeTab === 'matter' ? 'is-active' : ''}"
            onClick=${() => setActiveTab('matter')}
          >
            Matter Inputs (${matterFilesData?.files?.length ?? 0} files)
          </button>
        </div>

        ${errorMsg && html`
          <pre
            tabindex="0"
            class="formula-box"
            style="border-color: var(--color-danger); color: var(--color-danger); background-color: var(--color-danger-subtle);"
          ><code>${errorMsg}</code></pre>
        `}

        ${activeTab === 'canonical' && html`
          <div style="display: flex; flex-direction: column; gap: 12px;">
            <div class="toolbar-action-row">
              <div class="toolbar-cluster">
                <label for="mgr-canonical-domain" class="control-label">Domain</label>
                <input
                  id="mgr-canonical-domain"
                  type="text"
                  class="text-input"
                  style="width: 120px;"
                  value=${canonicalDomain}
                  disabled=${canonicalBusy}
                  onInput=${(e) => setCanonicalDomain(e.target.value)}
                />
                <label class="btn btn-primary file-picker-label">
                  <${Icon} name="plus" size=${13} />
                  <span>${canonicalBusy ? 'Working…' : 'Add / Replace Rule File'}</span>
                  <input
                    type="file"
                    accept=".md,.txt,.pdf,.docx"
                    disabled=${canonicalBusy}
                    style="display: none;"
                    onChange=${handleCanonicalUpload}
                  />
                </label>
              </div>
              <div class="toolbar-cluster">
                <button
                  type="button"
                  class="btn btn-compact"
                  disabled=${canonicalBusy}
                  onClick=${() => handleRebuildCanonical(false)}
                >
                  Rebuild Index
                </button>
                <button
                  type="button"
                  class="btn btn-compact"
                  disabled=${canonicalBusy}
                  onClick=${() => handleRebuildCanonical(true)}
                >
                  Full Re-encode
                </button>
              </div>
            </div>

            ${canonicalProgress.length > 0 && html`
              <div class="stage-progress-box">
                ${canonicalProgress.map(
                  (ev, idx) => html`
                    <div key=${idx}>
                      <span class="font-mono-data" style="color: var(--color-accent-primary);">[${ev.stage}]</span> ${ev.message}
                    </div>
                  `
                )}
              </div>
            `}

            <div class="corpus-split-grid">
              <div class="corpus-table-wrap">
                <table class="corpus-table">
                  <thead>
                    <tr>
                      <th>Document</th>
                      <th>Domain</th>
                      <th>Rules</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${catalogDocs.length === 0 && rawFiles.length === 0 && html`
                      <tr>
                        <td colspan="4" style="text-align: center; color: var(--color-text-muted); padding: 20px;">
                          No canonical rule documents loaded yet. Upload a Markdown, TXT, PDF, or DOCX file above.
                        </td>
                      </tr>
                    `}
                    ${catalogDocs.map((card) => {
                      const docStem = card.doc_id
                        .split('/')
                        .pop()
                        .replace(/(\.authorities)?\.[^.]+$/, '')
                        .toLowerCase();
                      const matchedRaw = rawByDomainStem[`${card.domain}/${docStem}`];
                      const deleteTargetName = matchedRaw
                        ? matchedRaw.filename
                        : card.doc_id.split('/').pop();
                      const isSelected = selectedDocId === card.doc_id;
                      return html`
                        <tr key=${card.doc_id} class=${isSelected ? 'is-selected' : ''}>
                          <td>
                            <div style="font-weight: 600; color: var(--color-text-primary);">${card.title || card.doc_id}</div>
                            <div class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">${card.doc_id}</div>
                          </td>
                          <td><span class="font-mono-data">${card.domain}</span></td>
                          <td class="font-mono-data">${card.authority_count}</td>
                          <td>
                            <div style="display: inline-flex; gap: 4px;">
                              <button
                                type="button"
                                class="btn btn-compact"
                                onClick=${() => handleInspectCanonicalDoc(card.doc_id)}
                              >
                                Inspect
                              </button>
                              <a
                                href=${`/api/canonical/files/${encodeURIComponent(card.domain)}/${encodeURIComponent(deleteTargetName)}/raw`}
                                target="_blank"
                                rel="noopener noreferrer"
                                class="btn btn-compact"
                                style="text-decoration: none;"
                                title="Open raw rule source file in new tab"
                              >
                                File ↗
                              </a>
                              <button
                                type="button"
                                class="btn btn-compact btn-danger-ghost"
                                aria-label="Delete ${deleteTargetName}"
                                disabled=${canonicalBusy}
                                onClick=${() => handleDeleteCanonical(card.domain, deleteTargetName, card.doc_id)}
                              >
                                <${Icon} name="trash" size=${12} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      `;
                    })}
                  </tbody>
                </table>
              </div>

              <div class="doc-inspector-card">
                ${docLoading && html`<div class="provenance-caption">Loading rules & outline…</div>`}
                ${!docLoading && !docDetail && html`
                  <div class="provenance-caption">
                    Select any document and click <strong>Inspect</strong> to review its outline and extracted controlling rules.
                  </div>
                `}
                ${!docLoading && docDetail && html`
                  <div style="display: flex; flex-direction: column; gap: 8px;">
                    <div>
                      <div style="font-weight: 600; color: var(--color-text-primary);">
                        ${docDetail.card?.title || docDetail.doc_id}
                      </div>
                      <div class="provenance-caption">
                        <span class="font-mono-data">${docDetail.doc_id}</span> · ${(docDetail.authorities || []).length} rules
                      </div>
                    </div>
                    ${docDetail.card?.scope_synopsis && html`
                      <div class="provenance-caption">${docDetail.card.scope_synopsis}</div>
                    `}
                    ${(docDetail.authorities || []).map(
                      (auth) => html`
                        <div key=${auth.auth_id} class="auth-detail-item">
                          <div class="font-mono-data" style="font-size: 11px; color: var(--color-accent-primary);">
                            [${auth.auth_id}]
                          </div>
                          <div style="font-weight: 600; color: var(--color-text-primary);">${auth.title}</div>
                          <div style="color: var(--color-text-body);">${auth.verbatim_quote}</div>
                        </div>
                      `
                    )}
                    ${docDetail.toc_markdown && html`
                      <details>
                        <summary class="control-label" style="cursor: pointer;">Document Outline & Section Map</summary>
                        <pre class="formula-box" style="margin-top: 6px; font-size: 11px;"><code>${docDetail.toc_markdown}</code></pre>
                      </details>
                    `}
                  </div>
                `}
              </div>
            </div>
          </div>
        `}

        ${activeTab === 'matter' && html`
          <div style="display: flex; flex-direction: column; gap: 12px;">
            <div class="toolbar-action-row">
              <div class="toolbar-cluster" style="flex: 1;">
                <label for="mgr-matter-select" class="control-label">Matter</label>
                <select
                  id="mgr-matter-select"
                  class="select-control"
                  value=${selectedMatter}
                  onChange=${(e) => setSelectedMatter(e.target.value)}
                >
                  ${matters.map(
                    (m) => html`
                      <option key=${m.matter_id} value=${m.matter_id}>
                        ${m.matter_id} (${m.raw_files?.length || 0} files)
                      </option>
                    `
                  )}
                </select>
                <input
                  type="text"
                  class="text-input"
                  style="width: 150px;"
                  placeholder="New matter name…"
                  value=${newMatterName}
                  onInput=${(e) => setNewMatterName(e.target.value)}
                />
                <button type="button" class="btn btn-compact" onClick=${handleCreateMatter}>
                  Create
                </button>
              </div>
              <div class="toolbar-cluster">
                <select
                  aria-label="Upload reliability tier"
                  class="select-control"
                  value=${uploadReliabilityTier}
                  disabled=${matterBusy || !selectedMatter}
                  onChange=${(e) => setUploadReliabilityTier(e.target.value)}
                >
                  <option value="primary_record">Primary Record</option>
                  <option value="secondary_analysis">Secondary Analysis</option>
                  <option value="self_reported">Self-Reported</option>
                </select>
                <input
                  type="text"
                  aria-label="Origin description"
                  class="text-input"
                  style="width: 190px;"
                  placeholder="Origin (e.g., QB P&L export)"
                  value=${uploadOriginDescription}
                  disabled=${matterBusy || !selectedMatter}
                  onInput=${(e) => setUploadOriginDescription(e.target.value)}
                />
                <label class="btn btn-primary file-picker-label">
                  <${Icon} name="plus" size=${13} />
                  <span>${matterBusy ? 'Indexing…' : 'Upload / Replace File'}</span>
                  <input
                    type="file"
                    accept=".pdf,.docx,.xlsx,.xlsm,.csv,.md,.txt"
                    disabled=${matterBusy || !selectedMatter}
                    style="display: none;"
                    onChange=${handleMatterUpload}
                  />
                </label>
                <button
                  type="button"
                  class="btn btn-compact"
                  disabled=${matterBusy || !selectedMatter}
                  onClick=${handleReindexMatter}
                >
                  Re-Index All
                </button>
              </div>
            </div>

            ${matterProgress.length > 0 && html`
              <div class="stage-progress-box">
                ${matterProgress.map(
                  (ev, idx) => html`
                    <div key=${idx}>
                      <span class="font-mono-data" style="color: var(--color-accent-primary);">[${ev.stage}]</span> ${ev.message}
                    </div>
                  `
                )}
              </div>
            `}

            <div class="corpus-table-wrap">
              <table class="corpus-table">
                <thead>
                  <tr>
                    <th>Filename</th>
                    <th>Type</th>
                    <th>Size</th>
                    <th>Indexed Coordinates</th>
                    <th>Source & Origin</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  ${(!matterFilesData?.files || matterFilesData.files.length === 0) && html`
                    <tr>
                      <td colspan="6" style="text-align: center; color: var(--color-text-muted); padding: 20px;">
                        No files uploaded into '${selectedMatter}' yet.
                      </td>
                    </tr>
                  `}
                  ${(matterFilesData?.files || []).map(
                    (f) => {
                      const draft = rowMetaDrafts[f.filename] || {
                        reliability_tier: f.reliability_tier || 'primary_record',
                        origin_description: f.origin_description || '',
                      };
                      const isEditingRow = editingMetaFile === f.filename;
                      const tierMeta = formatReliabilityTier(f.reliability_tier || 'primary_record');
                      return html`
                        <tr key=${f.filename}>
                          <td>
                            <a
                              href=${`/api/matters/${encodeURIComponent(selectedMatter)}/files/${encodeURIComponent(f.filename)}/raw`}
                              target="_blank"
                              rel="noopener noreferrer"
                              class="file-table-link"
                              title="Open or download original file in new tab"
                            >
                              ${f.filename} ↗
                            </a>
                          </td>
                          <td class="font-mono-data">${f.suffix || '—'}</td>
                          <td class="font-mono-data">${formatBytes(f.size_bytes)}</td>
                          <td class="font-mono-data">
                            ${f.blocks != null
                              ? `${f.blocks} blocks`
                              : f.cells != null
                              ? `${f.cells} cells`
                              : f.indexed_artifact || 'Pending'}
                          </td>
                          <td>
                            ${isEditingRow ? html`
                              <div class="meta-inline-row">
                                <select
                                  aria-label="Reliability tier for ${f.filename}"
                                  class="select-control select-compact"
                                  value=${draft.reliability_tier}
                                  disabled=${matterBusy || savingMetaFile === f.filename}
                                  onChange=${(e) =>
                                    setRowMetaDrafts((prev) => ({
                                      ...prev,
                                      [f.filename]: { ...draft, reliability_tier: e.target.value },
                                    }))
                                  }
                                >
                                  <option value="primary_record">Primary Record</option>
                                  <option value="secondary_analysis">Secondary Analysis</option>
                                  <option value="self_reported">Self-Reported</option>
                                </select>
                                <input
                                  type="text"
                                  aria-label="Origin description for ${f.filename}"
                                  class="text-input input-compact"
                                  placeholder="Origin note…"
                                  value=${draft.origin_description}
                                  disabled=${matterBusy || savingMetaFile === f.filename}
                                  onInput=${(e) =>
                                    setRowMetaDrafts((prev) => ({
                                      ...prev,
                                      [f.filename]: { ...draft, origin_description: e.target.value },
                                    }))
                                  }
                                />
                                <button
                                  type="button"
                                  class="btn btn-compact btn-primary"
                                  disabled=${savingMetaFile === f.filename}
                                  onClick=${() => handleSaveFileMetadata(f.filename)}
                                >
                                  ${savingMetaFile === f.filename ? 'Saving…' : 'Save'}
                                </button>
                                <button
                                  type="button"
                                  class="btn btn-compact"
                                  disabled=${savingMetaFile === f.filename}
                                  onClick=${() => {
                                    setRowMetaDrafts((prev) => ({
                                      ...prev,
                                      [f.filename]: {
                                        reliability_tier: f.reliability_tier || 'primary_record',
                                        origin_description: f.origin_description || '',
                                      },
                                    }));
                                    setEditingMetaFile(null);
                                  }}
                                >
                                  Cancel
                                </button>
                              </div>
                            ` : html`
                              <div class="meta-inline-row">
                                ${tierMeta && html`
                                  <span class="reliability-pill ${tierMeta.cls}">${tierMeta.label}</span>
                                `}
                                ${f.origin_description && html`
                                  <span class="provenance-origin-text" title=${f.origin_description}>
                                    ${f.origin_description}
                                  </span>
                                `}
                                <button
                                  type="button"
                                  class="btn-link"
                                  onClick=${() => setEditingMetaFile(f.filename)}
                                >
                                  Edit
                                </button>
                              </div>
                            `}
                          </td>
                          <td>
                            <button
                              type="button"
                              class="btn btn-compact btn-danger-ghost"
                              aria-label="Delete ${f.filename}"
                              disabled=${matterBusy}
                              onClick=${() => handleDeleteMatterFile(f.filename)}
                            >
                              <${Icon} name="trash" size=${12} />
                            </button>
                          </td>
                        </tr>
                      `;
                    }
                  )}
                </tbody>
              </table>
            </div>
          </div>
        `}
      </div>
    </dialog>
  `;
}

/**
 * Step-Through Checkpoint Review dialog for inspecting/editing Stage 1 OutlinePlan
 * and Stage 2 VerifiedFactLedger before continuing Stages 3 & 4.
 */
function CheckpointReviewModal({
  dialogRef,
  run,
  canonicalAuths,
  onRunUpdated,
  onBundleCreated,
  onOpenMatterFiles,
}) {
  const [editedPlan, setEditedPlan] = useState(null);
  const [resuming, setResuming] = useState(false);
  const [progressEvents, setProgressEvents] = useState([]);
  const [errorMsg, setErrorMsg] = useState(null);
  const [addAuthBySec, setAddAuthBySec] = useState({});
  const [blueprintSaveOpen, setBlueprintSaveOpen] = useState(false);
  const [blueprintTitle, setBlueprintTitle] = useState('');
  const [blueprintDomain, setBlueprintDomain] = useState('general');
  const [savingBlueprint, setSavingBlueprint] = useState(false);
  const [blueprintSaveMsg, setBlueprintSaveMsg] = useState(null);

  useEffect(() => {
    if (run?.outline_plan) {
      setEditedPlan(JSON.parse(JSON.stringify(run.outline_plan)));
      setBlueprintTitle(run.outline_plan.document_title || '');
      const inferredDomain =
        run.canonical_domains?.[0] ||
        run.outline_plan.sections?.[0]?.governing_authorities?.[0]?.domain ||
        'general';
      setBlueprintDomain(inferredDomain);
    } else {
      setEditedPlan(null);
      setBlueprintTitle('');
      setBlueprintDomain('general');
    }
    setBlueprintSaveOpen(false);
    setBlueprintSaveMsg(null);
    setErrorMsg(run?.error || null);
    setProgressEvents([]);
  }, [run?.run_id, run?.status, run?.updated_at]);

  if (!run) {
    return html`<dialog ref=${dialogRef} class="compiler-dialog is-wide"></dialog>`;
  }

  const isStage1 = run.status === 'awaiting_stage1_approval';
  const isStage2 = run.status === 'awaiting_stage2_approval';

  const handleSaveAsBlueprint = async () => {
    if (!editedPlan) return;
    setSavingBlueprint(true);
    setErrorMsg(null);
    setBlueprintSaveMsg(null);
    try {
      const domainVal = blueprintDomain.trim() || 'general';
      const titleVal = blueprintTitle.trim() || editedPlan.document_title || 'Saved Blueprint';
      const res = await fetch('/api/blueprints', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: titleVal,
          domain: domainVal,
          default_domains: run.canonical_domains || (domainVal !== 'general' ? [domainVal] : []),
          outline_plan: editedPlan,
          source_run_id: run.run_id,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to save blueprint');
      }
      const saved = await res.json();
      setBlueprintSaveMsg(`Saved template “${saved.title}” (${saved.blueprint_id})`);
      setBlueprintSaveOpen(false);
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setSavingBlueprint(false);
    }
  };

  const updateSectionField = (idx, field, value) => {
    setEditedPlan((prev) => {
      if (!prev) return prev;
      const nextSections = [...prev.sections];
      nextSections[idx] = { ...nextSections[idx], [field]: value };
      return { ...prev, sections: nextSections };
    });
  };

  const handleRemoveAuth = (secIdx, authId) => {
    setEditedPlan((prev) => {
      if (!prev) return prev;
      const nextSections = [...prev.sections];
      const curr = nextSections[secIdx];
      nextSections[secIdx] = {
        ...curr,
        governing_authorities: (curr.governing_authorities || []).filter(
          (a) => a.auth_id !== authId
        ),
      };
      return { ...prev, sections: nextSections };
    });
  };

  const handleAddAuth = (secIdx, authId) => {
    if (!authId) return;
    const match = (canonicalAuths || []).find((a) => a.auth_id === authId);
    if (!match) return;
    setEditedPlan((prev) => {
      if (!prev) return prev;
      const nextSections = [...prev.sections];
      const curr = nextSections[secIdx];
      const existing = curr.governing_authorities || [];
      if (existing.some((a) => a.auth_id === match.auth_id)) return prev;
      nextSections[secIdx] = {
        ...curr,
        governing_authorities: [...existing, match],
      };
      return { ...prev, sections: nextSections };
    });
  };

  const handleAddSection = () => {
    setEditedPlan((prev) => {
      if (!prev) return prev;
      const num = prev.sections.length + 1;
      const newSec = {
        section_id: `sec_${String(num).padStart(2, '0')}_${Date.now().toString(36).slice(-4)}`,
        section_title: `Section ${num}`,
        stated_intention: 'Analyze this issue using indexed project evidence.',
        routing_rationale: 'Added manually during Stage 1 review.',
        governing_authorities: [],
        required_fact_queries: ['What facts establish this point?'],
      };
      return { ...prev, sections: [...prev.sections, newSec] };
    });
  };

  const handleRemoveSection = (idx) => {
    setEditedPlan((prev) => {
      if (!prev || prev.sections.length <= 1) return prev;
      return { ...prev, sections: prev.sections.filter((_, i) => i !== idx) };
    });
  };

  const handleResume = async ({
    passOutline = false,
    reharvestIds = null,
    checkpointMode = null,
  } = {}) => {
    setResuming(true);
    setErrorMsg(null);
    setProgressEvents([{ stage: 'resume', message: 'Resuming persisted pipeline run…' }]);
    try {
      const { bundle: newBundle, run: updatedRun } = await resumeRunStream({
        runId: run.run_id,
        outlinePlan: passOutline ? editedPlan : null,
        reharvestSectionIds: reharvestIds,
        checkpointMode,
        onProgress: (ev) => setProgressEvents((prev) => [...prev, ev]),
        onCheckpoint: (ckptRun) => onRunUpdated?.(ckptRun),
      });
      if (updatedRun) {
        onRunUpdated?.(updatedRun);
      }
      if (newBundle) {
        await onBundleCreated?.(newBundle);
        dialogRef.current?.close();
      }
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setResuming(false);
    }
  };

  const ledgers = run.ledgers || {};

  return html`
    <dialog
      ref=${dialogRef}
      class="compiler-dialog is-wide"
      closedby="any"
      aria-labelledby="checkpoint-dialog-title"
    >
      <div class="dialog-inner">
        <div class="modal-header-row">
          <div>
            <h2 id="checkpoint-dialog-title" class="card-heading" style="font-size: 18px;">
              ${isStage1
                ? 'Stage 1 Checkpoint: Review & Edit Outline'
                : isStage2
                ? 'Stage 2 Checkpoint: Inspect Harvested Facts & Gaps'
                : `Pipeline Run · ${formatRunStatusLabel(run.status)}`}
            </h2>
            <div class="provenance-caption">
              Run <code class="font-mono-data">${run.run_id}</code> · Matter <code class="font-mono-data">${run.matter_id}</code>
            </div>
          </div>
          <form method="dialog">
            <button type="submit" class="btn btn-icon-only" aria-label="Close checkpoint dialog" disabled=${resuming}>
              <${Icon} name="close" />
            </button>
          </form>
        </div>

        ${isStage1 && editedPlan && html`
          <div class="checkpoint-sections-list">
            <div class="form-field">
              <label for="ckpt-doc-title" class="control-label">Document Title</label>
              <input
                id="ckpt-doc-title"
                type="text"
                class="text-input"
                value=${editedPlan.document_title}
                onInput=${(e) => setEditedPlan({ ...editedPlan, document_title: e.target.value })}
              />
            </div>
            <div class="form-field">
              <label for="ckpt-summary-intent" class="control-label">Executive Summary Intent</label>
              <textarea
                id="ckpt-summary-intent"
                class="comment-textarea"
                style="min-block-size: 56px;"
                value=${editedPlan.executive_summary_intent}
                onInput=${(e) =>
                  setEditedPlan({ ...editedPlan, executive_summary_intent: e.target.value })
                }
              ></textarea>
            </div>

            ${editedPlan.sections.map(
              (sec, idx) => html`
                <div key=${sec.section_id} class="checkpoint-section-card">
                  <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                    <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                      ${sec.section_id}
                    </span>
                    ${editedPlan.sections.length > 1 && html`
                      <button
                        type="button"
                        class="btn btn-compact btn-danger-ghost"
                        onClick=${() => handleRemoveSection(idx)}
                      >
                        Remove Section
                      </button>
                    `}
                  </div>

                  <div class="form-field">
                    <label class="control-label">Section Title</label>
                    <input
                      type="text"
                      class="text-input"
                      value=${sec.section_title}
                      onInput=${(e) => updateSectionField(idx, 'section_title', e.target.value)}
                    />
                  </div>

                  <div class="form-field">
                    <label class="control-label">Stated Analytical Intention</label>
                    <textarea
                      class="comment-textarea"
                      style="min-block-size: 48px;"
                      value=${sec.stated_intention}
                      onInput=${(e) => updateSectionField(idx, 'stated_intention', e.target.value)}
                    ></textarea>
                  </div>

                  <div class="form-field">
                    <label class="control-label">Required Fact Queries (one per line)</label>
                    <textarea
                      class="comment-textarea"
                      style="min-block-size: 56px;"
                      value=${(sec.required_fact_queries || []).join('\n')}
                      onInput=${(e) =>
                        updateSectionField(
                          idx,
                          'required_fact_queries',
                          e.target.value
                            .split('\n')
                            .map((line) => line.trim())
                            .filter(Boolean)
                        )
                      }
                    ></textarea>
                  </div>

                  <div class="form-field">
                    <span class="control-label">Governing Canonical Authorities</span>
                    <div class="auth-pill-row">
                      ${(sec.governing_authorities || []).length === 0 && html`
                        <span class="provenance-caption">Evidence & commonsense reasoning only</span>
                      `}
                      ${(sec.governing_authorities || []).map(
                        (a) => html`
                          <span key=${a.auth_id} class="auth-pill">
                            <span class="font-mono-data">${a.auth_id}</span>
                            <span>${a.title}</span>
                            <button
                              type="button"
                              class="auth-pill-remove"
                              aria-label="Remove ${a.auth_id}"
                              onClick=${() => handleRemoveAuth(idx, a.auth_id)}
                            >
                              <${Icon} name="close" size=${11} />
                            </button>
                          </span>
                        `
                      )}
                    </div>
                    ${(canonicalAuths || []).length > 0 && html`
                      <div style="display: flex; gap: 6px; margin-top: 4px;">
                        <select
                          class="select-control"
                          value=${addAuthBySec[sec.section_id] || ''}
                          onChange=${(e) =>
                            setAddAuthBySec((prev) => ({
                              ...prev,
                              [sec.section_id]: e.target.value,
                            }))
                          }
                        >
                          <option value="">Attach canonical [AUTH:...] rule…</option>
                          ${canonicalAuths.map(
                            (ca) => html`
                              <option key=${ca.auth_id} value=${ca.auth_id}>
                                [${ca.auth_id}] ${ca.title}
                              </option>
                            `
                          )}
                        </select>
                        <button
                          type="button"
                          class="btn btn-compact"
                          onClick=${() => {
                            handleAddAuth(idx, addAuthBySec[sec.section_id]);
                            setAddAuthBySec((prev) => ({ ...prev, [sec.section_id]: '' }));
                          }}
                        >
                          Add Rule
                        </button>
                      </div>
                    `}
                  </div>
                </div>
              `
            )}

            <div>
              <button type="button" class="btn btn-compact" onClick=${handleAddSection}>
                <${Icon} name="plus" size=${12} />
                <span>Add Section</span>
              </button>
            </div>
          </div>
        `}

        ${isStage2 && run.outline_plan && html`
          <div class="checkpoint-sections-list">
            ${run.outline_plan.sections.map((sec) => {
              const ledger = ledgers[sec.section_id] || {};
              const facts = ledger.verified_facts || [];
              const gaps = ledger.unresolved_gaps || [];
              return html`
                <div key=${sec.section_id} class="checkpoint-section-card">
                  <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;">
                    <div>
                      <div style="font-weight: 600; color: var(--color-text-primary);">${sec.section_title}</div>
                      <div class="provenance-caption">
                        <span class="font-mono-data">${facts.length}</span> verified facts ·
                        <span class="font-mono-data">${gaps.length}</span> unresolved gaps
                      </div>
                    </div>
                    <button
                      type="button"
                      class="btn btn-compact"
                      disabled=${resuming}
                      onClick=${() => handleResume({ reharvestIds: [sec.section_id] })}
                    >
                      Re-Harvest Section
                    </button>
                  </div>

                  ${ledger.harvest_summary && html`
                    <div class="provenance-caption">${ledger.harvest_summary}</div>
                  `}

                  ${facts.map(
                    (f) => html`
                      <div key=${f.fact_id} class="fact-review-row">
                        <div style="display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap;">
                          <strong>${f.title}</strong>
                          <span class="font-mono-data" style="font-size: 11px; color: var(--color-accent-primary);">
                            ${f.locator?.file_name || ''} · ${f.locator?.locator_key || f.locator?.cell_range || ''}
                          </span>
                        </div>
                        <div style="color: var(--color-text-body);">${f.quote}</div>
                      </div>
                    `
                  )}

                  ${gaps.map(
                    (g, gi) => html`
                      <div key=${gi} class="gap-callout">
                        <strong>Unresolved Gap (${g.recommended_handling || 'assumption'}): ${g.query}</strong>
                        <span>${g.rationale}</span>
                      </div>
                    `
                  )}
                </div>
              `;
            })}
          </div>
        `}

        ${(progressEvents.length > 0 || (run.events || []).length > 0) && html`
          <details open=${progressEvents.length > 0}>
            <summary class="control-label" style="cursor: pointer;">
              Execution Log (${progressEvents.length > 0 ? progressEvents.length : run.events.length} events)
            </summary>
            <div class="stage-progress-box" style="margin-top: 6px;">
              ${(progressEvents.length > 0 ? progressEvents : run.events).map(
                (ev, idx) => html`
                  <div key=${idx}>
                    <span class="font-mono-data" style="color: var(--color-accent-primary);">[${ev.stage}]</span> ${ev.message}
                  </div>
                `
              )}
            </div>
          </details>
        `}

        ${errorMsg && html`
          <pre
            tabindex="0"
            class="formula-box"
            style="border-color: var(--color-danger); color: var(--color-danger); background-color: var(--color-danger-subtle);"
          ><code>${errorMsg}</code></pre>
        `}

        ${blueprintSaveMsg && html`
          <div class="provenance-caption" style="color: var(--color-emerald-accent); font-weight: 600;">
            ${blueprintSaveMsg}
          </div>
        `}

        ${isStage1 && editedPlan && blueprintSaveOpen && html`
          <div class="blueprint-save-bar">
            <input
              type="text"
              aria-label="Blueprint title"
              class="text-input input-compact"
              style="flex: 2; min-width: 180px;"
              placeholder="Blueprint template title…"
              value=${blueprintTitle}
              disabled=${savingBlueprint}
              onInput=${(e) => setBlueprintTitle(e.target.value)}
            />
            <input
              type="text"
              aria-label="Blueprint domain"
              class="text-input input-compact"
              style="flex: 1; min-width: 110px;"
              placeholder="Domain (e.g. bankruptcy)"
              value=${blueprintDomain}
              disabled=${savingBlueprint}
              onInput=${(e) => setBlueprintDomain(e.target.value)}
            />
            <button
              type="button"
              class="btn btn-compact btn-primary"
              disabled=${savingBlueprint}
              onClick=${handleSaveAsBlueprint}
            >
              ${savingBlueprint ? 'Saving…' : 'Save Template'}
            </button>
            <button
              type="button"
              class="btn btn-compact"
              disabled=${savingBlueprint}
              onClick=${() => setBlueprintSaveOpen(false)}
            >
              Cancel
            </button>
          </div>
        `}

        <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;">
          <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            ${isStage1 && editedPlan && html`
              <button
                type="button"
                class="btn"
                disabled=${resuming || savingBlueprint}
                onClick=${() => setBlueprintSaveOpen((prev) => !prev)}
              >
                <${Icon} name="source" size=${13} />
                <span>Save as Reusable Template…</span>
              </button>
            `}
            ${isStage2 && html`
              <button
                type="button"
                class="btn"
                disabled=${resuming}
                onClick=${() => onOpenMatterFiles?.(run.matter_id)}
              >
                <${Icon} name="folder" size=${13} />
                <span>Upload Missing Matter File…</span>
              </button>
            `}
          </div>
          <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            ${isStage1 && html`
              <button
                type="button"
                class="btn"
                disabled=${resuming}
                onClick=${() =>
                  handleResume({ passOutline: true, checkpointMode: false })
                }
              >
                ${resuming ? 'Running…' : 'Approve & Finish Automatically'}
              </button>
              <button
                type="button"
                class="btn btn-primary"
                disabled=${resuming}
                onClick=${() =>
                  handleResume({ passOutline: true, checkpointMode: true })
                }
              >
                ${resuming ? 'Harvesting Facts…' : 'Approve & Harvest Facts'}
              </button>
            `}
            ${isStage2 && html`
              <button
                type="button"
                class="btn btn-primary"
                disabled=${resuming}
                onClick=${() => handleResume({ checkpointMode: true })}
              >
                ${resuming ? 'Drafting & Auditing Memo…' : 'Approve & Draft Memo'}
              </button>
            `}
            ${!isStage1 && !isStage2 && html`
              <button
                type="button"
                class="btn btn-primary"
                disabled=${resuming}
                onClick=${() => handleResume({})}
              >
                ${resuming ? 'Resuming…' : 'Resume Run'}
              </button>
            `}
          </div>
        </div>
      </div>
    </dialog>
  `;
}

/**
 * Native <dialog> for starting a New Question / Brief and browsing persisted runs.
 */
function AskPipelineDialog({
  dialogRef,
  activeMatterHint,
  onBundleCreated,
  onCheckpointPaused,
  onOpenCorpusManager,
  onOpenRun,
}) {
  const [matters, setMatters] = useState([]);
  const [selectedMatter, setSelectedMatter] = useState(activeMatterHint || 'legal_motion_1332');
  const [question, setQuestion] = useState('');
  const [bundleSlug, setBundleSlug] = useState('');
  const [checkpointMode, setCheckpointMode] = useState(false);
  const [canonicalDomainsList, setCanonicalDomainsList] = useState([]);
  const [autoSelectDomains, setAutoSelectDomains] = useState(true);
  const [selectedDomains, setSelectedDomains] = useState([]);
  const [blueprintsList, setBlueprintsList] = useState([]);
  const [selectedBlueprintId, setSelectedBlueprintId] = useState('');
  const [blueprintMode, setBlueprintMode] = useState('guided');
  const [activeAskTab, setActiveAskTab] = useState('compose');
  const [runsList, setRunsList] = useState([]);
  const [progressEvents, setProgressEvents] = useState([]);
  const [running, setRunning] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  const refreshMatters = useCallback(async () => {
    const res = await fetch('/api/matters');
    if (res.ok) {
      const data = await res.json();
      const list = data.matters || [];
      setMatters(list);
      if (list.length > 0 && !list.some((m) => m.matter_id === selectedMatter)) {
        setSelectedMatter(list[0].matter_id);
      }
    }
  }, [selectedMatter]);

  const refreshAskOptions = useCallback(async () => {
    try {
      const [canRes, bpRes] = await Promise.all([
        fetch('/api/canonical'),
        fetch('/api/blueprints'),
      ]);
      if (canRes.ok) {
        const canData = await canRes.json();
        setCanonicalDomainsList(canData.canonical_domains || []);
      }
      if (bpRes.ok) {
        const bpData = await bpRes.json();
        setBlueprintsList(Array.isArray(bpData) ? bpData : []);
      }
    } catch {
      // Non-fatal: pipeline defaults to auto domain selection
    }
  }, []);

  const refreshRuns = useCallback(async (matterId) => {
    if (!matterId) return;
    const res = await fetch(`/api/matters/${matterId}/runs`);
    if (res.ok) {
      setRunsList(await res.json());
    }
  }, []);

  useEffect(() => {
    refreshMatters();
    refreshAskOptions();
  }, [refreshMatters, refreshAskOptions]);

  useEffect(() => {
    const dlg = dialogRef?.current;
    if (!dlg || typeof MutationObserver === 'undefined') return undefined;
    const observer = new MutationObserver(() => {
      if (dlg.hasAttribute('open')) {
        refreshMatters();
        refreshAskOptions();
      }
    });
    observer.observe(dlg, { attributes: true, attributeFilter: ['open'] });
    return () => observer.disconnect();
  }, [dialogRef, refreshMatters, refreshAskOptions]);

  useEffect(() => {
    if (activeMatterHint && matters.some((m) => m.matter_id === activeMatterHint)) {
      setSelectedMatter(activeMatterHint);
    }
  }, [activeMatterHint, matters]);

  useEffect(() => {
    if (selectedMatter) {
      refreshRuns(selectedMatter);
    }
  }, [selectedMatter, refreshRuns]);

  const activeMatterObj = matters.find((m) => m.matter_id === selectedMatter);

  const handleSelectBlueprint = (bpId) => {
    setSelectedBlueprintId(bpId);
    if (!bpId) return;
    const bp = blueprintsList.find((item) => item.blueprint_id === bpId);
    if (bp?.default_domains && bp.default_domains.length > 0) {
      const availSet = new Set(canonicalDomainsList.map((d) => d.domain));
      const matched = bp.default_domains.filter((d) => availSet.size === 0 || availSet.has(d));
      if (matched.length > 0) {
        setAutoSelectDomains(false);
        setSelectedDomains(matched);
      }
    }
  };

  const handleToggleDomain = (domainName) => {
    setAutoSelectDomains(false);
    setSelectedDomains((prev) =>
      prev.includes(domainName)
        ? prev.filter((d) => d !== domainName)
        : [...prev, domainName]
    );
  };

  const handleRunAsk = async (e) => {
    e.preventDefault();
    if (!question.trim() || !selectedMatter) return;
    setRunning(true);
    setErrorMsg(null);
    setProgressEvents([{ stage: 'init', message: 'Starting analysis pipeline...' }]);

    try {
      const { bundle: newBundle, run: pausedRun } = await streamAskPipeline({
        matterId: selectedMatter,
        question,
        bundleId: bundleSlug.trim() || null,
        checkpointMode,
        canonicalDomains: autoSelectDomains ? null : selectedDomains,
        blueprintId: selectedBlueprintId || null,
        blueprintMode: selectedBlueprintId ? blueprintMode : 'none',
        onProgress: (ev) => setProgressEvents((prev) => [...prev, ev]),
      });
      await refreshRuns(selectedMatter);
      if (newBundle) {
        await onBundleCreated(newBundle);
        setQuestion('');
        setBundleSlug('');
        dialogRef.current?.close();
      } else if (pausedRun) {
        dialogRef.current?.close();
        onCheckpointPaused?.(pausedRun);
      }
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setRunning(false);
    }
  };

  const pillClassFor = (status) => {
    if (status === 'awaiting_stage1_approval' || status === 'awaiting_stage2_approval') return 'is-paused';
    if (status === 'running') return 'is-running';
    if (status === 'completed') return 'is-completed';
    if (status === 'failed') return 'is-failed';
    return '';
  };

  return html`
    <dialog
      ref=${dialogRef}
      class="compiler-dialog"
      closedby="any"
      aria-labelledby="ask-dialog-title"
    >
      <div class="dialog-inner">
        <div class="modal-header-row">
          <h2 id="ask-dialog-title" class="card-heading" style="font-size: 18px;">
            New Analytical Brief
          </h2>
          <form method="dialog">
            <button type="submit" class="btn btn-icon-only" aria-label="Close dialog" disabled=${running}>
              <${Icon} name="close" />
            </button>
          </form>
        </div>

        ${runsList.length > 0 && html`
          <div class="modal-tabs" role="tablist" aria-label="Brief views">
            <button
              type="button"
              role="tab"
              aria-selected=${activeAskTab === 'compose'}
              class="modal-tab-btn ${activeAskTab === 'compose' ? 'is-active' : ''}"
              onClick=${() => setActiveAskTab('compose')}
            >
              New Brief
            </button>
            <button
              type="button"
              role="tab"
              aria-selected=${activeAskTab === 'history'}
              class="modal-tab-btn ${activeAskTab === 'history' ? 'is-active' : ''}"
              onClick=${() => setActiveAskTab('history')}
            >
              Run History (${runsList.length})
            </button>
          </div>
        `}

        ${(activeAskTab === 'compose' || runsList.length === 0) && html`
          <form onSubmit=${handleRunAsk} style="display: flex; flex-direction: column; gap: 12px;">
            <div class="form-field">
              <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                <label for="matter-select" class="control-label">Matter Workspace</label>
                <button
                  type="button"
                  class="btn btn-compact"
                  onClick=${() => onOpenCorpusManager?.('matter', selectedMatter)}
                >
                  <${Icon} name="folder" size=${12} />
                  <span>Manage Files & Rules…</span>
                </button>
              </div>
              <select
                id="matter-select"
                class="select-control"
                value=${selectedMatter}
                onChange=${(e) => setSelectedMatter(e.target.value)}
              >
                ${matters.map(
                  (m) => html`
                    <option key=${m.matter_id} value=${m.matter_id}>
                      ${m.matter_id} (${m.raw_files?.length || 0} files${m.indexed ? ' · indexed' : ''})
                    </option>
                  `
                )}
              </select>
              ${activeMatterObj && (activeMatterObj.raw_files?.length || 0) > 0 && html`
                <div class="provenance-caption">
                  Files: ${activeMatterObj.raw_files.join(', ')}
                </div>
              `}
              ${activeMatterObj && (activeMatterObj.raw_files?.length || 0) === 0 && html`
                <div class="provenance-caption" style="color: var(--color-warning); display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                  <span>No raw source files uploaded yet in this matter.</span>
                  <button
                    type="button"
                    class="btn-link"
                    onClick=${() => onOpenCorpusManager?.('matter', selectedMatter)}
                  >
                    Upload Matter Files…
                  </button>
                </div>
              `}
            </div>

            <div class="form-field">
              <label for="ask-question-input" class="control-label">Question or Brief Prompt</label>
              <textarea
                id="ask-question-input"
                class="comment-textarea"
                style="min-block-size: 84px;"
                placeholder="E.g., Evaluate whether complete diversity and the $75,000 threshold are satisfied under 28 U.S.C. § 1332..."
                value=${question}
                onInput=${(e) => setQuestion(e.target.value)}
                required
              ></textarea>
            </div>

            <details
              class="advanced-options-disclosure"
              open=${Boolean(selectedBlueprintId || !autoSelectDomains || bundleSlug || checkpointMode)}
            >
              <summary class="advanced-options-summary">
                <span>Advanced Pipeline Options</span>
                <span class="provenance-caption">Template, rule domains, checkpoints</span>
              </summary>
              <div class="advanced-options-body">
                <div class="form-field">
                  <label for="ask-blueprint-select" class="control-label">
                    Document Template / Blueprint
                  </label>
                  <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                    <select
                      id="ask-blueprint-select"
                      class="select-control"
                      style="flex: 2; min-width: 210px;"
                      value=${selectedBlueprintId}
                      disabled=${running}
                      onChange=${(e) => handleSelectBlueprint(e.target.value)}
                    >
                      <option value="">No Template — Free Iterate</option>
                      ${blueprintsList.map(
                        (bp) => html`
                          <option key=${bp.blueprint_id} value=${bp.blueprint_id}>
                            ${bp.title} (${bp.domain} · ${bp.sections?.length || 0} sections)
                          </option>
                        `
                      )}
                    </select>
                    <select
                      aria-label="Blueprint constraint mode"
                      class="select-control"
                      style="flex: 1; min-width: 150px;"
                      value=${selectedBlueprintId ? blueprintMode : 'none'}
                      disabled=${running || !selectedBlueprintId}
                      onChange=${(e) => setBlueprintMode(e.target.value)}
                    >
                      ${!selectedBlueprintId && html`<option value="none">Mode: Free Iterate</option>`}
                      <option value="guided">Guided (adapt to facts)</option>
                      <option value="strict">Strict (lock sections)</option>
                    </select>
                  </div>
                  ${selectedBlueprintId && html`
                    <div class="provenance-caption">
                      ${blueprintsList.find((b) => b.blueprint_id === selectedBlueprintId)?.description || ''}
                    </div>
                  `}
                </div>

                <div class="form-field">
                  <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                    <span class="control-label">Canonical Rule Domains</span>
                    <label class="checkbox-row" style="font-size: 12px;">
                      <input
                        type="checkbox"
                        checked=${autoSelectDomains}
                        disabled=${running}
                        onChange=${(e) => {
                          const checked = Boolean(e.target.checked);
                          setAutoSelectDomains(checked);
                          if (!checked && selectedDomains.length === 0) {
                            setSelectedDomains(canonicalDomainsList.map((d) => d.domain));
                          }
                        }}
                      />
                      <span>Auto-select from corpus</span>
                    </label>
                  </div>
                  ${canonicalDomainsList.length > 0 ? html`
                    <div class="domain-chip-group">
                      ${canonicalDomainsList.map((d) => {
                        const isChecked = autoSelectDomains
                          ? false
                          : selectedDomains.includes(d.domain);
                        return html`
                          <label
                            key=${d.domain}
                            class="domain-chip ${isChecked ? 'is-selected' : ''} ${autoSelectDomains ? 'is-auto' : ''}"
                            title=${(d.titles || []).join(', ')}
                          >
                            <input
                              type="checkbox"
                              checked=${isChecked}
                              disabled=${running}
                              onChange=${() => handleToggleDomain(d.domain)}
                            />
                            <span>${d.domain}</span>
                            <span class="font-mono-data" style="font-size: 10.5px; color: var(--color-text-muted);">
                              ${d.document_count}
                            </span>
                          </label>
                        `;
                      })}
                    </div>
                  ` : html`
                    <div class="provenance-caption">No indexed canonical domain packs yet (auto-select active).</div>
                  `}
                </div>

                <div class="form-field">
                  <label for="ask-bundle-slug" class="control-label">Optional Output Identifier</label>
                  <input
                    id="ask-bundle-slug"
                    type="text"
                    class="text-input"
                    placeholder="Auto-generated if left blank"
                    value=${bundleSlug}
                    onInput=${(e) => setBundleSlug(e.target.value)}
                  />
                </div>

                <label class="checkbox-row">
                  <input
                    type="checkbox"
                    checked=${checkpointMode}
                    onChange=${(e) => setCheckpointMode(Boolean(e.target.checked))}
                  />
                  <span>Step-through checkpoints (pause after Stage 1 outline & Stage 2 fact harvest)</span>
                </label>
              </div>
            </details>

            ${progressEvents.length > 0 && html`
              <div class="stage-progress-box">
                ${progressEvents.map(
                  (ev, idx) => html`
                    <div key=${idx}>
                      <span class="font-mono-data" style="color: var(--color-accent-primary);">[${ev.stage}]</span> ${ev.message}
                    </div>
                  `
                )}
              </div>
            `}

            ${errorMsg && html`
              <pre
                tabindex="0"
                class="formula-box"
                style="border-color: var(--color-danger); color: var(--color-danger); background-color: var(--color-danger-subtle);"
              ><code>${errorMsg}</code></pre>
            `}

            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button type="submit" class="btn btn-primary" disabled=${running}>
                ${running ? 'Running Pipeline…' : checkpointMode ? 'Start Stage 1 Outline' : 'Generate Brief'}
              </button>
            </div>
          </form>
        `}

        ${activeAskTab === 'history' && runsList.length > 0 && html`
          <div class="form-field">
            <span class="control-label">Recent Runs in ${selectedMatter}</span>
            <div class="runs-list">
              ${runsList.slice(0, 8).map(
                (r) => html`
                  <div key=${r.run_id} class="run-row">
                    <div style="min-width: 0; flex: 1;">
                      <div style="display: flex; align-items: center; gap: 8px;">
                        <span class="run-status-pill ${pillClassFor(r.status)}">
                          ${formatRunStatusLabel(r.status)}
                        </span>
                        <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                          ${r.run_id}
                        </span>
                      </div>
                      <div style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 2px;">
                        ${r.question}
                      </div>
                    </div>
                    <button
                      type="button"
                      class="btn btn-compact"
                      onClick=${() => {
                        dialogRef.current?.close();
                        onOpenRun?.(r);
                      }}
                    >
                      ${r.status === 'completed' ? 'Open Bundle' : 'Inspect / Resume'}
                    </button>
                  </div>
                `
              )}
            </div>
          </div>
        `}
      </div>
    </dialog>
  `;
}

/**
 * Main Application Component.
 */
function App() {
  const [bundlesList, setBundlesList] = useState([]);
  const [mattersList, setMattersList] = useState([]);
  const [canonicalAuths, setCanonicalAuths] = useState([]);
  const [currentBundleId, setCurrentBundleId] = useState('legal_motion_1332');
  const [bundle, setBundle] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeRun, setActiveRun] = useState(null);
  const [activeRunLiveMsg, setActiveRunLiveMsg] = useState(null);
  const [corpusTabHint, setCorpusTabHint] = useState('canonical');
  const [corpusMatterHint, setCorpusMatterHint] = useState(null);

  // Progressive 3-column canvas state
  const [pinnedClaimId, setPinnedClaimId] = useState(null);
  const [expandedLevel2Ids, setExpandedLevel2Ids] = useState([]);
  const [hoveredRef, setHoveredRef] = useState(null);
  const [hoveredLinkId, setHoveredLinkId] = useState(null);
  const [activeLinkPopover, setActiveLinkPopover] = useState(null);
  const [auditFilter, setAuditFilter] = useState('all');
  const [inspectorNode, setInspectorNode] = useState(null);

  // Secondary tools / progressive trace visibility
  const [toolsMenuOpen, setToolsMenuOpen] = useState(false);
  const [showPipelineTrace, setShowPipelineTrace] = useState(false);
  const [expandedTraceSections, setExpandedTraceSections] = useState(() => ({}));

  // Commenting, Review Queue, and Bottom Document Dock state
  const [commentingKey, setCommentingKey] = useState(null);
  const [submittingComment, setSubmittingComment] = useState(false);
  const [queueDrawerOpen, setQueueDrawerOpen] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [actionError, setActionError] = useState(null);

  const [dockMode, setDockMode] = useState('comment'); // 'comment' | 'followup'
  const [dockInputText, setDockInputText] = useState('');
  const [dockFocused, setDockFocused] = useState(false);
  const [followupRunning, setFollowupRunning] = useState(false);
  const [followupStatusMsg, setFollowupStatusMsg] = useState(null);

  // Native <dialog> refs
  const dialogRef = useRef(null);
  const askDialogRef = useRef(null);
  const corpusDialogRef = useRef(null);
  const checkpointDialogRef = useRef(null);
  const toolsMenuRef = useRef(null);
  const [compilerJsonText, setCompilerJsonText] = useState(
    JSON.stringify(SAMPLE_TIER1_COMPILE_PAYLOAD, null, 2)
  );
  const [compilerError, setCompilerError] = useState(null);

  // Viewport ref, grid ref, and computed SVG Bezier links
  const viewportRef = useRef(null);
  const gridRef = useRef(null);
  const [bezierLinks, setBezierLinks] = useState([]);

  const fetchBundlesList = useCallback(async () => {
    const res = await fetch('/api/bundles');
    if (res.ok) {
      const data = await res.json();
      setBundlesList(data);
    }
  }, []);

  const fetchMattersList = useCallback(async () => {
    const res = await fetch('/api/matters');
    if (res.ok) {
      const data = await res.json();
      setMattersList(data.matters || []);
      setCanonicalAuths(data.canonical_authorities || []);
    }
  }, []);

  const loadBundle = useCallback(async (bId) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/bundles/${bId}`);
      if (res.ok) {
        const data = await res.json();
        setBundle(data);
        setCurrentBundleId(bId);
        setPinnedClaimId(null);
        setExpandedLevel2Ids([]);
        setHoveredRef(null);
        setActiveLinkPopover(null);
        setCommentingKey(null);
        setInspectorNode(null);
        setExpandedTraceSections({});
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const applyCreatedBundle = useCallback(
    async (newBundle) => {
      await fetchBundlesList();
      await fetchMattersList();
      setBundle(newBundle);
      setCurrentBundleId(newBundle.bundle_id);
      setPinnedClaimId(null);
      setExpandedLevel2Ids([]);
      setActiveRun(null);
      setActiveRunLiveMsg(null);
      saveActiveRunId(null);
    },
    [fetchBundlesList, fetchMattersList]
  );

  const openPersistedRun = useCallback(
    async (runObj) => {
      if (!runObj) return;
      if (runObj.status === 'completed' && runObj.result_bundle_id) {
        await loadBundle(runObj.result_bundle_id);
        return;
      }
      setActiveRun(runObj);
      saveActiveRunId(runObj.run_id);
      if (runObj.status === 'running') {
        setActiveRunLiveMsg('Reconnecting to active pipeline stream…');
        try {
          const { bundle: doneBundle, run: updatedRun } = await connectRunStream({
            runId: runObj.run_id,
            onProgress: (ev) => setActiveRunLiveMsg(`[${ev.stage}] ${ev.message}`),
            onCheckpoint: (ckptRun) => {
              setActiveRun(ckptRun);
              setActiveRunLiveMsg(null);
              checkpointDialogRef.current?.showModal();
            },
          });
          if (doneBundle) {
            await applyCreatedBundle(doneBundle);
          } else if (updatedRun) {
            setActiveRun(updatedRun);
            setActiveRunLiveMsg(null);
            checkpointDialogRef.current?.showModal();
          }
        } catch (err) {
          setActionError(err.message);
          setActiveRunLiveMsg(null);
        }
        return;
      }
      checkpointDialogRef.current?.showModal();
    },
    [applyCreatedBundle, loadBundle]
  );

  useEffect(() => {
    fetchBundlesList();
    fetchMattersList();
    loadBundle('legal_motion_1332');

    const storedRunId = loadActiveRunId();
    if (storedRunId) {
      fetch(`/api/runs/${storedRunId}`)
        .then((res) => (res.ok ? res.json() : null))
        .then((runData) => {
          if (!runData) {
            saveActiveRunId(null);
            return;
          }
          if (runData.status === 'completed' && runData.result_bundle_id) {
            saveActiveRunId(null);
            loadBundle(runData.result_bundle_id);
          } else if (runData.status !== 'failed') {
            setActiveRun(runData);
            if (runData.status === 'running') {
              openPersistedRun(runData);
            }
          }
        })
        .catch(() => {});
    }
  }, [fetchBundlesList, fetchMattersList, loadBundle, openPersistedRun]);

  // Close tools overflow popover on outside click
  useEffect(() => {
    if (!toolsMenuOpen) return;
    const handleOutside = (e) => {
      if (toolsMenuRef.current && !toolsMenuRef.current.contains(e.target)) {
        setToolsMenuOpen(false);
      }
    };
    window.addEventListener('pointerdown', handleOutside);
    return () => window.removeEventListener('pointerdown', handleOutside);
  }, [toolsMenuOpen]);

  // Progressive Escape key handling
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key !== 'Escape') return;
      if (toolsMenuOpen) {
        setToolsMenuOpen(false);
      } else if (activeLinkPopover) {
        setActiveLinkPopover(null);
      } else if (queueDrawerOpen) {
        setQueueDrawerOpen(false);
      } else if (inspectorNode) {
        setInspectorNode(null);
      } else if (commentingKey) {
        setCommentingKey(null);
      } else if (expandedLevel2Ids.length > 0) {
        setExpandedLevel2Ids([]);
      } else if (pinnedClaimId) {
        setPinnedClaimId(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toolsMenuOpen, activeLinkPopover, queueDrawerOpen, inspectorNode, commentingKey, expandedLevel2Ids, pinnedClaimId]);

  const nodesMap = useMemo(() => bundle?.nodes || {}, [bundle]);

  const tensionClaimIds = useMemo(() => {
    const set = new Set();
    for (const t of bundle?.audit_summary?.cross_section_tensions || []) {
      for (const cid of t.involved_claim_ids || []) {
        set.add(cid);
      }
    }
    return set;
  }, [bundle]);

  const activeClaimNode = pinnedClaimId ? nodesMap[pinnedClaimId] : null;

  const level1Nodes = useMemo(() => {
    if (!activeClaimNode) return [];
    return (activeClaimNode.direct_child_ids || []).map((id) => nodesMap[id]).filter(Boolean);
  }, [activeClaimNode, nodesMap]);

  const level2PlusNodes = useMemo(() => {
    const result = [];
    const seen = new Set();
    const queue = [...expandedLevel2Ids];

    while (queue.length > 0) {
      const currId = queue.shift();
      if (!currId || seen.has(currId)) continue;
      const node = nodesMap[currId];
      if (!node) continue;
      seen.add(currId);
      result.push(node);
      for (const deeperId of node.direct_child_ids || []) {
        if (expandedLevel2Ids.includes(deeperId) && !seen.has(deeperId)) {
          queue.push(deeperId);
        }
      }
    }
    return result;
  }, [expandedLevel2Ids, nodesMap]);

  const showL1 = Boolean(activeClaimNode);
  const showL2 = showL1 && level2PlusNodes.length > 0;
  const gridColsClass = showL2 ? 'cols-3' : showL1 ? 'cols-2' : 'cols-1';

  const activeNodeIds = useMemo(() => {
    const set = new Set();
    if (pinnedClaimId) set.add(pinnedClaimId);
    for (const n of expandedLevel2Ids) set.add(n);
    return set;
  }, [pinnedClaimId, expandedLevel2Ids]);

  const handleClickRef = useCallback(
    (targetNodeId, level) => {
      const targetNode = nodesMap[targetNodeId];
      if (!targetNode) return;
      setActiveLinkPopover(null);

      if (level === 0 || targetNode.type === 'claim') {
        if (pinnedClaimId === targetNodeId) {
          setPinnedClaimId(null);
          setExpandedLevel2Ids([]);
        } else {
          setPinnedClaimId(targetNodeId);
          setExpandedLevel2Ids([]);
          if (typeof window !== 'undefined' && window.innerWidth <= 1180) {
            requestAnimationFrame(() => {
              const laneEl = viewportRef.current?.querySelector('.lane-evidence');
              laneEl?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
          }
        }
      } else {
        setExpandedLevel2Ids((prev) => {
          const next = new Set(prev);
          if (next.has(targetNodeId)) {
            next.delete(targetNodeId);
          } else {
            next.add(targetNodeId);
            for (const subChildId of targetNode.direct_child_ids || []) {
              next.add(subChildId);
            }
          }
          return Array.from(next);
        });
      }
    },
    [nodesMap, pinnedClaimId]
  );

  const handleToggleSubtree = useCallback((parentNode) => {
    const childIds = parentNode.direct_child_ids || [];
    if (childIds.length === 0) return;
    setActiveLinkPopover(null);
    setExpandedLevel2Ids((prev) => {
      const next = new Set(prev);
      const anyOpen = childIds.some((id) => next.has(id));
      if (anyOpen) {
        for (const id of childIds) next.delete(id);
      } else {
        for (const id of childIds) next.add(id);
      }
      return Array.from(next);
    });
  }, []);

  const handleHoverRef = useCallback((nodeId, domEl, level) => {
    const rect = domEl.getBoundingClientRect();
    setHoveredRef({
      nodeId,
      level,
      rect: {
        top: rect.top,
        bottom: rect.bottom,
        left: rect.left,
        right: rect.right,
      },
    });
  }, []);

  const handleLeaveRef = useCallback(() => {
    setHoveredRef(null);
  }, []);

  // Recompute SVG Bezier connector lines AND interactive midpoint coordinates
  const recomputeConnectors = useCallback(() => {
    const container = viewportRef.current;
    if (!container || !showL1) {
      setBezierLinks([]);
      return;
    }
    const containerRect = container.getBoundingClientRect();
    const links = [];

    if (pinnedClaimId) {
      const claimBtn = container.querySelector(
        `button[data-ref-node-id="${pinnedClaimId}"][data-ref-level="0"]`
      );
      if (claimBtn) {
        const srcRect = claimBtn.getBoundingClientRect();
        const x1 = srcRect.right - containerRect.left;
        const y1 = srcRect.top + srcRect.height / 2 - containerRect.top;

        for (const l1Node of level1Nodes) {
          const targetCard = container.querySelector(`article[data-card-node-id="${l1Node.id}"]`);
          if (targetCard) {
            const tgtRect = targetCard.getBoundingClientRect();
            const x2 = tgtRect.left - containerRect.left;
            const y2 = tgtRect.top + 18 - containerRect.top;
            const dx = Math.max(32, (x2 - x1) * 0.5);
            const midX = (x1 + x2) / 2;
            const midY = (y1 + y2) / 2;
            links.push({
              id: `${pinnedClaimId}->${l1Node.id}`,
              sourceId: pinnedClaimId,
              targetId: l1Node.id,
              d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
              x1,
              y1,
              x2,
              y2,
              midX,
              midY,
              screenMidX: containerRect.left + midX,
              screenMidY: containerRect.top + midY,
              tier: 1,
            });
          }
        }
      }
    }

    if (showL2) {
      for (const l2Node of level2PlusNodes) {
        const targetCard = container.querySelector(`article[data-card-node-id="${l2Node.id}"]`);
        if (!targetCard) continue;
        const tgtRect = targetCard.getBoundingClientRect();
        const x2 = tgtRect.left - containerRect.left;
        const y2 = tgtRect.top + 18 - containerRect.top;

        const inlineTrigger = container.querySelector(
          `article .clause-highlight[data-ref-node-id="${l2Node.id}"]`
        );
        const parentL1 = level1Nodes.find((n) => (n.direct_child_ids || []).includes(l2Node.id));
        const fallbackParentCard = parentL1
          ? container.querySelector(`article[data-card-node-id="${parentL1.id}"]`)
          : null;

        const srcEl = inlineTrigger || fallbackParentCard;
        if (srcEl) {
          const srcRect = srcEl.getBoundingClientRect();
          const x1 = srcRect.right - containerRect.left;
          const y1 = srcRect.top + srcRect.height / 2 - containerRect.top;
          const dx = Math.max(32, Math.abs(x2 - x1) * 0.5);
          const midX = (x1 + x2) / 2;
          const midY = (y1 + y2) / 2;
          links.push({
            id: `${parentL1 ? parentL1.id : 'l1'}->${l2Node.id}`,
            sourceId: parentL1 ? parentL1.id : pinnedClaimId,
            targetId: l2Node.id,
            d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
            x1,
            y1,
            x2,
            y2,
            midX,
            midY,
            screenMidX: containerRect.left + midX,
            screenMidY: containerRect.top + midY,
            tier: 2,
          });
        }
      }
    }

    setBezierLinks(links);
  }, [showL1, showL2, pinnedClaimId, level1Nodes, level2PlusNodes]);

  useEffect(() => {
    const rafId = requestAnimationFrame(recomputeConnectors);
    window.addEventListener('resize', recomputeConnectors);
    window.addEventListener('scroll', recomputeConnectors, { passive: true });
    let observer = null;
    if (typeof ResizeObserver !== 'undefined' && gridRef.current) {
      observer = new ResizeObserver(() => requestAnimationFrame(recomputeConnectors));
      observer.observe(gridRef.current);
    }
    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener('resize', recomputeConnectors);
      window.removeEventListener('scroll', recomputeConnectors);
      observer?.disconnect();
    };
  }, [recomputeConnectors, commentingKey, showPipelineTrace, expandedTraceSections, bundle?.comments?.length]);

  const handleRunCompiler = async (e) => {
    e.preventDefault();
    setCompilerError(null);
    try {
      const parsed = JSON.parse(compilerJsonText);
      const endpoint =
        parsed.sections && Array.isArray(parsed.sections) ? '/api/compile' : '/api/bundles';
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parsed),
      });
      const data = await res.json();
      if (!res.ok) {
        setCompilerError(JSON.stringify(data.detail || data, null, 2));
        return;
      }
      await fetchBundlesList();
      setBundle(data);
      setCurrentBundleId(data.bundle_id);
      setPinnedClaimId(null);
      setExpandedLevel2Ids([]);
      dialogRef.current?.close();
    } catch (err) {
      setCompilerError(err.message);
    }
  };

  const handleSubmitComment = useCallback(
    async ({ scope = 'node', node_id, section_id, target_label, comment_text, suggested_status }) => {
      if (!currentBundleId) return;
      setSubmittingComment(true);
      setActionError(null);
      try {
        const res = await fetch(`/api/bundles/${currentBundleId}/comments`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scope,
            node_id,
            section_id,
            target_label,
            comment_text,
            suggested_status,
          }),
        });
        const data = await res.json();
        if (!res.ok) {
          setActionError(JSON.stringify(data.detail || data));
          return;
        }
        setBundle(data);
        await fetchBundlesList();
      } finally {
        setSubmittingComment(false);
      }
    },
    [currentBundleId, fetchBundlesList]
  );

  const handleDeleteComment = useCallback(
    async (commentId) => {
      if (!currentBundleId) return;
      const res = await fetch(`/api/bundles/${currentBundleId}/comments/${commentId}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        const data = await res.json();
        setBundle(data);
        await fetchBundlesList();
      }
    },
    [currentBundleId, fetchBundlesList]
  );

  const handleRegenerateBatch = useCallback(async () => {
    if (!currentBundleId) return;
    setRegenerating(true);
    setActionError(null);
    setFollowupStatusMsg('Triaging feedback notes and regenerating affected sections…');
    try {
      const res = await fetch(`/api/bundles/${currentBundleId}/regenerate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ smooth_transitions: true }),
      });
      const data = await res.json();
      if (!res.ok) {
        setActionError(formatApiError(data));
        return;
      }
      setBundle(data);
      setCommentingKey(null);
      setActiveLinkPopover(null);
      await fetchBundlesList();
    } catch (err) {
      setActionError(err.message);
    } finally {
      setRegenerating(false);
      setFollowupStatusMsg(null);
    }
  }, [currentBundleId, fetchBundlesList]);

  const handleJumpToComment = useCallback(
    (comment) => {
      if (comment.scope === 'document' || comment.section_id === '__document__') {
        viewportRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
        return;
      }
      if (comment.scope === 'section' || comment.node_id === '__section__') {
        const secEl = viewportRef.current?.querySelector(
          `section[data-section-id="${comment.section_id}"]`
        );
        secEl?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
      }
      const target = nodesMap[comment.node_id];
      if (!target) return;
      if (target.type === 'claim') {
        setPinnedClaimId(target.id);
        setExpandedLevel2Ids([]);
      } else if (target.parent_claim_ids?.length > 0) {
        const rootClaimId = target.parent_claim_ids[0];
        setPinnedClaimId(rootClaimId);
        const rootNode = nodesMap[rootClaimId];
        const isDirectL1 = (rootNode?.direct_child_ids || []).includes(target.id);
        setExpandedLevel2Ids(isDirectL1 ? [] : [target.id]);
      }
    },
    [nodesMap]
  );

  const activeMatterId = useMemo(() => {
    if (bundle?.matter_id) return bundle.matter_id;
    if (mattersList.some((m) => m.matter_id === currentBundleId)) return currentBundleId;
    return mattersList[0]?.matter_id || null;
  }, [bundle, mattersList, currentBundleId]);

  const handleDockSubmit = async (e) => {
    e.preventDefault();
    const text = dockInputText.trim();
    if (!text) return;

    if (dockMode === 'comment') {
      await handleSubmitComment({
        scope: 'document',
        node_id: '__document__',
        section_id: '__document__',
        target_label: bundle?.artifact?.title || 'Overall Memo',
        comment_text: text,
      });
      setDockInputText('');
      return;
    }

    // Mode: Ask Follow-up against active matter
    if (!activeMatterId) {
      askDialogRef.current?.showModal();
      return;
    }

    setFollowupRunning(true);
    setActionError(null);
    setFollowupStatusMsg(`Running follow-up against matter '${activeMatterId}'…`);
    try {
      const contextualQuestion = bundle?.artifact?.title
        ? `Follow-up to "${bundle.artifact.title}": ${text}`
        : text;
      const { bundle: newBundle } = await streamAskPipeline({
        matterId: activeMatterId,
        question: contextualQuestion,
        bundleId: null,
        checkpointMode: false,
        onProgress: (ev) => setFollowupStatusMsg(`[${ev.stage}] ${ev.message}`),
      });
      if (newBundle) {
        await fetchBundlesList();
        setBundle(newBundle);
        setCurrentBundleId(newBundle.bundle_id);
        setPinnedClaimId(null);
        setExpandedLevel2Ids([]);
        setDockInputText('');
      }
    } catch (err) {
      setActionError(err.message);
    } finally {
      setFollowupRunning(false);
      setFollowupStatusMsg(null);
    }
  };

  if (loading || !bundle) {
    return html`
      <div class="app-shell" style="padding: 48px; text-align: center; color: var(--color-text-secondary);">
        <p>Loading document…</p>
      </div>
    `;
  }

  const summary = bundle.audit_summary || {};
  const caveatCount = (summary.extrapolation_count || 0) + (summary.assumption_count || 0);
  const tensionCount = (summary.cross_section_tensions || []).length;
  const hoveredNode = hoveredRef ? nodesMap[hoveredRef.nodeId] : null;
  const allComments = bundle.comments || [];
  const pendingComments = allComments.filter((c) => !c.resolved);
  const docCommentsCount = pendingComments.filter(
    (c) => c.scope === 'document' || c.section_id === '__document__'
  ).length;

  return html`
    <div class="app-shell">
      <header class="top-bar" inert=${Boolean(inspectorNode || queueDrawerOpen)}>
        <div class="top-bar-left">
          <span class="brand-title">Audit Canvas</span>
          <span class="divider-vertical" aria-hidden="true"></span>
          <div class="control-group">
            <label for="bundle-selector" class="visually-hidden">Select Document</label>
            <select
              id="bundle-selector"
              class="select-control"
              value=${currentBundleId}
              onChange=${(e) => loadBundle(e.target.value)}
            >
              ${bundlesList.map(
                (b) => html`
                  <option key=${b.bundle_id} value=${b.bundle_id}>
                    ${b.title}
                  </option>
                `
              )}
            </select>
          </div>
        </div>

        <div class="top-bar-right">
          <div class="status-filter-strip" role="group" aria-label="Filter claims by verification status">
            <button
              type="button"
              class="status-filter-btn ${auditFilter === 'all' ? 'is-active' : ''}"
              aria-pressed=${auditFilter === 'all'}
              onClick=${() => setAuditFilter('all')}
            >
              <span class="status-dot is-verified" aria-hidden="true"></span>
              <span>All Claims</span>
              <span class="font-mono-data">(${summary.total_claims || 0})</span>
            </button>
            <button
              type="button"
              class="status-filter-btn is-caveat ${auditFilter === 'caveats' ? 'is-active' : ''}"
              aria-pressed=${auditFilter === 'caveats'}
              onClick=${() => setAuditFilter((f) => (f === 'caveats' ? 'all' : 'caveats'))}
            >
              <span class="status-dot is-warning" aria-hidden="true"></span>
              <span>Caveats</span>
              <span class="font-mono-data">(${caveatCount})</span>
            </button>
            ${tensionCount > 0 && html`
              <button
                type="button"
                class="status-filter-btn is-tension ${auditFilter === 'tension' ? 'is-active' : ''}"
                aria-pressed=${auditFilter === 'tension'}
                onClick=${() => setAuditFilter((f) => (f === 'tension' ? 'all' : 'tension'))}
              >
                <span class="status-dot is-danger" aria-hidden="true"></span>
                <span>Tensions</span>
                <span class="font-mono-data">(${tensionCount})</span>
              </button>
            `}
          </div>

          <button
            type="button"
            class="btn"
            onClick=${() => {
              setCorpusTabHint('matter');
              setCorpusMatterHint(activeMatterId);
              corpusDialogRef.current?.showModal();
            }}
          >
            <${Icon} name="folder" size=${13} />
            <span>Sources & Rules</span>
          </button>

          <button
            type="button"
            class="btn btn-primary"
            onClick=${() => askDialogRef.current?.showModal()}
          >
            <${Icon} name="plus" size=${13} />
            <span>New Brief</span>
          </button>

          <div class="tools-menu-wrap" ref=${toolsMenuRef}>
            <button
              type="button"
              class="btn"
              aria-label="Pipeline tools and workspace settings"
              aria-expanded=${toolsMenuOpen}
              onClick=${() => setToolsMenuOpen((v) => !v)}
            >
              <${Icon} name="more" size=${13} />
              <span>Tools</span>
            </button>

            ${toolsMenuOpen && html`
              <div class="tools-popover" role="menu">
                <button
                  type="button"
                  class="tools-menu-item"
                  role="menuitemcheckbox"
                  aria-checked=${showPipelineTrace}
                  onClick=${() => {
                    setShowPipelineTrace((v) => !v);
                    setToolsMenuOpen(false);
                  }}
                >
                  <div>
                    <div>Pipeline Reasoning Trace</div>
                    <span class="tools-menu-sub">Show stage 1–4 notes under sections</span>
                  </div>
                  ${showPipelineTrace && html`<${Icon} name="check" size=${14} />`}
                </button>
                <button
                  type="button"
                  class="tools-menu-item"
                  role="menuitem"
                  onClick=${() => {
                    setToolsMenuOpen(false);
                    setCorpusTabHint('canonical');
                    setCorpusMatterHint(activeMatterId);
                    corpusDialogRef.current?.showModal();
                  }}
                >
                  <div>
                    <div>Corpus & Rule Library</div>
                    <span class="tools-menu-sub">Inspect, add, or remove rules & matter files</span>
                  </div>
                </button>
                ${activeRun && html`
                  <button
                    type="button"
                    class="tools-menu-item"
                    role="menuitem"
                    onClick=${() => {
                      setToolsMenuOpen(false);
                      checkpointDialogRef.current?.showModal();
                    }}
                  >
                    <div>
                      <div>Active Checkpoint Run</div>
                      <span class="tools-menu-sub">${formatRunStatusLabel(activeRun.status)}</span>
                    </div>
                  </button>
                `}
                <div class="tools-divider"></div>
                <button
                  type="button"
                  class="tools-menu-item"
                  role="menuitem"
                  onClick=${() => {
                    setToolsMenuOpen(false);
                    setCompilerError(null);
                    dialogRef.current?.showModal();
                  }}
                >
                  <div>
                    <div>Import / Compile JSON</div>
                    <span class="tools-menu-sub">Load or compile structured bundle JSON</span>
                  </div>
                </button>
              </div>
            `}
          </div>
        </div>
      </header>

      ${activeRun && activeRun.status !== 'completed' && html`
        <div
          class="active-run-banner ${
            activeRun.status === 'awaiting_stage1_approval' || activeRun.status === 'awaiting_stage2_approval'
              ? 'is-paused'
              : ''
          }"
        >
          <span>
            <strong>${formatRunStatusLabel(activeRun.status)}</strong>
            ${activeRunLiveMsg
              ? ` · ${activeRunLiveMsg}`
              : ` · Run ${activeRun.run_id} (${activeRun.matter_id})`}
          </span>
          <div style="display: inline-flex; gap: 8px; align-items: center;">
            <button
              type="button"
              class="btn btn-compact btn-primary"
              onClick=${() => checkpointDialogRef.current?.showModal()}
            >
              <${Icon} name="play" size=${12} />
              <span>Open Checkpoint Review</span>
            </button>
            <button
              type="button"
              class="btn btn-compact"
              onClick=${() => {
                setActiveRun(null);
                setActiveRunLiveMsg(null);
                saveActiveRunId(null);
              }}
            >
              Dismiss
            </button>
          </div>
        </div>
      `}

      <main
        id="workspace-main"
        tabindex="-1"
        class="spatial-viewport"
        ref=${viewportRef}
        inert=${Boolean(inspectorNode || queueDrawerOpen)}
      >
        <svg class="connector-svg-layer" aria-hidden="true">
          ${bezierLinks.map((link) => {
            const targetNode = nodesMap[link.targetId];
            const roleMeta = getLinkRoleMeta(targetNode);
            const isHovered = hoveredLinkId === link.id || activeLinkPopover?.id === link.id;
            const strokeColor = link.tier === 1 ? roleMeta.stroke : '#3E4652';
            return html`
              <g key=${link.id}>
                <path
                  d=${link.d}
                  fill="none"
                  stroke="transparent"
                  stroke-width="14"
                  class="bezier-hit-path"
                  onMouseEnter=${() => setHoveredLinkId(link.id)}
                  onMouseLeave=${() => setHoveredLinkId(null)}
                  onClick=${(e) => {
                    e.stopPropagation();
                    setActiveLinkPopover(link);
                  }}
                />
                <path
                  d=${link.d}
                  fill="none"
                  class="bezier-stroke"
                  stroke=${strokeColor}
                  stroke-width=${isHovered ? '2.25' : '1.5'}
                  opacity=${isHovered ? '1' : '0.68'}
                />
                <rect
                  x=${link.x1 - 2.5}
                  y=${link.y1 - 2.5}
                  width="5"
                  height="5"
                  fill=${strokeColor}
                />
                <rect
                  x=${link.x2 - 2.5}
                  y=${link.y2 - 2.5}
                  width="5"
                  height="5"
                  fill=${strokeColor}
                />
              </g>
            `;
          })}
        </svg>

        ${bezierLinks.length > 0 && html`
          <div class="connector-handles-layer">
            ${bezierLinks.map((link) => {
              const targetNode = nodesMap[link.targetId];
              const roleMeta = getLinkRoleMeta(targetNode);
              const linkNoteCount = allComments.filter(
                (c) => !c.resolved && c.node_id === link.targetId && c.scope === 'link'
              ).length;
              const isOpen = activeLinkPopover?.id === link.id;
              return html`
                <button
                  key=${`handle-${link.id}`}
                  type="button"
                  class="bezier-link-handle ${roleMeta.toneClass} ${isOpen ? 'is-active' : ''}"
                  style=${{ left: `${link.midX}px`, top: `${link.midY}px` }}
                  aria-label=${`Inspect or comment on ${roleMeta.label} connection to ${targetNode?.title || link.targetId}`}
                  onMouseEnter=${() => setHoveredLinkId(link.id)}
                  onMouseLeave=${() => setHoveredLinkId(null)}
                  onClick=${(e) => {
                    e.stopPropagation();
                    setActiveLinkPopover(isOpen ? null : link);
                  }}
                >
                  <span>${roleMeta.label}</span>
                  ${linkNoteCount > 0 && html`
                    <span class="bezier-link-count">· ${linkNoteCount}</span>
                  `}
                </button>
              `;
            })}
          </div>
        `}

        <div class="bounded-canvas-grid ${gridColsClass}" ref=${gridRef}>
          <!-- COLUMN 1: DOCUMENT -->
          <div class="column-lane">
            <div class="lane-header">
              <span class="lane-title-group">
                <span class="lane-title">Document</span>
              </span>
              <span class="lane-caption">
                ${showL1
                  ? 'Click any highlighted claim or curve handle to verify & comment'
                  : 'Click any highlighted claim to trace supporting proof'}
              </span>
            </div>

            <article class="artifact-sheet">
              <div class="artifact-header">
                <h1 class="artifact-title">${bundle.artifact.title}</h1>
                <div class="artifact-meta-ledger">
                  ${Object.entries(bundle.artifact.metadata || {})
                    .filter(([k, v]) => k !== 'available_raw_files' && v != null && typeof v !== 'object')
                    .map(
                      ([k, v]) => html`
                        <span key=${k} class="meta-pair">
                          <span class="control-label">${k.replace(/_/g, ' ')}</span>
                          <span>${v}</span>
                        </span>
                      `
                    )}
                  <span class="meta-pair">
                    <span class="control-label">Verified</span>
                    <span class="font-mono-data">${summary.verified_count || 0}/${summary.total_claims || 0}</span>
                  </span>
                </div>
                ${bundle.artifact.summary && html`
                  <p class="artifact-summary">${bundle.artifact.summary}</p>
                `}
              </div>

              ${(summary.cross_section_tensions || []).map(
                (ten) => html`
                  <div
                    key=${ten.tension_id}
                    class="tension-callout ${ten.severity === 'warning' ? 'is-warning' : ''}"
                  >
                    <div class="tension-callout-header ${ten.severity === 'warning' ? 'is-warning' : ''}">
                      <span style="display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <span>
                          ${ten.tension_scope === 'cross_bundle'
                            ? `Cross-Bundle Contradiction (${ten.severity})`
                            : `Cross-Section Tension (${ten.severity})`}
                        </span>
                        ${ten.tension_scope === 'cross_bundle' && html`
                          <span class="tension-scope-badge">
                            vs. ${ten.conflicting_bundle_title || ten.conflicting_bundle_id}
                          </span>
                        `}
                      </span>
                      <span class="font-mono-data">${ten.tension_id}</span>
                    </div>
                    <p class="tension-desc">${ten.description}</p>
                    <div class="tension-actions">
                      ${(ten.involved_claim_ids || []).map((cid) => {
                        const cNode = nodesMap[cid];
                        return html`
                          <button
                            type="button"
                            key=${cid}
                            class="btn-link"
                            onClick=${() => handleClickRef(cid, 0)}
                          >
                            ${pinnedClaimId === cid ? 'Viewing' : 'Inspect'} “${cNode ? cNode.title : cid}”
                          </button>
                        `;
                      })}
                      ${ten.conflicting_bundle_id && html`
                        <button
                          type="button"
                          class="btn-link"
                          onClick=${() => loadBundle(ten.conflicting_bundle_id)}
                        >
                          Open ${ten.conflicting_bundle_title || ten.conflicting_bundle_id} →
                        </button>
                      `}
                    </div>
                  </div>
                `
              )}

              ${(bundle.artifact.sections || []).map((sec) => {
                const sa = bundle.stage_artifacts || {};
                const outlineSec = ((sa.outline_plan && sa.outline_plan.sections) || []).find(
                  (s) => s.section_id === sec.section_id
                );
                const ledgerSec = (sa.ledgers && sa.ledgers[sec.section_id]) || null;
                const draftSec = (sa.sections || []).find((s) => s.section_id === sec.section_id);
                const auditSec = (sa.audits && sa.audits[sec.section_id]) || null;
                const hasTrace = Boolean(outlineSec || ledgerSec || draftSec || auditSec);
                const isTraceOpen = Boolean(expandedTraceSections[sec.section_id]);
                const secPanelKey = `section:${sec.section_id}`;
                const isSecCommentOpen = commentingKey === secPanelKey;
                const secCommentCount = pendingComments.filter(
                  (c) => c.scope === 'section' && c.section_id === sec.section_id
                ).length;

                return html`
                  <section key=${sec.section_id} data-section-id=${sec.section_id} class="artifact-section">
                    <h2 class="section-heading">${sec.section_title}</h2>

                    <p class="section-prose">
                      ${renderAnnotatedText({
                        text: sec.content,
                        nodesMap,
                        activeNodeIds,
                        tensionClaimIds,
                        auditFilter,
                        onHoverRef: handleHoverRef,
                        onLeaveRef: handleLeaveRef,
                        onClickRef: handleClickRef,
                        level: 0,
                      })}
                    </p>

                    <div class="section-footer-actions">
                      <button
                        type="button"
                        class="btn-link is-muted"
                        onClick=${() => setCommentingKey(isSecCommentOpen ? null : secPanelKey)}
                      >
                        <${Icon} name="comment" size=${12} />
                        <span>
                          ${isSecCommentOpen
                            ? 'Close section note'
                            : secCommentCount > 0
                            ? `Section notes (${secCommentCount})`
                            : 'Comment on section'}
                        </span>
                      </button>

                      ${showPipelineTrace && hasTrace && html`
                        <button
                          type="button"
                          class="btn-link is-muted"
                          onClick=${() =>
                            setExpandedTraceSections((prev) => ({
                              ...prev,
                              [sec.section_id]: !prev[sec.section_id],
                            }))
                          }
                        >
                          <${Icon} name=${isTraceOpen ? 'chevronDown' : 'chevronRight'} size=${12} />
                          <span>${isTraceOpen ? 'Hide pipeline trace' : 'Pipeline trace (1–4)'}</span>
                        </button>
                      `}
                    </div>

                    <${InlineCommentPanel}
                      targetKey=${secPanelKey}
                      scope="section"
                      nodeId="__section__"
                      sectionId=${sec.section_id}
                      targetLabel=${sec.section_title}
                      placeholder="Suggest revisions or missing analysis for this section..."
                      comments=${allComments}
                      nodesMap=${nodesMap}
                      isOpen=${isSecCommentOpen}
                      onClose=${() => setCommentingKey(null)}
                      onSubmit=${handleSubmitComment}
                      onDelete=${handleDeleteComment}
                      submitting=${submittingComment}
                      allowStatusOverride=${false}
                    />

                    ${showPipelineTrace && hasTrace && isTraceOpen && html`
                      <div class="stage-trace-drawer">
                        ${outlineSec && html`
                          <div class="stage-trace-row">
                            <span class="control-label">Stage 1 · Plan & Routing</span>
                            <div><strong>Intention:</strong> ${outlineSec.stated_intention}</div>
                            ${outlineSec.routing_rationale && html`
                              <div><strong>Rationale:</strong> ${outlineSec.routing_rationale}</div>
                            `}
                          </div>
                        `}
                        ${ledgerSec && html`
                          <div class="stage-trace-row">
                            <span class="control-label">Stage 2 · Evidence Harvest</span>
                            <div>
                              ${ledgerSec.harvest_summary ||
                                `Collected ${(ledgerSec.verified_facts || []).length} verified fact(s) and ${(ledgerSec.unresolved_gaps || []).length} gap(s).`}
                            </div>
                          </div>
                        `}
                        ${draftSec && html`
                          <div class="stage-trace-row">
                            <span class="control-label">Stage 3 · Synthesis Notes</span>
                            <div>
                              ${draftSec.drafting_notes || 'Compiled section prose under closed-world verification.'}
                            </div>
                          </div>
                        `}
                        ${auditSec && html`
                          <div class="stage-trace-row">
                            <span class="control-label">Stage 4 · Independent Audit</span>
                            <div class="stage-trace-checks">
                              <span class="arch-stamp ${auditSec.check_a_relevance ? '' : 'is-danger'}">
                                Relevance: ${auditSec.check_a_relevance ? 'PASS' : 'FAIL'}
                              </span>
                              <span class="arch-stamp ${auditSec.check_b_congruence ? '' : 'is-danger'}">
                                Congruence: ${auditSec.check_b_congruence ? 'PASS' : 'FAIL'}
                              </span>
                              <span class="arch-stamp ${auditSec.check_c_intent ? '' : 'is-caveat'}">
                                Intent: ${auditSec.check_c_intent ? 'PASS' : 'FAIL'}
                              </span>
                            </div>
                            ${auditSec.audit_rationale && html`<div>${auditSec.audit_rationale}</div>`}
                          </div>
                        `}
                      </div>
                    `}
                  </section>
                `;
              })}
            </article>
          </div>

          <!-- COLUMN 2: PROOF & REASONING -->
          ${showL1 && html`
            <div class="column-lane lane-analytical lane-evidence">
              <div class="lane-header">
                <span class="lane-title-group">
                  <span class="lane-title">Proof & Reasoning</span>
                  <span class="lane-count">(${level1Nodes.length})</span>
                </span>
                <div style="display: inline-flex; align-items: center; gap: 10px;">
                  <button
                    type="button"
                    class="btn-link mobile-only-jump"
                    onClick=${() => {
                      const refEl = viewportRef.current?.querySelector(
                        `button[data-ref-node-id="${pinnedClaimId}"]`
                      );
                      refEl?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }}
                  >
                    ↑ Back to Document
                  </button>
                  <button
                    type="button"
                    class="btn-link is-muted"
                    onClick=${() => {
                      setPinnedClaimId(null);
                      setExpandedLevel2Ids([]);
                      setActiveLinkPopover(null);
                    }}
                  >
                    <${Icon} name="close" size=${12} />
                    <span>Close</span>
                  </button>
                </div>
              </div>

              <div class="spatial-card-stack">
                <div class="claim-context-bar">
                  <div class="card-meta-row" style="align-items: flex-start;">
                    <div class="card-heading">${activeClaimNode.title}</div>
                    <span class="arch-stamp ${isCaveatStatus(activeClaimNode.audit?.status) ? 'is-caveat' : ''}">
                      ${formatAuditStatus(activeClaimNode.audit?.status || 'verified')}
                    </span>
                  </div>
                  ${activeClaimNode.audit?.evaluator_note &&
                    activeClaimNode.audit.evaluator_note !== 'Verified across attached local support nodes.' && html`
                    <div class="provenance-caption">${activeClaimNode.audit.evaluator_note}</div>
                  `}
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <button
                      type="button"
                      class="plate-action-btn"
                      onClick=${() => {
                        const key = `node:${activeClaimNode.id}`;
                        setCommentingKey(commentingKey === key ? null : key);
                      }}
                    >
                      <${Icon} name="comment" size=${13} />
                      <span>
                        ${commentingKey === `node:${activeClaimNode.id}`
                          ? 'Close Note'
                          : 'Comment on Claim'}
                      </span>
                    </button>
                  </div>
                  <${InlineCommentPanel}
                    targetKey=${`node:${activeClaimNode.id}`}
                    scope="node"
                    nodeId=${activeClaimNode.id}
                    sectionId=${activeClaimNode.section_id}
                    targetLabel=${activeClaimNode.title}
                    comments=${allComments}
                    nodesMap=${nodesMap}
                    isOpen=${commentingKey === `node:${activeClaimNode.id}`}
                    onClose=${() => setCommentingKey(null)}
                    onSubmit=${handleSubmitComment}
                    onDelete=${handleDeleteComment}
                    submitting=${submittingComment}
                  />
                </div>

                ${level1Nodes.map(
                  (node) => html`
                    <${SpatialNodeCard}
                      key=${node.id}
                      node=${node}
                      level=${1}
                      nodesMap=${nodesMap}
                      activeNodeIds=${activeNodeIds}
                      expandedLevel2Ids=${expandedLevel2Ids}
                      tensionClaimIds=${tensionClaimIds}
                      auditFilter=${auditFilter}
                      comments=${allComments}
                      commentingKey=${commentingKey}
                      onToggleComment=${setCommentingKey}
                      onSubmitComment=${handleSubmitComment}
                      onDeleteComment=${handleDeleteComment}
                      submittingComment=${submittingComment}
                      onHoverRef=${handleHoverRef}
                      onLeaveRef=${handleLeaveRef}
                      onClickRef=${handleClickRef}
                      onToggleSubtree=${handleToggleSubtree}
                      onOpenInspector=${setInspectorNode}
                      sourceLink=${resolveSourceFileUrl(node, bundle, mattersList, canonicalAuths)}
                      isFocused=${hoveredRef?.nodeId === node.id || activeLinkPopover?.targetId === node.id}
                    />
                  `
                )}
              </div>
            </div>
          `}

          <!-- COLUMN 3: SOURCES & LAW -->
          ${showL2 && html`
            <div class="column-lane lane-analytical">
              <div class="lane-header">
                <span class="lane-title-group">
                  <span class="lane-title">Sources & Law</span>
                  <span class="lane-count">(${level2PlusNodes.length})</span>
                </span>
                <button
                  type="button"
                  class="btn-link is-muted"
                  onClick=${() => {
                    setExpandedLevel2Ids([]);
                    setActiveLinkPopover(null);
                  }}
                >
                  <${Icon} name="close" size=${12} />
                  <span>Close</span>
                </button>
              </div>

              <div class="spatial-card-stack">
                ${level2PlusNodes.map(
                  (node) => html`
                    <${SpatialNodeCard}
                      key=${node.id}
                      node=${node}
                      level=${2}
                      nodesMap=${nodesMap}
                      activeNodeIds=${activeNodeIds}
                      expandedLevel2Ids=${expandedLevel2Ids}
                      tensionClaimIds=${tensionClaimIds}
                      auditFilter=${auditFilter}
                      comments=${allComments}
                      commentingKey=${commentingKey}
                      onToggleComment=${setCommentingKey}
                      onSubmitComment=${handleSubmitComment}
                      onDeleteComment=${handleDeleteComment}
                      submittingComment=${submittingComment}
                      onHoverRef=${handleHoverRef}
                      onLeaveRef=${handleLeaveRef}
                      onClickRef=${handleClickRef}
                      onToggleSubtree=${handleToggleSubtree}
                      onOpenInspector=${setInspectorNode}
                      sourceLink=${resolveSourceFileUrl(node, bundle, mattersList, canonicalAuths)}
                      isFocused=${hoveredRef?.nodeId === node.id || activeLinkPopover?.targetId === node.id}
                    />
                  `
                )}
              </div>
            </div>
          `}
        </div>
      </main>

      <!-- HOVER PREVIEW TOOLTIP -->
      ${hoveredNode && html`
        <div
          class="hover-tooltip-preview"
          style=${{
            top: `${Math.min(window.innerHeight - 120, hoveredRef.rect.bottom + 8)}px`,
            left: `${Math.min(window.innerWidth - 312, Math.max(12, hoveredRef.rect.left))}px`,
          }}
        >
          <div class="card-meta-row">
            <span class="control-label">${formatNodeRole(hoveredNode.type)}</span>
            <span class="arch-stamp ${isCaveatStatus(hoveredNode.audit?.status) ? 'is-caveat' : ''}">
              ${formatAuditStatus(hoveredNode.audit?.status || 'verified')}
            </span>
          </div>
          <div class="card-heading" style="font-size: 14.5px;">
            ${hoveredNode.title}
          </div>
          <div class="provenance-caption" style="color: var(--color-accent-primary);">
            ${hoveredRef.level === 0
              ? `Click to inspect ${hoveredNode.direct_child_ids?.length || 0} supporting item(s)`
              : 'Click to open underlying rule or source'}
          </div>
        </div>
      `}

      <!-- ANCHORED LOGICAL LINK COMMENT POPOVER -->
      <${LinkCommentPopover}
        link=${activeLinkPopover}
        nodesMap=${nodesMap}
        comments=${allComments}
        onClose=${() => setActiveLinkPopover(null)}
        onSubmitComment=${handleSubmitComment}
        onDeleteComment=${handleDeleteComment}
        onOpenInspector=${setInspectorNode}
        submitting=${submittingComment}
      />

      <!-- PERSISTENT BOTTOM DOCUMENT DOCK: OVERALL FEEDBACK + FOLLOW-UP QUESTION + REVIEW QUEUE -->
      <footer
        class="document-dock ${!dockFocused && !dockInputText.trim() && pendingComments.length === 0 && !followupStatusMsg && !actionError ? 'is-compact' : ''}"
        inert=${Boolean(inspectorNode || queueDrawerOpen)}
        onFocusIn=${() => setDockFocused(true)}
        onBlur=${(e) => {
          if (!e.currentTarget.contains(e.relatedTarget)) {
            setDockFocused(false);
          }
        }}
      >
        ${(followupStatusMsg || actionError) && html`
          <div
            class="dock-stream-banner"
            style=${actionError
              ? 'background-color: var(--color-danger-subtle); border-color: var(--color-danger-border); color: var(--color-danger);'
              : ''}
          >
            <span>${actionError ? `Error: ${actionError}` : followupStatusMsg}</span>
            ${actionError && html`
              <button type="button" class="btn-link" onClick=${() => setActionError(null)}>
                Dismiss
              </button>
            `}
          </div>
        `}

        <div class="dock-main-row">
          <div class="dock-mode-switch" role="tablist" aria-label="Document feedback mode">
            <button
              type="button"
              role="tab"
              aria-selected=${dockMode === 'comment'}
              class="dock-mode-btn ${dockMode === 'comment' ? 'is-active' : ''}"
              onClick=${() => setDockMode('comment')}
            >
              <${Icon} name="comment" size=${13} />
              <span>Overall Comment</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected=${dockMode === 'followup'}
              class="dock-mode-btn ${dockMode === 'followup' ? 'is-active' : ''}"
              onClick=${() => setDockMode('followup')}
            >
              <${Icon} name="link" size=${13} />
              <span>Ask Follow-up</span>
            </button>
          </div>

          <form class="dock-composer-form" onSubmit=${handleDockSubmit}>
            <label for="document-dock-input" class="visually-hidden">
              ${dockMode === 'comment' ? 'Comment on overall document' : 'Ask a follow-up question'}
            </label>
            <input
              id="document-dock-input"
              type="text"
              class="dock-text-input"
              placeholder=${dockMode === 'comment'
                ? 'Comment on the overall memo (e.g., clarify tone, add missing analysis, check cross-references)...'
                : `Ask a follow-up question on ${activeMatterId || 'this matter'}...`}
              value=${dockInputText}
              disabled=${submittingComment || followupRunning || regenerating}
              onInput=${(e) => setDockInputText(e.target.value)}
            />
            <button
              type="submit"
              class="btn ${pendingComments.length === 0 ? 'btn-primary' : ''}"
              disabled=${!dockInputText.trim() || submittingComment || followupRunning || regenerating}
            >
              ${dockMode === 'comment'
                ? submittingComment
                  ? 'Saving…'
                  : docCommentsCount > 0
                  ? `Queue Note (${docCommentsCount})`
                  : 'Queue Note'
                : followupRunning
                ? 'Running…'
                : 'Run Follow-up'}
            </button>
          </form>

          ${pendingComments.length > 0 && html`
            <div class="dock-queue-cluster">
              <button
                type="button"
                class="btn"
                onClick=${() => setQueueDrawerOpen(true)}
              >
                Review Queue (${pendingComments.length})
              </button>
              <button
                type="button"
                class="btn btn-primary"
                disabled=${regenerating || followupRunning}
                onClick=${handleRegenerateBatch}
              >
                ${regenerating
                  ? 'Regenerating…'
                  : `Apply Feedback & Re-compile (${pendingComments.length})`}
              </button>
            </div>
          `}
        </div>
      </footer>

      <!-- SLIDE-OVER SOURCE INSPECTOR DRAWER -->
      <${SourceInspectorDrawer}
        node=${inspectorNode}
        sourceLink=${resolveSourceFileUrl(inspectorNode, bundle, mattersList, canonicalAuths)}
        onClose=${() => setInspectorNode(null)}
      />

      <!-- SLIDE-OVER REVIEW QUEUE DRAWER -->
      <${ReviewQueueDrawer}
        isOpen=${queueDrawerOpen}
        pendingComments=${pendingComments}
        nodesMap=${nodesMap}
        onClose=${() => setQueueDrawerOpen(false)}
        onJumpToComment=${handleJumpToComment}
        onDeleteComment=${handleDeleteComment}
        onRegenerate=${handleRegenerateBatch}
        regenerating=${regenerating}
      />

      <!-- WORKSPACE / NEW QUESTION / RUNS DIALOG -->
      <${AskPipelineDialog}
        dialogRef=${askDialogRef}
        activeMatterHint=${activeMatterId}
        onBundleCreated=${applyCreatedBundle}
        onCheckpointPaused=${(ckptRun) => {
          setActiveRun(ckptRun);
          checkpointDialogRef.current?.showModal();
        }}
        onOpenCorpusManager=${(tab, matterHint) => {
          setCorpusTabHint(tab || 'canonical');
          setCorpusMatterHint(matterHint || activeMatterId);
          corpusDialogRef.current?.showModal();
        }}
        onOpenRun=${openPersistedRun}
      />

      <!-- CORPUS & MATTER FILE MANAGER DIALOG -->
      <${CorpusManagerModal}
        dialogRef=${corpusDialogRef}
        activeMatterHint=${corpusMatterHint || activeMatterId}
        initialTab=${corpusTabHint}
        onCorpusChanged=${fetchMattersList}
      />

      <!-- STAGE 1 & STAGE 2 CHECKPOINT REVIEW DIALOG -->
      <${CheckpointReviewModal}
        dialogRef=${checkpointDialogRef}
        run=${activeRun}
        canonicalAuths=${canonicalAuths}
        onRunUpdated=${(updatedRun) => {
          setActiveRun(updatedRun);
          if (updatedRun?.run_id) {
            saveActiveRunId(updatedRun.status === 'completed' ? null : updatedRun.run_id);
          }
        }}
        onBundleCreated=${applyCreatedBundle}
        onOpenMatterFiles=${(mId) => {
          setCorpusTabHint('matter');
          setCorpusMatterHint(mId);
          corpusDialogRef.current?.showModal();
        }}
      />

      <!-- ADVANCED TIER-1 / TIER-2 JSON COMPILER DIALOG -->
      <dialog
        ref=${dialogRef}
        class="compiler-dialog"
        closedby="any"
        aria-labelledby="compiler-dialog-title"
      >
        <div class="dialog-inner">
          <div class="card-meta-row">
            <h2 id="compiler-dialog-title" class="card-heading" style="font-size: 17px;">
              Import / Compile Bundle JSON
            </h2>
            <form method="dialog">
              <button type="submit" class="btn btn-icon-only" aria-label="Close JSON compiler">
                <${Icon} name="close" />
              </button>
            </form>
          </div>

          <p class="provenance-caption">
            Paste a Tier-1 <code class="font-mono-data">CompilePipelineRequest</code> or Tier-2
            <code class="font-mono-data">CompiledBundle</code> JSON payload to validate and render on the canvas.
          </p>

          <form onSubmit=${handleRunCompiler} style="display: flex; flex-direction: column; gap: 12px;">
            <label for="compiler-json-input" class="control-label">
              JSON Payload
            </label>
            <textarea
              id="compiler-json-input"
              class="code-textarea"
              value=${compilerJsonText}
              onInput=${(e) => setCompilerJsonText(e.target.value)}
              required
            ></textarea>

            ${compilerError && html`
              <pre
                tabindex="0"
                class="formula-box"
                style="border-color: var(--color-danger); color: var(--color-danger); background-color: var(--color-danger-subtle);"
              ><code>${compilerError}</code></pre>
            `}

            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button
                type="button"
                class="btn"
                onClick=${() =>
                  setCompilerJsonText(JSON.stringify(SAMPLE_TIER1_COMPILE_PAYLOAD, null, 2))
                }
              >
                Reset Sample
              </button>
              <button type="submit" class="btn btn-primary">
                Validate & Render
              </button>
            </div>
          </form>
        </div>
      </dialog>
    </div>
  `;
}

render(html`<${App} />`, document.getElementById('app-root'));
