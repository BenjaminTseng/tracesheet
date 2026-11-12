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

  // Native <dialog> ref for live compiler / custom JSON loader
  const dialogRef = useRef(null);
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
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBundlesList();
    loadBundle('legal_motion_1332');
  }, [fetchBundlesList, loadBundle]);

  // Progressive Escape key handling: close Drawer -> close L2+ -> close L1
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key !== 'Escape') return;
      if (inspectorNode) {
        setInspectorNode(null);
      } else if (expandedLevel2Ids.length > 0) {
        setExpandedLevel2Ids([]);
      } else if (pinnedClaimId) {
        setPinnedClaimId(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [inspectorNode, expandedLevel2Ids, pinnedClaimId]);

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
        const fallbackParentCard =
          !inlineTrigger && l2Node.parent_ids?.[0]
            ? container.querySelector(`article[data-card-node-id="${l2Node.parent_ids[0]}"]`)
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

              ${(bundle.artifact.sections || []).map(
                (sec, idx) => html`
                  <section key=${sec.section_id} class="artifact-section">
                    <div class="card-meta-row">
                      <h2 class="section-heading">${sec.section_title}</h2>
                      <span class="font-mono-data" style="font-size: 11px; color: var(--color-text-muted);">
                        SEC. 0${idx + 1}
                      </span>
                    </div>
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
                `
              )}
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
                    <span
                      class="arch-stamp ${isCaveatStatus(activeClaimNode.audit?.status) ? 'is-caveat' : ''}"
                    >
                      ${isCaveatStatus(activeClaimNode.audit?.status) ? '▪ ' : ''}
                      ${formatAuditStatus(activeClaimNode.audit?.status || 'verified')}
                    </span>
                  </div>
                  <div class="card-heading">${activeClaimNode.title}</div>
                  ${activeClaimNode.audit?.evaluator_note && html`
                    <div class="provenance-caption">
                      ${activeClaimNode.audit.evaluator_note}
                    </div>
                  `}
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

      <!-- SLIDE-OVER SOURCE INSPECTOR DRAWER -->
      <${SourceInspectorDrawer}
        node=${inspectorNode}
        onClose=${() => setInspectorNode(null)}
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
