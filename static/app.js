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
    default:
      return { label: locator.source_type || '', coord: '' };
  }
}

/**
 * Streams the 4-stage SSE pipeline from `/api/matters/:matter_id/ask/stream`.
 */
async function streamAskPipeline({ matterId, question, bundleId, onProgress }) {
  const res = await fetch(`/api/matters/${matterId}/ask/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: question.trim(),
      bundle_id: bundleId || null,
      smooth_transitions: true,
    }),
  });
  if (!res.ok || !res.body) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(JSON.stringify(errData.detail || `HTTP ${res.status}`));
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let resultBundle = null;

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
      if (evt.event === 'progress') {
        onProgress?.({ stage: evt.stage, message: evt.message });
      } else if (evt.event === 'error') {
        throw new Error(evt.detail || 'Pipeline execution failed');
      } else if (evt.event === 'bundle') {
        resultBundle = evt.bundle;
      }
    }
  }
  return resultBundle;
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
function SourceInspectorDrawer({ node, onClose }) {
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
      <aside class="source-inspector-drawer" aria-labelledby="inspector-drawer-title">
        <div class="drawer-header">
          <div>
            <span class="control-label">
              ${formatNodeRole(node.type)}${loc.source_type ? ` · ${loc.source_type}` : ''}
            </span>
            <h2 id="inspector-drawer-title" class="card-heading" style="margin-top: 3px; font-size: 18px;">
              ${node.title}
            </h2>
          </div>
          <button type="button" class="btn btn-icon-only" aria-label="Close source inspector" onClick=${onClose}>
            <${Icon} name="close" />
          </button>
        </div>

        <div class="drawer-body">
          <div class="card-meta-row" style="border-bottom: 1px solid var(--color-border-subtle); padding-bottom: 8px;">
            <span class="arch-stamp ${isCaveatStatus(status) ? 'is-caveat' : ''}">
              ${formatAuditStatus(status)}
              <span class="font-mono-data">${Math.round((audit.score || 1) * 100)}%</span>
            </span>
            <span class="provenance-caption">
              Verified by ${audit.evaluator_type || 'deterministic'} check
            </span>
          </div>

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
              <p class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                ${loc.payload_hash || 'sha256:verified'}
              </p>
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
                <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                  ${loc.payload_hash || 'sha256:verified'}
                </span>
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

          ${loc.source_type === 'markdown' && html`
            <div class="pdf-page-simulator">
              <div class="card-meta-row">
                <span class="control-label">${loc.file_name}</span>
                <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                  ${loc.locator_key || 'BLOCK'}
                </span>
              </div>
              <div class="pdf-bbox-highlight">
                “${node.quote}”
              </div>
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
  if (!isOpen) return null;

  return html`
    <div
      class="inspector-backdrop"
      onClick=${(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside class="source-inspector-drawer" aria-labelledby="review-queue-title">
        <div class="drawer-header">
          <div>
            <span class="control-label">Batch Review Queue</span>
            <h2 id="review-queue-title" class="card-heading" style="margin-top: 3px; font-size: 18px;">
              Queued Notes (${pendingComments.length})
            </h2>
          </div>
          <button type="button" class="btn btn-icon-only" aria-label="Close review queue" onClick=${onClose}>
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
 * Native <dialog> for starting a New Question / Brief, uploading matter files,
 * and managing the Canonical Authorities library.
 */
function AskPipelineDialog({ dialogRef, activeMatterHint, onBundleCreated }) {
  const [matters, setMatters] = useState([]);
  const [canonicalAuths, setCanonicalAuths] = useState([]);
  const [selectedMatter, setSelectedMatter] = useState(activeMatterHint || 'legal_motion_1332');
  const [newMatterName, setNewMatterName] = useState('');
  const [question, setQuestion] = useState('');
  const [bundleSlug, setBundleSlug] = useState('');
  const [progressEvents, setProgressEvents] = useState([]);
  const [running, setRunning] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [showCanonicalMgr, setShowCanonicalMgr] = useState(false);
  const [canonicalDomain, setCanonicalDomain] = useState('legal');
  const [canonicalStatusMsg, setCanonicalStatusMsg] = useState(null);
  const [canonicalBusy, setCanonicalBusy] = useState(false);

  const refreshMatters = useCallback(async () => {
    const res = await fetch('/api/matters');
    if (res.ok) {
      const data = await res.json();
      setMatters(data.matters || []);
      setCanonicalAuths(data.canonical_authorities || []);
      if (data.matters?.length > 0 && !data.matters.some((m) => m.matter_id === selectedMatter)) {
        setSelectedMatter(data.matters[0].matter_id);
      }
    }
  }, [selectedMatter]);

  useEffect(() => {
    refreshMatters();
  }, [refreshMatters]);

  useEffect(() => {
    if (activeMatterHint && matters.some((m) => m.matter_id === activeMatterHint)) {
      setSelectedMatter(activeMatterHint);
    }
  }, [activeMatterHint, matters]);

  const activeMatterObj = matters.find((m) => m.matter_id === selectedMatter);

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
    } else {
      const err = await res.json();
      setErrorMsg(JSON.stringify(err.detail || err));
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file || !selectedMatter) return;
    setUploading(true);
    setErrorMsg(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(`/api/matters/${selectedMatter}/upload`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json();
        setErrorMsg(JSON.stringify(err.detail || err));
      } else {
        await refreshMatters();
      }
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  const handleCanonicalUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setCanonicalBusy(true);
    setErrorMsg(null);
    setCanonicalStatusMsg(null);
    try {
      const formData = new FormData();
      formData.append('domain', canonicalDomain.trim() || 'general');
      formData.append('file', file);
      const res = await fetch('/api/canonical/upload', {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json();
        setErrorMsg(JSON.stringify(err.detail || err));
      } else {
        const data = await res.json();
        setCanonicalAuths(data.authorities || []);
        setCanonicalStatusMsg(
          `Uploaded ${data.uploaded_file} into ${data.domain}/ · ${data.total_authorities} rules active.`
        );
      }
    } finally {
      setCanonicalBusy(false);
      e.target.value = '';
    }
  };

  const handleRebuildCanonical = async (purgeEncoded) => {
    setCanonicalBusy(true);
    setErrorMsg(null);
    setCanonicalStatusMsg(null);
    try {
      const res = await fetch('/api/canonical/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ purge_encoded: Boolean(purgeEncoded) }),
      });
      if (!res.ok) {
        const err = await res.json();
        setErrorMsg(JSON.stringify(err.detail || err));
      } else {
        const data = await res.json();
        setCanonicalAuths(data.authorities || []);
        setCanonicalStatusMsg(
          `Rebuilt index (${data.summary?.files_processed || 0} files -> ${data.total_authorities} authorities).`
        );
      }
    } finally {
      setCanonicalBusy(false);
    }
  };

  const handleRunAsk = async (e) => {
    e.preventDefault();
    if (!question.trim() || !selectedMatter) return;
    setRunning(true);
    setErrorMsg(null);
    setProgressEvents([{ stage: 'init', message: 'Starting analysis pipeline...' }]);

    try {
      const newBundle = await streamAskPipeline({
        matterId: selectedMatter,
        question,
        bundleId: bundleSlug.trim() || null,
        onProgress: (ev) => setProgressEvents((prev) => [...prev, ev]),
      });
      if (newBundle) {
        await onBundleCreated(newBundle);
        setQuestion('');
        setBundleSlug('');
        dialogRef.current?.close();
      }
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setRunning(false);
    }
  };

  return html`
    <dialog
      ref=${dialogRef}
      class="compiler-dialog"
      closedby="any"
      aria-labelledby="ask-dialog-title"
    >
      <div class="dialog-inner">
        <div class="card-meta-row">
          <div>
            <span class="control-label">New Document Brief</span>
            <h2 id="ask-dialog-title" class="card-heading" style="font-size: 18px; margin-top: 2px;">
              Workspace, Files & Controlling Rules
            </h2>
          </div>
          <form method="dialog">
            <button type="submit" class="btn btn-icon-only" aria-label="Close dialog" disabled=${running}>
              <${Icon} name="close" />
            </button>
          </form>
        </div>

        <div class="form-field">
          <label for="matter-select" class="control-label">Matter Workspace</label>
          <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <select
              id="matter-select"
              class="select-control"
              style="flex: 1;"
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
            <input
              type="text"
              class="text-input"
              style="width: 170px;"
              placeholder="New matter slug..."
              value=${newMatterName}
              onInput=${(e) => setNewMatterName(e.target.value)}
            />
            <button type="button" class="btn" onClick=${handleCreateMatter}>
              <${Icon} name="plus" size=${13} />
              Create
            </button>
          </div>
          ${activeMatterObj && html`
            <div class="provenance-caption">
              Files: ${(activeMatterObj.raw_files || []).join(', ') || 'None uploaded yet'}
            </div>
          `}
        </div>

        <div class="form-field">
          <label for="matter-file-upload" class="control-label">
            Upload Matter File (.pdf, .xlsx, .csv, .md)
          </label>
          <input
            id="matter-file-upload"
            type="file"
            accept=".pdf,.xlsx,.xlsm,.csv,.md,.txt"
            disabled=${uploading || running}
            onChange=${handleFileUpload}
          />
          ${uploading && html`<span class="provenance-caption">Indexing uploaded file coordinates…</span>`}
        </div>

        <div class="form-field">
          <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;">
            <div class="provenance-caption">
              <strong>Controlling Rules:</strong> <span class="font-mono-data">${canonicalAuths.length}</span> loaded
            </div>
            <button
              type="button"
              class="btn btn-compact"
              onClick=${() => setShowCanonicalMgr((prev) => !prev)}
            >
              ${showCanonicalMgr ? 'Hide Rule Library' : 'Manage Rule Library'}
            </button>
          </div>

          ${showCanonicalMgr && html`
            <div class="inline-comment-well" style="margin-top: 6px; border: 1px solid var(--color-border-subtle);">
              <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                <label for="canonical-domain-input" class="control-label">Domain</label>
                <input
                  id="canonical-domain-input"
                  type="text"
                  class="text-input"
                  style="width: 130px;"
                  value=${canonicalDomain}
                  onInput=${(e) => setCanonicalDomain(e.target.value)}
                  disabled=${canonicalBusy || running}
                />
                <input
                  id="canonical-file-upload"
                  type="file"
                  accept=".md,.txt,.pdf,.docx"
                  disabled=${canonicalBusy || running}
                  onChange=${handleCanonicalUpload}
                />
              </div>
              <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                <button
                  type="button"
                  class="btn btn-compact"
                  disabled=${canonicalBusy || running}
                  onClick=${() => handleRebuildCanonical(false)}
                >
                  Rebuild Index
                </button>
                <button
                  type="button"
                  class="btn btn-compact"
                  disabled=${canonicalBusy || running}
                  onClick=${() => handleRebuildCanonical(true)}
                >
                  Full Re-encode
                </button>
              </div>
              ${canonicalStatusMsg && html`
                <div class="provenance-caption" style="color: var(--color-emerald-accent);">
                  ${canonicalStatusMsg}
                </div>
              `}
            </div>
          `}
        </div>

        <form onSubmit=${handleRunAsk} style="display: flex; flex-direction: column; gap: 12px;">
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
              ${running ? 'Generating Brief…' : 'Generate Brief'}
            </button>
          </div>
        </form>
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
  const [currentBundleId, setCurrentBundleId] = useState('legal_motion_1332');
  const [bundle, setBundle] = useState(null);
  const [loading, setLoading] = useState(true);

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
  const [followupRunning, setFollowupRunning] = useState(false);
  const [followupStatusMsg, setFollowupStatusMsg] = useState(null);

  // Native <dialog> refs
  const dialogRef = useRef(null);
  const askDialogRef = useRef(null);
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

  useEffect(() => {
    fetchBundlesList();
    fetchMattersList();
    loadBundle('legal_motion_1332');
  }, [fetchBundlesList, fetchMattersList, loadBundle]);

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
        setActionError(JSON.stringify(data.detail || data));
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
      const newBundle = await streamAskPipeline({
        matterId: activeMatterId,
        question: contextualQuestion,
        bundleId: null,
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
            class="btn btn-primary"
            onClick=${() => askDialogRef.current?.showModal()}
          >
            <${Icon} name="plus" size=${13} />
            <span>New Brief</span>
          </button>

          <div class="tools-menu-wrap" ref=${toolsMenuRef}>
            <button
              type="button"
              class="btn btn-icon-only"
              aria-label="Pipeline tools and workspace settings"
              aria-expanded=${toolsMenuOpen}
              onClick=${() => setToolsMenuOpen((v) => !v)}
            >
              <${Icon} name="more" />
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
                    askDialogRef.current?.showModal();
                  }}
                >
                  <div>
                    <div>Corpus & Rule Library</div>
                    <span class="tools-menu-sub">Upload matter files or legal authorities</span>
                  </div>
                </button>
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
                    <span class="tools-menu-sub">Advanced Tier-1 / Tier-2 bundle loader</span>
                  </div>
                </button>
              </div>
            `}
          </div>
        </div>
      </header>

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
            const strokeColor = link.tier === 1 ? roleMeta.stroke : '#4B5563';
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
                  ${Object.entries(bundle.artifact.metadata || {}).map(
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
                      <span>Cross-Section Tension (${ten.severity})</span>
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
            <div class="column-lane lane-analytical">
              <div class="lane-header">
                <span class="lane-title-group">
                  <span class="lane-title">Proof & Reasoning</span>
                  <span class="lane-count">(${level1Nodes.length})</span>
                </span>
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

              <div class="spatial-card-stack">
                <div class="claim-context-bar">
                  <div class="card-meta-row">
                    <span class="control-label">Selected Claim</span>
                    <span class="arch-stamp ${isCaveatStatus(activeClaimNode.audit?.status) ? 'is-caveat' : ''}">
                      ${formatAuditStatus(activeClaimNode.audit?.status || 'verified')}
                    </span>
                  </div>
                  <div class="card-heading">${activeClaimNode.title}</div>
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
      <footer class="document-dock" inert=${Boolean(inspectorNode || queueDrawerOpen)}>
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

      <!-- WORKSPACE / NEW QUESTION / CORPUS DIALOG -->
      <${AskPipelineDialog}
        dialogRef=${askDialogRef}
        activeMatterHint=${activeMatterId}
        onBundleCreated=${async (newBundle) => {
          await fetchBundlesList();
          await fetchMattersList();
          setBundle(newBundle);
          setCurrentBundleId(newBundle.bundle_id);
          setPinnedClaimId(null);
          setExpandedLevel2Ids([]);
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
