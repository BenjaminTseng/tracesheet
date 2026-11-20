/**
 * Shared platform chrome, SVG icons, status/provenance formatters, and Application Switcher.
 */

import { h } from '/static/vendor/preact.mjs';
import { useState, useEffect } from '/static/vendor/hooks.mjs';
import htm from '/static/vendor/htm.mjs';

export const html = htm.bind(h);

/**
 * Minimal crisp 16px geometric SVG icon primitive (zero Unicode glyphs or emojis).
 */
export function Icon({ name, size = 14 }) {
  const props = {
    width: size,
    height: size,
    viewBox: '0 0 16 16',
    fill: 'none',
    stroke: 'currentColor',
    'stroke-width': '1.5',
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
    'aria-hidden': 'true',
  };

  switch (name) {
    case 'comment':
      return html`<svg ...${props}><path d="M2.5 3h11v7.5h-6L4.5 13v-2.5h-2V3z" /></svg>`;
    case 'source':
      return html`<svg ...${props}><path d="M3 2h7l3 3v9H3V2z" /><path d="M10 2v3h3" /><path d="M5.5 8.5h5M5.5 11h3.5" /></svg>`;
    case 'link':
      return html`<svg ...${props}><path d="M6.5 9.5a3 3 0 0 0 4.24 0l2-2a3 3 0 0 0-4.24-4.24l-1.1 1.1" /><path d="M9.5 6.5a3 3 0 0 0-4.24 0l-2 2a3 3 0 0 0 4.24 4.24l1.1-1.1" /></svg>`;
    case 'arrowRight':
      return html`<svg ...${props}><path d="M3 8h10M9.5 4.5L13 8l-3.5 3.5" /></svg>`;
    case 'arrowLeft':
      return html`<svg ...${props}><path d="M13 8H3M6.5 4.5L3 8l3.5 3.5" /></svg>`;
    case 'external':
      return html`<svg ...${props}><path d="M6.5 3.5H3.5v9h9v-3" /><path d="M9.5 2.5h4v4" /><path d="M13.5 2.5L7.5 8.5" /></svg>`;
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

export function CloseIcon({ size = 14 } = {}) {
  return html`<${Icon} name="close" size=${size} />`;
}

export function ArrowRightIcon({ size = 14 } = {}) {
  return html`<${Icon} name="arrowRight" size=${size} />`;
}

export function ArrowLeftIcon({ size = 14 } = {}) {
  return html`<${Icon} name="arrowLeft" size=${size} />`;
}

export function ExternalIcon({ size = 12 } = {}) {
  return html`<${Icon} name="external" size=${size} />`;
}

export function ChevronRightIcon({ size = 12 } = {}) {
  return html`<${Icon} name="chevronRight" size=${size} />`;
}

export function ChevronDownIcon({ size = 12 } = {}) {
  return html`<${Icon} name="chevronDown" size=${size} />`;
}

export function formatAuditStatus(status) {
  switch (status) {
    case 'verified':
      return 'Verified';
    case 'human_overridden':
      return 'Attested by Counsel';
    case 'verified_negative':
      return 'Verified (No Doc Needed)';
    case 'flagged_anomaly':
      return 'Verified (Flagged)';
    case 'contradicted':
      return 'Cross-Doc Contradiction';
    case 'extrapolation':
      return 'Extrapolation';
    case 'assumption':
      return 'Assumption';
    case 'disputed':
      return 'Disputed';
    case 'unverified':
      return 'Unverified / Gap';
    default:
      return status || 'Verified';
  }
}

export function formatAuditLabel(status) {
  switch (status) {
    case 'verified':
      return 'Verified';
    case 'human_overridden':
      return 'Attested by Counsel';
    case 'extrapolation':
      return 'Extrapolation';
    case 'assumption':
    case 'unverified':
      return 'Unverified';
    case 'disputed':
    case 'contradicted':
      return 'Contradicted';
    default:
      return 'Pending';
  }
}

export function isCaveatStatus(status) {
  return status !== 'verified' && status !== 'verified_negative' && status !== 'human_overridden';
}

export function isCaveat(status) {
  return isCaveatStatus(status);
}

export function formatNodeRole(type) {
  switch (type) {
    case 'evidence':
      return 'Direct Evidence';
    case 'reasoning':
      return 'Logical Inference';
    case 'calculation':
      return 'Calculation';
    case 'assumption':
      return 'Baseline Assumption';
    case 'authority':
      return 'Controlling Rule';
    case 'claim':
      return 'Claim';
    default:
      return type || 'Proof Node';
  }
}

export function getLinkRoleMeta(targetNode) {
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

export function formatScopeTag(comment, nodesMap) {
  const scope = comment?.scope || 'node';
  if (scope === 'document' || comment?.section_id === '__document__') {
    return { label: 'Overall Document', cls: 'is-document' };
  }
  if (scope === 'section' || comment?.node_id === '__section__') {
    return { label: 'Section Note', cls: 'is-section' };
  }
  if (scope === 'link') {
    return { label: 'Logical Link', cls: 'is-link' };
  }
  const node = nodesMap?.[comment?.node_id];
  if (node && node.type === 'claim') {
    return { label: 'Claim', cls: 'is-claim' };
  }
  return { label: 'Evidence Node', cls: 'is-evidence' };
}

export function formatReliabilityTier(tier) {
  switch (tier) {
    case 'primary_record':
      return { label: 'Primary Record', cls: 'is-primary' };
    case 'secondary_analysis':
    case 'corroborating_secondary':
      return { label: 'Secondary Analysis', cls: 'is-secondary' };
    case 'self_reported':
    case 'self_reported_intake':
      return { label: 'Self-Reported', cls: 'is-self-reported' };
    case 'governing_authority':
      return { label: 'Governing Rule', cls: 'is-primary' };
    default:
      return null;
  }
}

export function formatProvenanceParts(locator) {
  if (!locator) return { label: '', coord: '' };
  switch (locator.source_type) {
    case 'calculation_ledger':
      return {
        label: 'Ledger Snapshot',
        coord: [locator.json_path, locator.file_name].filter(Boolean).join(' · '),
      };
    case 'event_log':
      return {
        label: 'Event Log',
        coord: [locator.event_id ? `Event ${locator.event_id}` : null, locator.json_path]
          .filter(Boolean)
          .join(' · '),
      };
    case 'pdf':
      return {
        label: locator.file_name || 'Filing.pdf',
        coord: `p. ${locator.page || 1}${locator.line ? `, ln. ${locator.line}` : ''}`,
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
        coord:
          locator.database || locator.table
            ? `${locator.database || 'db'}.${locator.table || 'table'} [${locator.row_id || 'row'}]`
            : locator.query || locator.file_name || '',
      };
    case 'web':
      return {
        label: 'Archival Snapshot',
        coord: locator.locator_key || locator.url || '',
      };
    case 'markdown':
      return {
        label: locator.file_name || 'Document.md',
        coord: locator.locator_key || locator.section || '',
      };
    case 'docx':
      return {
        label: locator.file_name || 'Document.docx',
        coord: locator.locator_key || locator.section || '',
      };
    default:
      return { label: locator.source_type || locator.file_name || '', coord: '' };
  }
}

export function formatApiError(detailOrErr) {
  const detail = detailOrErr?.detail ?? detailOrErr;
  if (!detail) return 'Unexpected error.';
  if (typeof detail === 'string') return detail;
  if (typeof detail === 'object') {
    const parts = [];
    if (detail.message) parts.push(detail.message);
    if (Array.isArray(detail.failed_checks) && detail.failed_checks.length > 0) {
      parts.push(`Failed checks: ${detail.failed_checks.join(', ')}`);
    }
    if (detail.audit_rationale) parts.push(detail.audit_rationale);
    if (Array.isArray(detail.errors) && detail.errors.length > 0) {
      parts.push(
        detail.errors
          .slice(0, 3)
          .map((e) => (typeof e === 'string' ? e : e.message || JSON.stringify(e)))
          .join(' | ')
      );
    }
    if (parts.length > 0) return parts.join(' — ');
  }
  return JSON.stringify(detail);
}

export function formatBytes(bytes) {
  if (bytes == null || Number.isNaN(Number(bytes))) return '—';
  const n = Number(bytes);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

export function formatRunStatusLabel(status) {
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
 * Resolves a node's underlying raw source URL when backed by canonical or matter workspace files.
 */
export function resolveSourceFileUrl(node, bundle, mattersList, canonicalAuths) {
  const loc = node?.locator;
  if (!loc) return null;

  const sourceType = loc.source_type;
  const matterId = bundle?.matter_id;

  if (sourceType === 'web') {
    const extUrl = loc.url || node?.url;
    if (extUrl) {
      return {
        existsOnDisk: true,
        isExternal: true,
        url: extUrl,
        fileName: null,
        label: 'Open External Source',
      };
    }
  }

  if (loc.canonical_doc_id || sourceType === 'authority_rule' || node?.type === 'authority') {
    const canonMatch = (canonicalAuths || []).find(
      (a) =>
        (loc.canonical_doc_id && a.doc_id === loc.canonical_doc_id) ||
        (loc.locator_key && a.auth_id === loc.locator_key) ||
        (node?.title && a.title === node.title) ||
        (loc.file_name && a.file_name === loc.file_name)
    );
    const docId = canonMatch?.doc_id || loc?.file_name || '';
    const domain = canonMatch?.domain || loc.domain || (docId.includes('/') ? docId.split('/')[0] : '');
    const fileName =
      canonMatch?.file_name ||
      (docId.includes('/') ? docId.split('/').slice(1).join('/') : loc.file_name);
    if (domain && fileName) {
      return {
        existsOnDisk: true,
        url: `/api/v1/canonical/files/${encodeURIComponent(domain)}/${encodeURIComponent(fileName)}/raw`,
        fileName,
        label: 'Open Controlling Rule',
      };
    }
  }

  if (sourceType === 'calculation_ledger') {
    if (!matterId) return null;
    return {
      existsOnDisk: true,
      isLedgerSnapshot: true,
      url: `/api/v1/matters/${encodeURIComponent(matterId)}/ledgers`,
      fileName: loc.file_name || 'ledgers/snapshot.json',
      label: 'Inspect Verified Ledger JSON',
    };
  }

  const fileName = loc.file_name;
  if (!fileName || !matterId) return null;

  const matterMeta = (mattersList || []).find((m) => m.matter_id === matterId);
  const availableRawFiles =
    matterMeta?.raw_files || bundle?.artifact?.metadata?.available_raw_files || [];
  const existsOnDisk = availableRawFiles.includes(fileName);

  const hashSuffix = sourceType === 'pdf' && loc.page ? `#page=${loc.page}` : '';
  const baseUrl = `/api/v1/matters/${encodeURIComponent(matterId)}/files/${encodeURIComponent(fileName)}/raw`;

  return {
    existsOnDisk,
    isSampleFixture: !existsOnDisk && !matterMeta,
    url: `${baseUrl}${hashSuffix}`,
    fileName,
    label:
      sourceType === 'pdf' && loc.page
        ? `Open Original PDF (p. ${loc.page})`
        : 'Open / Download Source File',
  };
}

/**
 * Shared top navigation chrome + App Switcher dropdown + standardized slot layout.
 */
export function PlatformShell({
  activeAppId,
  brandTitle = 'Audit Canvas',
  appsOverride = null,
  selectorSlot = null,
  filterSlot = null,
  headerActions = null,
  bannerSlot = null,
  queueView = null,
  inertOverlay = false,
  children,
  overlaySlots = null,
}) {
  const [apps, setApps] = useState(appsOverride || []);

  useEffect(() => {
    if (appsOverride) {
      setApps(appsOverride);
      return;
    }
    let cancelled = false;
    fetch('/api/v1/apps')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data && Array.isArray(data.apps)) {
          setApps(data.apps);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [appsOverride]);

  const showSwitcher = apps.length > 1;

  return html`
    <div class="app-shell">
      <header class="top-bar" inert=${Boolean(inertOverlay)}>
        <div class="top-bar-left">
          <span class="brand-title">${brandTitle}</span>
          ${showSwitcher && html`
            <div class="platform-app-switcher">
              <label for="platform-app-select" class="visually-hidden">Application Workspace</label>
              <select
                id="platform-app-select"
                class="select-control platform-app-select"
                aria-label="Switch active compiler application"
                value=${activeAppId}
                onChange=${(e) => {
                  const chosen = apps.find((a) => a.app_id === e.target.value);
                  if (chosen?.ui_route && chosen.app_id !== activeAppId) {
                    window.location.assign(chosen.ui_route);
                  }
                }}
              >
                ${apps.map(
                  (app) => html`
                    <option key=${app.app_id} value=${app.app_id}>
                      ${app.label}
                    </option>
                  `
                )}
              </select>
            </div>
          `}
          ${selectorSlot && html`
            <span class="divider-vertical" aria-hidden="true"></span>
            ${selectorSlot}
          `}
        </div>

        <div class="top-bar-right">
          ${filterSlot}
          ${headerActions}
        </div>
      </header>

      ${bannerSlot}
      ${queueView}
      ${children}
      ${overlaySlots}
    </div>
  `;
}
