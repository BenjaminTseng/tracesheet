import { h, render } from 'preact';
import { useState, useEffect, useRef, useCallback, useMemo } from 'preact/hooks';
import htm from 'htm';

const html = htm.bind(h);

/**
 * Formats an audit status string into a concise label.
 * @param {string} status
 * @returns {string}
 */
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

/**
 * Returns true when an audit status warrants an exception callout (warm ochre caveat).
 * @param {string} status
 * @returns {boolean}
 */
function isCaveatStatus(status) {
  return (
    status === 'extrapolation' ||
    status === 'assumption' ||
    status === 'disputed' ||
    status === 'unverified'
  );
}

/**
 * Formats a locator object into a clean provenance string, separating human labels
 * from quantitative coordinates.
 * @param {object} locator
 * @returns {{ label: string, coord: string }}
 */
function formatProvenanceParts(locator) {
  if (!locator) return { label: 'Internal Graph Node', coord: '' };
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
        label: 'Archival Web Snapshot',
        coord: locator.locator_key || '',
      };
    case 'markdown':
      return {
        label: locator.file_name || 'Document.md',
        coord: locator.locator_key || '',
      };
    default:
      return { label: locator.source_type, coord: '' };
  }
}

/**
 * Parses text containing `<ref id='node_id'>clause</ref>` tags into clean inline
 * interactive highlights without pill badges.
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

    const isDimmed = !matchesFilter;

    const classNames = [
      'clause-highlight',
      isActive ? 'is-active' : '',
      hasCaveat ? 'is-caveat' : '',
      isDimmed ? 'is-dimmed' : '',
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
 * Slide-Over Source Inspector Drawer framed as an Archival Broadsheet Plate.
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
      <aside
        class="source-inspector-drawer"
        aria-labelledby="inspector-drawer-title"
      >
        <div class="drawer-header">
          <div>
            <div class="card-meta-row">
              <span class="kicker-label">
                ▪ ${node.type}${loc.source_type ? ` · ${loc.source_type}` : ''}
              </span>
            </div>
            <h2 id="inspector-drawer-title" class="card-heading" style="margin-top: 3px; font-size: 18px;">
              ${node.title}
            </h2>
          </div>
          <button type="button" class="btn" onClick=${onClose}>
            Close
          </button>
        </div>

        <div class="drawer-body">
          <div class="card-meta-row" style="border-bottom: 1px solid var(--color-border-subtle); padding-bottom: 8px;">
            <span class="arch-stamp ${isCaveatStatus(status) ? 'is-caveat' : ''}">
              ▪ ${formatAuditStatus(status)}
              <span class="font-mono-data">${Math.round((audit.score || 1) * 100)}%</span>
            </span>
            <span class="kicker-label">
              Evaluator: ${audit.evaluator_type || 'deterministic'}
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
                <span class="kicker-label">${loc.file_name}</span>
                <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                  PAGE ${loc.page || 1}
                </span>
              </div>
              <p class="provenance-caption">
                Section Locator: ${loc.locator_key || 'Verified Excerpt'}
              </p>
              <div class="pdf-bbox-highlight">
                <div class="font-mono-data" style="font-size: 10.5px; color: var(--color-accent-primary); margin-bottom: 4px;">
                  BBOX [${(loc.bounding_box || [0, 0, 0, 0]).join(', ')}]
                </div>
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
                <span class="kicker-label kicker-emerald">▪ Workbook: ${loc.file_name}</span>
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
                  <span class="kicker-label">Captured API Response Payload</span>
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
                <figcaption class="evidence-figcaption">
                  <span class="kicker-label">Read-Only Verification Query</span>
                </figcaption>
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
                <figcaption class="evidence-figcaption">
                  <cite>${node.title}</cite>
                  ${loc.url && html`
                    <a
                      href=${loc.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      class="external-link"
                    >
                      Open Source URL ↗
                    </a>
                  `}
                </figcaption>
              </figure>
            </div>
          `}

          ${loc.source_type === 'markdown' && html`
            <div class="pdf-page-simulator">
              <div class="card-meta-row">
                <span class="kicker-label">${loc.file_name}</span>
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
                  <cite>${node.title}</cite>
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
 * Reusable Antigravity-style inline comment thread & composer anchored to a node.
 */
function InlineCommentPanel({
  node,
  comments,
  isOpen,
  onClose,
  onSubmit,
  onDelete,
  submitting,
}) {
  const [draftText, setDraftText] = useState('');
  const [suggestedStatus, setSuggestedStatus] = useState('');

  const nodeComments = (comments || []).filter((c) => c.node_id === node.id);

  const handleSave = async (e) => {
    e.preventDefault();
    if (!draftText.trim()) return;
    await onSubmit({
      node_id: node.id,
      section_id: node.section_id,
      comment_text: draftText.trim(),
      suggested_status: suggestedStatus || null,
    });
    setDraftText('');
    setSuggestedStatus('');
    onClose();
  };

  if (nodeComments.length === 0 && !isOpen) return null;

  return html`
    <div class="inline-comment-well">
      ${nodeComments.length > 0 && html`
        <div class="comment-thread-list">
          ${nodeComments.map(
            (c) => html`
              <div key=${c.comment_id} class="comment-item ${c.resolved ? 'is-resolved' : ''}">
                <div class="card-meta-row">
                  <span class="kicker-label">
                    ${c.resolved ? '▪ Resolved Feedback' : '▪ Queued Review Note'}
                    ${c.suggested_status ? ` · ${formatAuditStatus(c.suggested_status)}` : ''}
                  </span>
                  ${!c.resolved && html`
                    <button
                      type="button"
                      class="btn-link"
                      onClick=${() => onDelete(c.comment_id)}
                    >
                      × Remove
                    </button>
                  `}
                </div>
                <p class="comment-item-text">${c.comment_text}</p>
              </div>
            `
          )}
        </div>
      `}

      ${isOpen && html`
        <form onSubmit=${handleSave} style="display: flex; flex-direction: column; gap: 8px;">
          <label for=${`cmt-input-${node.id}`} class="control-label">
            Add Feedback for Regeneration
          </label>
          <textarea
            id=${`cmt-input-${node.id}`}
            class="comment-textarea"
            placeholder="E.g., Check board minutes for treasury location, or soften to extrapolation..."
            value=${draftText}
            onInput=${(e) => setDraftText(e.target.value)}
            required
          ></textarea>
          <div class="card-meta-row" style="flex-wrap: wrap;">
            <select
              class="select-control"
              aria-label="Optional audit status override"
              value=${suggestedStatus}
              onChange=${(e) => setSuggestedStatus(e.target.value)}
            >
              <option value="">Keep / Auto-Detect Status</option>
              <option value="verified">Mark as Verified</option>
              <option value="extrapolation">Flag as Extrapolation</option>
              <option value="assumption">Flag as Assumption</option>
              <option value="disputed">Flag as Disputed</option>
            </select>
            <div style="display: flex; gap: 6px;">
              <button type="button" class="btn" onClick=${onClose}>
                Cancel
              </button>
              <button type="submit" class="btn btn-primary" disabled=${submitting}>
                ${submitting ? 'Saving…' : 'Queue Comment'}
              </button>
            </div>
          </div>
        </form>
      `}
    </div>
  `;
}

/**
 * Renders an individual reasoning, evidence, authority, calculation, or assumption node
 * framed as an Economist / Broadsheet Editorial Plate (ben-design-prefs Section 4).
 */
function SpatialNodeCard({
  node,
  plateIndexLabel,
  level,
  nodesMap,
  activeNodeIds,
  expandedLevel2Ids,
  tensionClaimIds,
  auditFilter,
  comments,
  commentingNodeId,
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
  const sourceTypeLabel = node.locator?.source_type ? ` · ${node.locator.source_type}` : '';
  const provenance = formatProvenanceParts(node.locator);

  const isFinancial =
    node.type === 'calculation' || node.locator?.source_type === 'spreadsheet';
  const isAuthority = node.type === 'authority';

  const plateToneClass = isFinancial
    ? 'plate-financial'
    : isAuthority
    ? 'plate-authority'
    : '';

  const kickerToneClass = isFinancial
    ? 'kicker-emerald'
    : isAuthority
    ? 'kicker-copper'
    : '';

  const nodeComments = (comments || []).filter((c) => c.node_id === node.id);
  const pendingCount = nodeComments.filter((c) => !c.resolved).length;
  const isCommentOpen = commentingNodeId === node.id;

  return html`
    <article
      class="spatial-node-card ${plateToneClass} ${isFocused ? 'is-focused' : ''}"
      data-card-node-id=${node.id}
      data-card-level=${level}
    >
      <!-- Broadsheet Plate Header Strip -->
      <div class="plate-header-strip">
        <span class="lane-title-group">
          <span class="lane-index">${plateIndexLabel}</span>
          <span class="kicker-label ${kickerToneClass}">
            · ${node.type}${sourceTypeLabel}
          </span>
        </span>
        <span class="arch-stamp ${isCaveatStatus(status) ? 'is-caveat' : ''}">
          ${isCaveatStatus(status) ? '▪ ' : ''}${formatAuditStatus(status)}
        </span>
      </div>

      <!-- Crisp #FFFFFF Plate Stage -->
      <div class="plate-body-stage">
        <h3 class="card-heading">${node.title}</h3>

        ${node.quote && html`
          <figure class="evidence-figure">
            <blockquote
              class="evidence-blockquote"
              cite=${node.url || node.locator?.url || ''}
            >
              “${node.quote}”
            </blockquote>
            <figcaption class="evidence-figcaption">
              <cite>${node.locator?.file_name || node.title}</cite>
              ${node.url && html`
                <a
                  href=${node.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  class="external-link"
                >
                  Authority Link ↗
                </a>
              `}
            </figcaption>
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

        ${node.audit && node.audit.evaluator_note && node.audit.evaluator_note !== 'Deterministic node compilation' && html`
          <div class="card-evaluator-note">
            <span class="kicker-label">Audit Note (${node.audit.evaluator_type || 'llm'})</span>
            <span>${node.audit.evaluator_note}</span>
          </div>
        `}
      </div>

      <!-- Plate Provenance Footer Line -->
      <div class="plate-footer-row">
        <span class="provenance-caption">
          ${node.locator ? html`
            <span>${provenance.label}</span>
            ${provenance.coord && html`
              <span class="font-mono-data" style="margin-left: 6px;">${provenance.coord}</span>
            `}
          ` : html`
            <span class="font-mono-data">${node.id}</span>
          `}
        </span>

        <div style="display: flex; align-items: center; gap: 12px;">
          <button
            type="button"
            class="btn-link"
            onClick=${() => onToggleComment(isCommentOpen ? null : node.id)}
          >
            ${isCommentOpen
              ? 'Close Note'
              : pendingCount > 0
              ? `Comment (${pendingCount})`
              : 'Comment'}
          </button>
          ${(node.locator || node.url || node.quote) && html`
            <button
              type="button"
              class="btn-link"
              onClick=${() => onOpenInspector(node)}
            >
              Inspect Source
            </button>
          `}
          ${hasChildren && html`
            <button
              type="button"
              class="btn-link"
              onClick=${() => onToggleSubtree(node)}
            >
              ${areChildrenExpanded
                ? `Hide Backing (${childIds.length})`
                : `View Backing (${childIds.length}) →`}
            </button>
          `}
        </div>
      </div>

      <${InlineCommentPanel}
        node=${node}
        comments=${comments}
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
 * Slide-Over Batch Review Queue Drawer allowing reviewers to jump to anchored nodes
 * or remove comments before clicking Apply Feedback & Re-compile.
 */
function ReviewQueueDrawer({
  isOpen,
  pendingComments,
  nodesMap,
  onClose,
  onJumpToNode,
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
            <span class="kicker-label kicker-accent">▪ Antigravity-Style Batch Review Queue</span>
            <h2 id="review-queue-title" class="card-heading" style="margin-top: 3px; font-size: 18px;">
              Queued Review Notes (${pendingComments.length})
            </h2>
          </div>
          <button type="button" class="btn" onClick=${onClose}>Close</button>
        </div>

        <div class="drawer-body">
          <p class="provenance-caption">
            Reviewers can anchor feedback across any L0 claim or L1/L2+ support plate.
            Applying feedback triages each section: prose/caveat edits re-run Stage 3→4,
            while factual requests trigger Stage 2 re-harvesting.
          </p>

          ${pendingComments.length === 0 ? html`
            <p class="card-body-prose" style="color: var(--color-text-muted);">
              No pending comments queued. Click any claim or support plate and select “Comment”.
            </p>
          ` : html`
            <div class="comment-thread-list">
              ${pendingComments.map((c) => {
                const targetNode = nodesMap[c.node_id];
                return html`
                  <div key=${c.comment_id} class="comment-item">
                    <div class="card-meta-row">
                      <span class="kicker-label">
                        ${targetNode ? `${targetNode.type} · ${targetNode.title}` : c.node_id}
                      </span>
                      <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                        ${c.section_id}
                      </span>
                    </div>
                    <p class="comment-item-text">${c.comment_text}</p>
                    <div class="card-meta-row" style="margin-top: 4px;">
                      <button
                        type="button"
                        class="btn-link"
                        onClick=${() => {
                          onJumpToNode(c.node_id);
                          onClose();
                        }}
                      >
                        Jump to Node →
                      </button>
                      <button
                        type="button"
                        class="btn-link"
                        onClick=${() => onDeleteComment(c.comment_id)}
                      >
                        × Remove
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
                : `Apply Feedback & Re-compile (${pendingComments.length}) →`}
            </button>
          `}
        </div>
      </aside>
    </div>
  `;
}

/**
 * Native <dialog> for selecting/creating a Project Matter, uploading inputs (a),
 * inspecting canonical authorities (b), and running the 4-stage pipeline for question (c).
 */
function AskPipelineDialog({ dialogRef, onBundleCreated }) {
  const [matters, setMatters] = useState([]);
  const [canonicalAuths, setCanonicalAuths] = useState([]);
  const [selectedMatter, setSelectedMatter] = useState('legal_motion_1332');
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
          `Uploaded ${data.uploaded_file} into ${data.domain}/ · ${data.total_authorities} [AUTH:...] anchors active in INDEX.md.`
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
          `Rebuilt canonical/INDEX.md (${data.summary?.files_processed || 0} raw files → ${data.total_authorities} authorities).`
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
    setProgressEvents([{ stage: 'init', message: 'Starting 4-stage pipeline...' }]);

    try {
      const res = await fetch(`/api/matters/${selectedMatter}/ask/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: question.trim(),
          bundle_id: bundleSlug.trim() || null,
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
            setProgressEvents((prev) => [...prev, { stage: evt.stage, message: evt.message }]);
          } else if (evt.event === 'error') {
            throw new Error(evt.detail || 'Pipeline failed');
          } else if (evt.event === 'bundle') {
            await onBundleCreated(evt.bundle);
            dialogRef.current?.close();
          }
        }
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
            <span class="kicker-label kicker-accent">▪ Agentic Q&A Pipeline (Stages 1 → 4)</span>
            <h2 id="ask-dialog-title" class="card-heading" style="font-size: 18px; margin-top: 2px;">
              Ask Question Against Project & Canonical Corpus
            </h2>
          </div>
          <form method="dialog">
            <button type="submit" class="btn" disabled=${running}>Close</button>
          </form>
        </div>

        <div class="form-field">
          <label for="matter-select" class="control-label">1. Project / Matter (a)</label>
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
              + Create
            </button>
          </div>
          ${activeMatterObj && html`
            <div class="provenance-caption">
              Raw files: ${(activeMatterObj.raw_files || []).join(', ') || 'None yet'}
            </div>
          `}
        </div>

        <div class="form-field">
          <label for="matter-file-upload" class="control-label">
            Upload Task Input (.pdf, .xlsx, .csv, .md)
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
              <strong>Canonical Authorities (b):</strong> <span class="font-mono-data">${canonicalAuths.length}</span> loaded
              from <code class="font-mono-data">canonical/INDEX.md</code>
              (${canonicalAuths.slice(0, 3).map((a) => a.auth_id).join(', ')}${canonicalAuths.length > 3 ? '…' : ''})
            </div>
            <button
              type="button"
              class="btn"
              onClick=${() => setShowCanonicalMgr((prev) => !prev)}
            >
              ${showCanonicalMgr ? 'Hide Canonical Manager' : 'Manage Canonical Corpus (b)'}
            </button>
          </div>

          ${showCanonicalMgr && html`
            <div class="inline-comment-composer" style="margin-top: 6px;">
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
                  accept=".md,.txt,.pdf,.docx,.xlsx,.xlsm,.csv"
                  disabled=${canonicalBusy || running}
                  onChange=${handleCanonicalUpload}
                />
              </div>
              <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                <button
                  type="button"
                  class="btn"
                  disabled=${canonicalBusy || running}
                  onClick=${() => handleRebuildCanonical(false)}
                >
                  Rebuild INDEX.md
                </button>
                <button
                  type="button"
                  class="btn"
                  disabled=${canonicalBusy || running}
                  onClick=${() => handleRebuildCanonical(true)}
                >
                  Purge Encoded & Rebuild
                </button>
                ${canonicalStatusMsg && html`<span class="provenance-caption">${canonicalStatusMsg}</span>`}
              </div>
            </div>
          `}
        </div>

        <form onSubmit=${handleRunAsk} style="display: flex; flex-direction: column; gap: 10px;">
          <div class="form-field">
            <label for="ask-question-input" class="control-label">2. Analytical Question (c)</label>
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
            <label for="ask-bundle-slug" class="control-label">Optional Output Bundle Slug</label>
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
              ${running ? 'Running 4-Stage Pipeline…' : 'Run 4-Stage Pipeline →'}
            </button>
          </div>
        </form>
      </div>
    </dialog>
  `;
}

/**
 * Main Application Component.
 * Follows the `ben-design-prefs` Swiss Quantitative Broadsheet + Archival Press system,
 * starting cleanly at L0 and expanding progressively to L1 and L2+ on click.
 */
function App() {
  const [bundlesList, setBundlesList] = useState([]);
  const [currentBundleId, setCurrentBundleId] = useState('legal_motion_1332');
  const [bundle, setBundle] = useState(null);
  const [loading, setLoading] = useState(true);

  // Progressive spatial expansion state (starts at L0 only)
  const [pinnedClaimId, setPinnedClaimId] = useState(null);
  const [expandedLevel2Ids, setExpandedLevel2Ids] = useState([]);
  const [hoveredRef, setHoveredRef] = useState(null);
  const [auditFilter, setAuditFilter] = useState('all');
  const [inspectorNode, setInspectorNode] = useState(null);

  // Antigravity-style inline review & batch regeneration state
  const [commentingNodeId, setCommentingNodeId] = useState(null);
  const [submittingComment, setSubmittingComment] = useState(false);
  const [queueDrawerOpen, setQueueDrawerOpen] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [expandedTraceSections, setExpandedTraceSections] = useState(() => ({}));

  // Native <dialog> refs for JSON compiler and Ask Pipeline modal
  const dialogRef = useRef(null);
  const askDialogRef = useRef(null);
  const [compilerJsonText, setCompilerJsonText] = useState(
    JSON.stringify(SAMPLE_TIER1_COMPILE_PAYLOAD, null, 2)
  );
  const [compilerError, setCompilerError] = useState(null);

  // Viewport ref and computed SVG Bezier paths
  const viewportRef = useRef(null);
  const [bezierLinks, setBezierLinks] = useState([]);

  const fetchBundlesList = useCallback(async () => {
    const res = await fetch('/api/bundles');
    if (res.ok) {
      const data = await res.json();
      setBundlesList(data);
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
        // Start with only L0 visible; L1 and L2+ expand only when clicked
        setPinnedClaimId(null);
        setExpandedLevel2Ids([]);
        setHoveredRef(null);
        setInspectorNode(null);
        setExpandedTraceSections({});
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBundlesList();
    loadBundle('legal_motion_1332');
  }, [fetchBundlesList, loadBundle]);

  // Progressive Escape key handling: close Drawer/Queue/Comment -> close L2+ -> close L1
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key !== 'Escape') return;
      if (queueDrawerOpen) {
        setQueueDrawerOpen(false);
      } else if (inspectorNode) {
        setInspectorNode(null);
      } else if (commentingNodeId) {
        setCommentingNodeId(null);
      } else if (expandedLevel2Ids.length > 0) {
        setExpandedLevel2Ids([]);
      } else if (pinnedClaimId) {
        setPinnedClaimId(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [queueDrawerOpen, inspectorNode, commentingNodeId, expandedLevel2Ids, pinnedClaimId]);

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

  // L1 only opens when a claim in L0 is explicitly clicked (pinnedClaimId)
  const activeClaimNode = pinnedClaimId ? nodesMap[pinnedClaimId] : null;

  const level1Nodes = useMemo(() => {
    if (!activeClaimNode) return [];
    return (activeClaimNode.direct_child_ids || [])
      .map((id) => nodesMap[id])
      .filter(Boolean);
  }, [activeClaimNode, nodesMap]);

  // L2+ only opens when a sub-citation or "View Backing" inside L1/L2 is clicked
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

  // Clicking a `<ref id="...">` at L0 opens L1; clicking inside L1/L2 opens L2+
  const handleClickRef = useCallback(
    (targetNodeId, level) => {
      const targetNode = nodesMap[targetNodeId];
      if (!targetNode) return;

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

  // Recompute SVG Bezier connector lines between visible columns
  const recomputeConnectors = useCallback(() => {
    const container = viewportRef.current;
    if (!container || !showL1) {
      setBezierLinks([]);
      return;
    }
    const containerRect = container.getBoundingClientRect();
    const links = [];

    // 1. Connect active Claim span in L0 -> L1 plates in Column 2
    if (pinnedClaimId) {
      const claimBtn = container.querySelector(
        `button[data-ref-node-id="${pinnedClaimId}"][data-ref-level="0"]`
      );
      if (claimBtn) {
        const srcRect = claimBtn.getBoundingClientRect();
        const x1 = srcRect.right - containerRect.left;
        const y1 = srcRect.top + srcRect.height / 2 - containerRect.top;

        for (const l1Node of level1Nodes) {
          const targetCard = container.querySelector(
            `article[data-card-node-id="${l1Node.id}"]`
          );
          if (targetCard) {
            const tgtRect = targetCard.getBoundingClientRect();
            const x2 = tgtRect.left - containerRect.left;
            const y2 = tgtRect.top + 18 - containerRect.top;
            const dx = Math.max(32, (x2 - x1) * 0.5);
            links.push({
              id: `${pinnedClaimId}->${l1Node.id}`,
              d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
              x1,
              y1,
              x2,
              y2,
              tier: 1,
            });
          }
        }
      }
    }

    // 2. Connect L1 inline sub-refs (or parent plates) -> L2+ plates in Column 3
    if (showL2) {
      for (const l2Node of level2PlusNodes) {
        const targetCard = container.querySelector(
          `article[data-card-node-id="${l2Node.id}"]`
        );
        if (!targetCard) continue;
        const tgtRect = targetCard.getBoundingClientRect();
        const x2 = tgtRect.left - containerRect.left;
        const y2 = tgtRect.top + 18 - containerRect.top;

        const inlineTrigger = container.querySelector(
          `article .clause-highlight[data-ref-node-id="${l2Node.id}"]`
        );
        const parentL1 = !inlineTrigger
          ? level1Nodes.find((n) => (n.direct_child_ids || []).includes(l2Node.id))
          : null;
        const fallbackParentCard = parentL1
          ? container.querySelector(`article[data-card-node-id="${parentL1.id}"]`)
          : null;

        const srcEl = inlineTrigger || fallbackParentCard;
        if (srcEl) {
          const srcRect = srcEl.getBoundingClientRect();
          const x1 = srcRect.right - containerRect.left;
          const y1 = srcRect.top + srcRect.height / 2 - containerRect.top;
          const dx = Math.max(32, Math.abs(x2 - x1) * 0.5);
          links.push({
            id: `sub->${l2Node.id}`,
            d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
            x1,
            y1,
            x2,
            y2,
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
    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener('resize', recomputeConnectors);
      window.removeEventListener('scroll', recomputeConnectors);
    };
  }, [recomputeConnectors]);

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
    async ({ node_id, section_id, comment_text, suggested_status }) => {
      if (!currentBundleId) return;
      setSubmittingComment(true);
      setActionError(null);
      try {
        const res = await fetch(`/api/bundles/${currentBundleId}/comments`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ node_id, section_id, comment_text, suggested_status }),
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
      setCommentingNodeId(null);
      await fetchBundlesList();
    } catch (err) {
      setActionError(err.message);
    } finally {
      setRegenerating(false);
    }
  }, [currentBundleId, fetchBundlesList]);

  const handleJumpToNode = useCallback(
    (nodeId) => {
      const target = nodesMap[nodeId];
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
  const affectedSectionsCount = new Set(pendingComments.map((c) => c.section_id)).size;

  return html`
    <div class="app-shell">
      <header class="top-bar" inert=${Boolean(inspectorNode)}>
        <div class="top-bar-left">
          <span class="brand-title">Audit-Grounded Document Canvas</span>
          <span class="divider-vertical" aria-hidden="true"></span>
          <div class="control-group">
            <label for="bundle-selector" class="control-label">Matter / File</label>
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
          <div class="telemetry-summary" aria-label="Document audit summary">
            <span class="telemetry-stat">
              <span class="square-marker" aria-hidden="true">▪</span>
              <span class="font-mono-data">${summary.total_claims || 0}</span>
              <span>Claims (<span class="font-mono-data">${summary.verified_count || 0}</span> Verified)</span>
            </span>
            ${caveatCount > 0 && html`
              <span class="telemetry-stat">
                <span class="square-marker square-warning" aria-hidden="true">▪</span>
                <span class="font-mono-data">${caveatCount}</span>
                <span>Caveat${caveatCount === 1 ? '' : 's'}</span>
              </span>
            `}
            ${tensionCount > 0 && html`
              <span class="telemetry-stat">
                <span class="square-marker square-danger" aria-hidden="true">▪</span>
                <span class="font-mono-data">${tensionCount}</span>
                <span>Tension${tensionCount === 1 ? '' : 's'}</span>
              </span>
            `}
          </div>

          <span class="divider-vertical" aria-hidden="true"></span>

          <div class="control-group">
            <label for="highlight-filter" class="control-label">Highlight</label>
            <select
              id="highlight-filter"
              class="select-control"
              value=${auditFilter}
              onChange=${(e) => setAuditFilter(e.target.value)}
            >
              <option value="all">All Cited Clauses</option>
              <option value="caveats">Caveats & Assumptions Only</option>
              ${tensionCount > 0 && html`
                <option value="tension">Cross-Section Tensions Only</option>
              `}
            </select>
          </div>

          <button
            type="button"
            class="btn btn-primary"
            onClick=${() => askDialogRef.current?.showModal()}
          >
            Ask Question
          </button>

          <button
            type="button"
            class="btn"
            onClick=${() => {
              setCompilerError(null);
              dialogRef.current?.showModal();
            }}
          >
            Compile / Load JSON
          </button>
        </div>
      </header>

      <main
        id="workspace-main"
        tabindex="-1"
        class="spatial-viewport"
        ref=${viewportRef}
        inert=${Boolean(inspectorNode)}
      >
        <svg class="connector-svg-layer" aria-hidden="true">
          ${bezierLinks.map(
            (link) => html`
              <g key=${link.id}>
                <path
                  d=${link.d}
                  fill="none"
                  stroke=${link.tier === 1 ? '#14284B' : '#4B5563'}
                  stroke-width="1.5"
                  opacity="0.8"
                />
                <rect
                  x=${link.x1 - 2.5}
                  y=${link.y1 - 2.5}
                  width="5"
                  height="5"
                  fill=${link.tier === 1 ? '#14284B' : '#4B5563'}
                />
                <rect
                  x=${link.x2 - 2.5}
                  y=${link.y2 - 2.5}
                  width="5"
                  height="5"
                  fill=${link.tier === 1 ? '#14284B' : '#4B5563'}
                />
              </g>
            `
          )}
        </svg>

        <div class="bounded-canvas-grid ${gridColsClass}">
          <!-- COLUMN 1 (L0): SYNTHESIZED ARTIFACT PLATE (Always Visible) -->
          <div class="column-lane">
            <div class="lane-header">
              <span class="lane-title-group">
                <span class="lane-index">L0</span>
                <span class="lane-title">· Synthesized Document</span>
              </span>
              <span class="lane-caption">
                ${showL1
                  ? 'Click active clause or × Close L1 to collapse'
                  : 'Click any highlighted clause to inspect primary support →'}
              </span>
            </div>

            <article class="artifact-sheet">
              <div class="artifact-header">
                <h1 class="artifact-title">${bundle.artifact.title}</h1>
                <div class="artifact-meta-ledger">
                  <span class="meta-pair">
                    <span class="kicker-label">Version</span>
                    <span class="font-mono-data">${bundle.artifact.version}</span>
                  </span>
                  ${Object.entries(bundle.artifact.metadata || {}).map(
                    ([k, v]) => html`
                      <span key=${k} class="meta-pair">
                        <span class="kicker-label">${k.replace(/_/g, ' ')}</span>
                        <span>${v}</span>
                      </span>
                    `
                  )}
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
                    <div
                      class="tension-callout-header ${ten.severity === 'warning' ? 'is-warning' : ''}"
                    >
                      <span>
                        ▪ Cross-Section Tension Flagged (${ten.severity})
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
                            ${pinnedClaimId === cid ? 'Viewing' : 'Inspect'} “${cNode ? cNode.title : cid}” →
                          </button>
                        `;
                      })}
                    </div>
                  </div>
                `
              )}

              ${(bundle.artifact.sections || []).map((sec, idx) => {
                const sa = bundle.stage_artifacts || {};
                const outlineSec = ((sa.outline_plan && sa.outline_plan.sections) || []).find(
                  (s) => s.section_id === sec.section_id
                );
                const ledgerSec = (sa.ledgers && sa.ledgers[sec.section_id]) || null;
                const draftSec = (sa.sections || []).find((s) => s.section_id === sec.section_id);
                const auditSec = (sa.audits && sa.audits[sec.section_id]) || null;
                const hasTrace = Boolean(outlineSec || ledgerSec || draftSec || auditSec);
                const isTraceOpen = Boolean(expandedTraceSections[sec.section_id]);

                return html`
                  <section key=${sec.section_id} class="artifact-section">
                    <div class="card-meta-row">
                      <h2 class="section-heading">${sec.section_title}</h2>
                      <div style="display: flex; align-items: center; gap: 10px;">
                        ${hasTrace && html`
                          <button
                            type="button"
                            class="btn-link"
                            onClick=${() =>
                              setExpandedTraceSections((prev) => ({
                                ...prev,
                                [sec.section_id]: !prev[sec.section_id],
                              }))
                            }
                          >
                            ${isTraceOpen ? '▾ Hide Stage Trace' : '▪ Stage Trace (1–4)'}
                          </button>
                        `}
                        <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                          SEC. 0${idx + 1}
                        </span>
                      </div>
                    </div>

                    ${hasTrace && isTraceOpen && html`
                      <div class="stage-trace-drawer">
                        ${outlineSec && html`
                          <div class="stage-trace-row">
                            <span class="kicker-label kicker-accent">Stage 1 · Architect Plan & Routing</span>
                            <div><strong>Intention:</strong> ${outlineSec.stated_intention}</div>
                            ${outlineSec.routing_rationale && html`
                              <div><strong>Rationale:</strong> ${outlineSec.routing_rationale}</div>
                            `}
                            <div class="provenance-caption">
                              ${(outlineSec.governing_authorities || []).length > 0
                                ? `Authorities: ${outlineSec.governing_authorities.map((a) => `[${a.auth_id}]`).join(', ')}`
                                : 'No canonical authorities assigned (grounded in L1 evidence & commonsense/arithmetic)'}
                            </div>
                          </div>
                        `}
                        ${ledgerSec && html`
                          <div class="stage-trace-row">
                            <span class="kicker-label">Stage 2 · Evidence Harvest</span>
                            <div>
                              ${ledgerSec.harvest_summary ||
                                `Collected ${(ledgerSec.verified_facts || []).length} verified fact(s) and ${(ledgerSec.unresolved_gaps || []).length} unresolved gap(s).`}
                            </div>
                            <div class="provenance-caption">
                              Facts verified: ${(ledgerSec.verified_facts || []).length} · Unresolved gaps: ${(ledgerSec.unresolved_gaps || []).length}
                              ${(ledgerSec.additional_authorities || []).length > 0
                                ? ` · Discovered rules: ${ledgerSec.additional_authorities.map((a) => `[${a.auth_id}]`).join(', ')}`
                                : ''}
                            </div>
                          </div>
                        `}
                        ${draftSec && html`
                          <div class="stage-trace-row">
                            <span class="kicker-label">Stage 3 · Drafting Synthesis</span>
                            <div>
                              ${draftSec.drafting_notes ||
                                'Compiled section prose and structured support cards under closed-world verification.'}
                            </div>
                          </div>
                        `}
                        ${auditSec && html`
                          <div class="stage-trace-row">
                            <span class="kicker-label">Stage 4 · Independent Audit Gate</span>
                            <div class="stage-trace-checks">
                              <span class="arch-stamp ${auditSec.check_a_relevance ? '' : 'is-danger'}">
                                Check A Relevance: ${auditSec.check_a_relevance ? 'PASS' : 'FAIL'}
                              </span>
                              <span class="arch-stamp ${auditSec.check_b_congruence ? '' : 'is-danger'}">
                                Check B Congruence: ${auditSec.check_b_congruence ? 'PASS' : 'FAIL'}
                              </span>
                              <span class="arch-stamp ${auditSec.check_c_intent ? '' : 'is-caveat'}">
                                Check C Intent: ${auditSec.check_c_intent ? 'PASS' : 'FAIL'}
                              </span>
                            </div>
                            ${auditSec.audit_rationale && html`
                              <div>${auditSec.audit_rationale}</div>
                            `}
                          </div>
                        `}
                      </div>
                    `}

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
                  </section>
                `;
              })}
            </article>
          </div>

          <!-- COLUMN 2 (L1): PRIMARY REASONING & EVIDENCE PLATES (Rendered only when an L0 clause is clicked) -->
          ${showL1 && html`
            <div class="column-lane lane-analytical">
              <div class="lane-header">
                <span class="lane-title-group">
                  <span class="lane-index">L1</span>
                  <span class="lane-title">· Primary Support</span>
                  <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                    (${level1Nodes.length})
                  </span>
                </span>
                <button
                  type="button"
                  class="btn-link"
                  onClick=${() => {
                    setPinnedClaimId(null);
                    setExpandedLevel2Ids([]);
                  }}
                >
                  × Close L1
                </button>
              </div>

              <div class="spatial-card-stack">
                <div class="claim-context-bar">
                  <div class="card-meta-row">
                    <span class="kicker-label kicker-accent">▪ Selected Claim</span>
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <button
                        type="button"
                        class="btn-link"
                        onClick=${() =>
                          setCommentingNodeId(
                            commentingNodeId === activeClaimNode.id ? null : activeClaimNode.id
                          )
                        }
                      >
                        ${commentingNodeId === activeClaimNode.id
                          ? 'Close Note'
                          : '+ Comment on Claim'}
                      </button>
                      <span
                        class="arch-stamp ${isCaveatStatus(activeClaimNode.audit?.status) ? 'is-caveat' : ''}"
                      >
                        ${isCaveatStatus(activeClaimNode.audit?.status) ? '▪ ' : ''}
                        ${formatAuditStatus(activeClaimNode.audit?.status || 'verified')}
                      </span>
                    </div>
                  </div>
                  <div class="card-heading">${activeClaimNode.title}</div>
                  ${activeClaimNode.audit?.evaluator_note && html`
                    <div class="provenance-caption">
                      ${activeClaimNode.audit.evaluator_note}
                    </div>
                  `}
                  <${InlineCommentPanel}
                    node=${activeClaimNode}
                    comments=${allComments}
                    isOpen=${commentingNodeId === activeClaimNode.id}
                    onClose=${() => setCommentingNodeId(null)}
                    onSubmit=${handleSubmitComment}
                    onDelete=${handleDeleteComment}
                    submitting=${submittingComment}
                  />
                </div>

                ${level1Nodes.map(
                  (node, idx) => html`
                    <${SpatialNodeCard}
                      key=${node.id}
                      node=${node}
                      plateIndexLabel=${`FIG. 1.${idx + 1}`}
                      level=${1}
                      nodesMap=${nodesMap}
                      activeNodeIds=${activeNodeIds}
                      expandedLevel2Ids=${expandedLevel2Ids}
                      tensionClaimIds=${tensionClaimIds}
                      auditFilter=${auditFilter}
                      comments=${allComments}
                      commentingNodeId=${commentingNodeId}
                      onToggleComment=${setCommentingNodeId}
                      onSubmitComment=${handleSubmitComment}
                      onDeleteComment=${handleDeleteComment}
                      submittingComment=${submittingComment}
                      onHoverRef=${handleHoverRef}
                      onLeaveRef=${handleLeaveRef}
                      onClickRef=${handleClickRef}
                      onToggleSubtree=${handleToggleSubtree}
                      onOpenInspector=${setInspectorNode}
                      isFocused=${hoveredRef?.nodeId === node.id}
                    />
                  `
                )}
              </div>
            </div>
          `}

          <!-- COLUMN 3 (L2+): BACKING AUTHORITIES & SUB-CITATIONS PLATES (Rendered only when an L1 sub-citation is clicked) -->
          ${showL2 && html`
            <div class="column-lane lane-analytical">
              <div class="lane-header">
                <span class="lane-title-group">
                  <span class="lane-index">L2+</span>
                  <span class="lane-title">· Backing Authorities</span>
                  <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                    (${level2PlusNodes.length})
                  </span>
                </span>
                <button
                  type="button"
                  class="btn-link"
                  onClick=${() => setExpandedLevel2Ids([])}
                >
                  × Close L2+
                </button>
              </div>

              <div class="spatial-card-stack">
                ${level2PlusNodes.map(
                  (node, idx) => html`
                    <${SpatialNodeCard}
                      key=${node.id}
                      node=${node}
                      plateIndexLabel=${`FIG. 2.${idx + 1}`}
                      level=${2}
                      nodesMap=${nodesMap}
                      activeNodeIds=${activeNodeIds}
                      expandedLevel2Ids=${expandedLevel2Ids}
                      tensionClaimIds=${tensionClaimIds}
                      auditFilter=${auditFilter}
                      comments=${allComments}
                      commentingNodeId=${commentingNodeId}
                      onToggleComment=${setCommentingNodeId}
                      onSubmitComment=${handleSubmitComment}
                      onDeleteComment=${handleDeleteComment}
                      submittingComment=${submittingComment}
                      onHoverRef=${handleHoverRef}
                      onLeaveRef=${handleLeaveRef}
                      onClickRef=${handleClickRef}
                      onToggleSubtree=${handleToggleSubtree}
                      onOpenInspector=${setInspectorNode}
                      isFocused=${hoveredRef?.nodeId === node.id}
                    />
                  `
                )}
              </div>
            </div>
          `}
        </div>
      </main>

      <!-- SHARP EDITORIAL HOVER TOOLTIP PREVIEW -->
      ${hoveredNode && html`
        <div
          class="hover-tooltip-preview"
          style=${{
            top: `${Math.min(window.innerHeight - 130, hoveredRef.rect.bottom + 8)}px`,
            left: `${Math.min(window.innerWidth - 320, Math.max(12, hoveredRef.rect.left))}px`,
          }}
        >
          <div class="card-meta-row">
            <span class="kicker-label">▪ ${hoveredNode.type}</span>
            <span class="arch-stamp ${isCaveatStatus(hoveredNode.audit?.status) ? 'is-caveat' : ''}">
              ${formatAuditStatus(hoveredNode.audit?.status || 'verified')}
            </span>
          </div>
          <div class="card-heading" style="font-size: 14.5px;">
            ${hoveredNode.title}
          </div>
          <div class="kicker-label kicker-accent" style="margin-top: 2px;">
            ${hoveredRef.level === 0
              ? `Click to expand ${hoveredNode.direct_child_ids?.length || 0} L1 support plate(s) →`
              : 'Click to expand in L2+ Backing column →'}
          </div>
        </div>
      `}

      <!-- STICKY BATCH REVIEW QUEUE BAR (Antigravity-Style Regeneration) -->
      ${(pendingComments.length > 0 || regenerating || actionError) && html`
        <footer class="review-queue-bar" inert=${Boolean(inspectorNode || queueDrawerOpen)}>
          <div style="display: flex; align-items: center; gap: 14px; flex-wrap: wrap;">
            <span class="kicker-label kicker-accent">
              ▪ ${pendingComments.length} Queued Review Note${pendingComments.length === 1 ? '' : 's'}
            </span>
            <span class="provenance-caption">
              Across <span class="font-mono-data">${affectedSectionsCount}</span> section${affectedSectionsCount === 1 ? '' : 's'}
            </span>
            ${actionError && html`
              <span class="provenance-caption" style="color: var(--color-danger);">
                Error: ${actionError}
              </span>
            `}
          </div>
          <div style="display: flex; align-items: center; gap: 10px;">
            <button
              type="button"
              class="btn"
              onClick=${() => setQueueDrawerOpen(true)}
            >
              Inspect Queue
            </button>
            <button
              type="button"
              class="btn btn-primary"
              disabled=${regenerating || pendingComments.length === 0}
              onClick=${handleRegenerateBatch}
            >
              ${regenerating
                ? 'Triaging & Regenerating…'
                : `Apply Feedback & Re-compile (${pendingComments.length}) →`}
            </button>
          </div>
        </footer>
      `}

      <!-- SLIDE-OVER SOURCE INSPECTOR DRAWER -->
      <${SourceInspectorDrawer}
        node=${inspectorNode}
        onClose=${() => setInspectorNode(null)}
      />

      <!-- SLIDE-OVER BATCH REVIEW QUEUE DRAWER -->
      <${ReviewQueueDrawer}
        isOpen=${queueDrawerOpen}
        pendingComments=${pendingComments}
        nodesMap=${nodesMap}
        onClose=${() => setQueueDrawerOpen(false)}
        onJumpToNode=${handleJumpToNode}
        onDeleteComment=${handleDeleteComment}
        onRegenerate=${handleRegenerateBatch}
        regenerating=${regenerating}
      />

      <!-- NATIVE DIALOG FOR ASKING A NEW QUESTION / RUNNING 4-STAGE PIPELINE -->
      <${AskPipelineDialog}
        dialogRef=${askDialogRef}
        onBundleCreated=${async (newBundle) => {
          await fetchBundlesList();
          setBundle(newBundle);
          setCurrentBundleId(newBundle.bundle_id);
          setPinnedClaimId(null);
          setExpandedLevel2Ids([]);
        }}
      />

      <!-- NATIVE DIALOG FOR TIER-1 COMPILER & CUSTOM BUNDLE LOADER -->
      <dialog
        ref=${dialogRef}
        class="compiler-dialog"
        closedby="any"
        aria-labelledby="compiler-dialog-title"
      >
        <div class="dialog-inner">
          <div class="card-meta-row">
            <h2 id="compiler-dialog-title" class="card-heading" style="font-size: 17px;">
              Compile Tier-1 Sections or Load Tier-2 Bundle JSON
            </h2>
            <form method="dialog">
              <button type="submit" class="btn">Close</button>
            </form>
          </div>

          <p class="provenance-caption">
            Paste either a Tier-1 <code class="font-mono-data">CompilePipelineRequest</code> (runs
            <code class="font-mono-data">SectionValidator</code>,
            <code class="font-mono-data">StitchInvariantGate</code>, and
            <code class="font-mono-data">CompiledGraphBuilder</code>) or a Tier-2
            <code class="font-mono-data">CompiledBundle</code> JSON payload.
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
                Reset Sample Payload
              </button>
              <button type="submit" class="btn btn-primary">
                Validate & Render on Canvas
              </button>
            </div>
          </form>
        </div>
      </dialog>
    </div>
  `;
}

render(html`<${App} />`, document.getElementById('app-root'));
