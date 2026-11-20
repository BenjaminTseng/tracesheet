/**
 * Shared polymorphic Source Inspector drawer handling PDF, spreadsheets, ledgers,
 * event logs, APIs, databases, web citations, markdown/docx excerpts, and statutory authorities.
 */

import { useEffect, useRef } from '/static/vendor/hooks.mjs';
import {
  html,
  Icon,
  CloseIcon,
  ExternalIcon,
  formatAuditStatus,
  formatNodeRole,
  formatProvenanceParts,
  formatReliabilityTier,
  isCaveatStatus,
} from './shell.js';

function tryParseJson(rawValue) {
  if (rawValue == null) return null;
  if (typeof rawValue === 'object') return rawValue;
  if (typeof rawValue !== 'string') return null;
  const trimmed = rawValue.trim();
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}

export function SourceInspectorDrawer({ node, sourceLink = null, rawUrlOverride = null, onClose }) {
  const closeBtnRef = useRef(null);

  useEffect(() => {
    if (!node) return undefined;
    const prevFocus = document.activeElement;
    requestAnimationFrame(() => closeBtnRef.current?.focus());
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      if (prevFocus && typeof prevFocus.focus === 'function') {
        prevFocus.focus();
      }
    };
  }, [node?.id, onClose]);

  if (!node) return null;

  const loc = node.locator || {};
  const sourceType = loc.source_type || (node.type === 'authority' ? 'web' : null);
  const provenance = formatProvenanceParts(loc);
  const tierMeta = formatReliabilityTier(loc.reliability_tier);
  const audit = node.audit || {};
  const auditStatus = audit.status || 'verified';
  const caveatFlag = isCaveatStatus(auditStatus);
  const rawLinkUrl = rawUrlOverride || (sourceLink?.existsOnDisk ? sourceLink.url : null);
  const rawLinkLabel = sourceLink?.label || (loc.page ? `Open Original PDF (p. ${loc.page})` : 'Open Original File');
  const parsedRaw = tryParseJson(loc.raw_value);

  return html`
    <div
      class="inspector-backdrop"
      onClick=${(e) => {
        if (e.target === e.currentTarget) onClose?.();
      }}
    >
      <aside
        class="source-inspector-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Source provenance inspector"
        onClick=${(e) => e.stopPropagation()}
      >
        <div class="drawer-header">
          <div>
            <span class="control-label">
              ${formatNodeRole(node.type)}
              ${provenance.label ? ` · ${provenance.label}` : ''}
              ${provenance.coord ? ` (${provenance.coord})` : ''}
            </span>
            <h2 class="card-heading" style="font-size: 17px; margin-top: 2px;">${node.title}</h2>
          </div>
          <button
            ref=${closeBtnRef}
            type="button"
            class="btn btn-icon-only"
            aria-label="Close source inspector"
            onClick=${onClose}
          >
            <${CloseIcon} />
          </button>
        </div>

        <div class="drawer-body">
          <div class="card-meta-row" style="border-bottom: 1px solid var(--color-border-subtle); padding-bottom: 8px; flex-wrap: wrap;">
            <span style="display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <span class="arch-stamp ${caveatFlag ? 'is-caveat' : ''}">
                ${formatAuditStatus(auditStatus)}
                ${audit.score != null && html`
                  <span class="font-mono-data" style="margin-inline-start: 4px;">${Math.round(audit.score * 100)}%</span>
                `}
              </span>
              ${tierMeta && html`
                <span class="reliability-pill ${tierMeta.cls}">${tierMeta.label}</span>
              `}
            </span>
            ${audit.evaluator_type && html`
              <span class="provenance-caption">
                Verified by ${audit.evaluator_type} check
              </span>
            `}
          </div>

          ${(loc.origin_description || sourceLink?.isSampleFixture) && html`
            <div class="provenance-origin-row">
              ${loc.origin_description && html`
                <span class="provenance-origin-text">${loc.origin_description}</span>
              `}
              ${sourceLink?.isSampleFixture && html`
                <span class="sample-fixture-badge">Sample Fixture (No Raw File on Disk)</span>
              `}
            </div>
          `}

          ${sourceType === 'calculation_ledger' && html`
            <div class="ledger-inspector-box">
              <div class="card-meta-row">
                <span class="control-label">Verified Calculation Ledger</span>
                ${loc.payload_hash && html`
                  <span class="font-mono-data" style="font-size: 11px;">sha256:${loc.payload_hash}</span>
                `}
              </div>
              <div class="provenance-caption">
                <strong>File:</strong> <span class="font-mono-data">${loc.file_name || 'ledgers/snapshot.json'}</span>
                ${loc.json_path && html` · <strong>Path:</strong> <span class="font-mono-data">${loc.json_path}</span>`}
              </div>
              ${parsedRaw && !Array.isArray(parsedRaw) ? html`
                <table class="sheet-table">
                  <thead>
                    <tr>
                      <th>Metric / Field</th>
                      <th>Verified Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${Object.entries(parsedRaw).map(([k, v]) => html`
                      <tr key=${k}>
                        <td class="font-mono-data">${k}</td>
                        <td class="cell-numeric sheet-cell-active">
                          ${typeof v === 'object' ? JSON.stringify(v) : String(v)}
                        </td>
                      </tr>
                    `)}
                  </tbody>
                </table>
              ` : loc.raw_value != null && html`
                <table class="sheet-table">
                  <thead>
                    <tr>
                      <th>Key</th>
                      <th>Verified Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td class="font-mono-data">${loc.json_path || 'value'}</td>
                      <td class="cell-numeric sheet-cell-active">${String(loc.raw_value)}</td>
                    </tr>
                  </tbody>
                </table>
              `}
              ${node.quote && html`
                <blockquote class="evidence-blockquote">“${node.quote}”</blockquote>
              `}
            </div>
          `}

          ${sourceType === 'event_log' && html`
            <div class="event-log-box">
              <div class="card-meta-row">
                <span class="control-label">Structured Event Log</span>
                ${loc.event_id && html`
                  <span class="font-mono-data" style="font-size: 11px;">${loc.event_id}</span>
                `}
              </div>
              <div class="provenance-caption">
                <strong>Source:</strong> <span class="font-mono-data">${loc.file_name || 'events.json'}</span>
                ${loc.json_path && html` · <span class="font-mono-data">${loc.json_path}</span>`}
              </div>
              ${parsedRaw && html`
                <pre tabindex="0" class="formula-box" style="margin: 0; white-space: pre-wrap;">${JSON.stringify(parsedRaw, null, 2)}</pre>
              `}
              ${node.quote && html`
                <blockquote class="evidence-blockquote">“${node.quote}”</blockquote>
              `}
            </div>
          `}

          ${sourceType === 'pdf' && html`
            <div class="pdf-page-simulator">
              <div class="card-meta-row">
                <span class="control-label">${loc.file_name || 'PDF Document'}</span>
                <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                  PAGE ${loc.page || 1}${loc.line ? ` · LINE ${loc.line}` : ''}
                </span>
              </div>
              <p class="provenance-caption">
                Locator: <span class="font-mono-data">${loc.locator_key || 'Verified Excerpt'}</span>
              </p>
              ${(node.quote || node.body) && html`
                <div class="pdf-bbox-highlight">
                  ${loc.bounding_box && html`
                    <div class="font-mono-data" style="font-size: 10.5px; color: var(--color-accent-primary); margin-bottom: 4px;">
                      BBOX [${loc.bounding_box.join(', ')}]
                    </div>
                  `}
                  “${node.quote || node.body}”
                </div>
              `}
              ${loc.payload_hash && html`
                <p class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                  ${loc.payload_hash}
                </p>
              `}
            </div>
          `}

          ${sourceType === 'spreadsheet' && html`
            <div style="display: flex; flex-direction: column; gap: 10px;">
              <div class="card-meta-row">
                <span class="control-label">Workbook: ${loc.file_name || 'Spreadsheet'}</span>
                <span class="font-mono-data" style="font-size: 11.5px; color: var(--color-text-secondary);">
                  ${[loc.sheet, loc.cell_range].filter(Boolean).join('!')}
                </span>
              </div>
              <table class="sheet-table">
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
                    <td class="font-mono-data">${loc.cell_range || loc.sheet || 'Target'}</td>
                    <td>${node.title}</td>
                    <td class="sheet-cell-active">${node.quote || '—'}</td>
                    <td class="cell-numeric">
                      ${loc.raw_value != null ? JSON.stringify(loc.raw_value) : '—'}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          `}

          ${sourceType === 'api' && html`
            <div style="display: flex; flex-direction: column; gap: 10px;">
              <div class="formula-box">
                <strong>${loc.method || 'GET'}</strong> ${loc.endpoint || loc.file_name || ''}
              </div>
              <div class="card-meta-row">
                <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-secondary);">
                  ${loc.json_path || ''}
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

          ${sourceType === 'internal_db' && html`
            <div style="display: flex; flex-direction: column; gap: 10px;">
              <div class="card-meta-row">
                <span class="font-mono-data" style="font-size: 11.5px; color: var(--color-text-secondary);">
                  ${[loc.database, loc.table].filter(Boolean).join('.') || loc.file_name || 'Database'}
                </span>
                ${loc.row_id != null && html`
                  <span class="font-mono-data" style="font-size: 11.5px; color: var(--color-text-muted);">
                    ROW ${loc.row_id}
                  </span>
                `}
              </div>
              ${loc.query && html`
                <figure class="evidence-figure">
                  <figcaption class="evidence-figcaption">Read-Only Verification Query</figcaption>
                  <pre tabindex="0" class="formula-box"><code class="language-sql">${loc.query}</code></pre>
                </figure>
              `}
              ${node.quote && html`
                <div class="evidence-figure">
                  <blockquote class="evidence-blockquote">“${node.quote}”</blockquote>
                </div>
              `}
            </div>
          `}

          ${sourceType === 'web' && html`
            <div style="display: flex; flex-direction: column; gap: 10px;">
              ${(loc.snapshot_timestamp || loc.locator_key) && html`
                <div class="card-meta-row">
                  <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                    ${loc.snapshot_timestamp || ''}
                  </span>
                  <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-secondary);">
                    ${loc.locator_key || ''}
                  </span>
                </div>
              `}
              ${node.quote && html`
                <blockquote class="evidence-blockquote" cite=${loc.url || node.url || ''}>
                  “${node.quote}”
                </blockquote>
              `}
            </div>
          `}

          ${(sourceType === 'markdown' || sourceType === 'docx') && html`
            <div class="doc-excerpt-frame">
              <div class="card-meta-row">
                <span class="control-label">${loc.file_name || 'Document'}</span>
                <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                  ${loc.locator_key || loc.section || 'EXCERPT'}
                </span>
              </div>
              ${node.quote && html`
                <blockquote class="evidence-blockquote">“${node.quote}”</blockquote>
              `}
              ${loc.payload_hash && html`
                <p class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                  ${loc.payload_hash}
                </p>
              `}
            </div>
          `}

          ${!sourceType && (node.quote || node.body) && html`
            <figure class="evidence-figure">
              ${node.quote && html`
                <blockquote class="evidence-blockquote" cite=${node.url || ''}>
                  “${node.quote}”
                </blockquote>
              `}
              ${node.body && html`<p class="card-body-prose">${node.body}</p>`}
            </figure>
          `}

          ${node.formula && html`
            <div>
              <span class="control-label" style="display: block; margin-bottom: 6px;">Verified Formula / Rule Check</span>
              <div class="formula-box"><strong>fx</strong> ${node.formula}</div>
            </div>
          `}

          ${sourceType && node.body && html`
            <p class="card-body-prose" style="margin: 0;">${node.body}</p>
          `}

          ${audit.evaluator_note && html`
            <div class="card-evaluator-note">
              <span><strong>Audit Record:</strong> ${audit.evaluator_note}</span>
            </div>
          `}

          ${audit.override && html`
            <div class="card-evaluator-note">
              <span>
                <strong>Counsel / Reviewer Attestation:</strong> ${audit.override.actor_name} (${audit.override.actor_role}) — ${audit.override.rationale}
              </span>
            </div>
          `}

          <div style="display: flex; flex-wrap: wrap; gap: 10px; padding-top: 6px;">
            ${(node.url || loc.url) && html`
              <a
                href=${node.url || loc.url}
                target="_blank"
                rel="noopener noreferrer"
                class="btn btn-primary"
              >
                <span>Open Controlling Authority</span>
                <${ExternalIcon} size=${13} />
              </a>
            `}
            ${rawLinkUrl && html`
              <a
                href=${rawLinkUrl}
                target="_blank"
                rel="noopener noreferrer"
                class="btn ${!(node.url || loc.url) ? 'btn-primary' : ''}"
                style="text-decoration: none;"
              >
                <${Icon} name="source" size=${12} />
                <span>${rawLinkLabel}</span>
                <${ExternalIcon} size=${12} />
              </a>
            `}
          </div>
        </div>
      </aside>
    </div>
  `;
}
