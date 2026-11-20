/**
 * Shared progressive 3-column Traceability Canvas, Bezier curves, and `<ref id='...'>` text blocks.
 */

import { html, Icon, isCaveatStatus, getLinkRoleMeta } from './shell.js';

/**
 * Determines tone styling (`default` / `financial` / `authority` / `caveat`) for a graph node.
 */
export function getToneForNode(node) {
  if (!node) return { cls: '', tag: 'Proof', dot: 'var(--color-accent-primary)', stroke: '#4A5568' };
  const status = node.audit?.status || 'verified';
  if (isCaveatStatus(status)) {
    return { cls: 'plate-caveat', tag: 'Audit Gap', dot: 'var(--color-warning)', stroke: '#C27803' };
  }
  if (node.type === 'calculation' || node.locator?.source_type === 'spreadsheet' || node.locator?.source_type === 'calculation_ledger') {
    return { cls: 'plate-financial', tag: 'Computation', dot: 'var(--color-emerald-accent)', stroke: '#0F6B50' };
  }
  if (node.type === 'authority') {
    return { cls: 'plate-authority', tag: 'Statutory Rule', dot: 'var(--color-copper-accent)', stroke: '#9E4B1E' };
  }
  return { cls: '', tag: node.type === 'reasoning' ? 'Legal Analysis' : 'Source Evidence', dot: 'var(--color-accent-primary)', stroke: '#1D4ED8' };
}

/**
 * Parses `<ref id='node_id'>clause</ref>` tags into interactive inline text highlights.
 */
export function renderAnnotatedText({
  text,
  nodesMap,
  activeNodeIds,
  tensionClaimIds = new Set(),
  auditFilter = 'all',
  onHoverRef,
  onLeaveRef,
  onClickRef,
  level,
  refAttrMode = 'both',
}) {
  if (!text) return null;
  const regex = /<ref\s+id=['"]([^'"]+)['"]>([\s\S]*?)<\/ref>/g;
  const parts = [];
  let lastIndex = 0;
  let match;
  let tokenIdx = 0;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    const nodeId = match[1];
    const clause = match[2];
    const targetNode = nodesMap?.[nodeId];
    const auditStatus = targetNode?.audit?.status || 'verified';
    const isCaveat = isCaveatStatus(auditStatus);
    const isTension = level === 0 && Boolean(tensionClaimIds?.has?.(nodeId));
    const hasCaveat = isCaveat || isTension;
    const isFinancial =
      targetNode &&
      (targetNode.type === 'calculation' ||
        targetNode.locator?.source_type === 'spreadsheet' ||
        targetNode.locator?.source_type === 'calculation_ledger');
    const isAuthority = targetNode && targetNode.type === 'authority';

    let toneClass = 'tone-default';
    if (isTension) toneClass = 'tone-tension';
    else if (isCaveat) toneClass = 'tone-caveat';
    else if (isFinancial) toneClass = 'tone-financial';
    else if (isAuthority) toneClass = 'tone-authority';

    const isActive = Boolean(activeNodeIds?.has?.(nodeId));
    const isDimmed =
      level === 0 &&
      ((auditFilter === 'caveats' && !hasCaveat) || (auditFilter === 'tension' && !isTension));

    const dataProps = {
      'data-ref-node-id': nodeId,
      'data-ref-level': level,
    };
    if (refAttrMode === 'both') {
      dataProps['data-ref-id'] = nodeId;
    }

    parts.push(html`
      <button
        key=${`ref-${nodeId}-${tokenIdx++}`}
        type="button"
        class="clause-highlight ${toneClass} ${isActive ? 'is-active' : ''} ${isCaveat ? 'is-caveat' : ''} ${isDimmed ? 'is-dimmed' : ''}"
        aria-pressed=${isActive}
        ...${dataProps}
        onMouseEnter=${(e) => onHoverRef?.(nodeId, e.currentTarget, level)}
        onMouseLeave=${() => onLeaveRef?.()}
        onFocus=${(e) => onHoverRef?.(nodeId, e.currentTarget, level)}
        onBlur=${() => onLeaveRef?.()}
        onClick=${(e) => {
          e.stopPropagation();
          onClickRef?.(nodeId, level);
        }}
      >
        ${clause}
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
 * Renders structured section prose + pipe markdown tables containing `<ref id="...">` spans.
 */
export function RichRefBlock({ content, nodes, pinnedClaimId, onSelectClaim, showCaveatsOnly = false }) {
  if (!content) return null;

  const renderBoldAndCode = (txt) => {
    const segs = txt.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    return segs.map((seg) => {
      if (seg.startsWith('**') && seg.endsWith('**')) {
        return html`<strong>${seg.slice(2, -2)}</strong>`;
      }
      if (seg.startsWith('`') && seg.endsWith('`')) {
        return html`<span class="font-mono-data">${seg.slice(1, -1)}</span>`;
      }
      return seg;
    });
  };

  const renderInline = (raw) => {
    const regex = /<ref\s+id=['"]([^'"]+)['"]>([\s\S]*?)<\/ref>/g;
    const parts = [];
    let last = 0;
    let m;
    let tok = 0;
    while ((m = regex.exec(raw)) !== null) {
      if (m.index > last) {
        parts.push(renderBoldAndCode(raw.slice(last, m.index)));
      }
      const refId = m[1];
      const inner = m[2];
      const targetNode = nodes?.[refId];
      const caveat = isCaveatStatus(targetNode?.audit?.status || 'verified');
      const active = pinnedClaimId === refId;
      const dimmed = Boolean(pinnedClaimId && !active) || (showCaveatsOnly && !caveat);
      const isFinancial =
        targetNode &&
        (targetNode.type === 'calculation' ||
          targetNode.locator?.source_type === 'spreadsheet' ||
          targetNode.locator?.source_type === 'calculation_ledger');
      const isAuthority = targetNode && targetNode.type === 'authority';
      const toneClass = caveat
        ? 'tone-caveat'
        : isFinancial
        ? 'tone-financial'
        : isAuthority
        ? 'tone-authority'
        : 'tone-default';

      parts.push(html`
        <button
          key=${`richref-${refId}-${tok++}`}
          type="button"
          data-ref-id=${refId}
          data-ref-node-id=${refId}
          class=${`clause-highlight ${toneClass} ${active ? 'is-active' : ''} ${caveat ? 'is-caveat' : ''} ${dimmed ? 'is-dimmed' : ''}`}
          aria-pressed=${active}
          onClick=${(e) => {
            e.stopPropagation();
            onSelectClaim?.(refId);
          }}
        >
          ${renderBoldAndCode(inner)}
        </button>
      `);
      last = regex.lastIndex;
    }
    if (last < raw.length) {
      parts.push(renderBoldAndCode(raw.slice(last)));
    }
    return parts;
  };

  const lines = content.split('\n');
  const blocks = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith('|') && i + 1 < lines.length && /^\|\s*[-:]+/.test(lines[i + 1].trim())) {
      const headerCells = line
        .trim()
        .split('|')
        .slice(1, -1)
        .map((s) => s.trim());
      const alignLine = lines[i + 1]
        .trim()
        .split('|')
        .slice(1, -1)
        .map((s) => s.trim());
      const isNumericCol = alignLine.map((a) => a.endsWith(':'));
      i += 2;
      const bodyRows = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        const cells = lines[i]
          .trim()
          .split('|')
          .slice(1, -1)
          .map((s) => s.trim());
        bodyRows.push(cells);
        i += 1;
      }
      blocks.push(html`
        <div class="bk-table-wrap">
          <table class="sheet-table">
            <thead>
              <tr>
                ${headerCells.map(
                  (hCell, colIdx) => html`
                    <th class=${isNumericCol[colIdx] ? 'cell-numeric' : ''}>${hCell}</th>
                  `
                )}
              </tr>
            </thead>
            <tbody>
              ${bodyRows.map(
                (r) => html`
                  <tr>
                    ${r.map(
                      (cell, colIdx) => html`
                        <td class=${isNumericCol[colIdx] ? 'cell-numeric' : ''}>${renderInline(cell)}</td>
                      `
                    )}
                  </tr>
                `
              )}
            </tbody>
          </table>
        </div>
      `);
      continue;
    }

    if (line.trim() === '') {
      i += 1;
      continue;
    }
    blocks.push(html`<p class="bk-prose-line">${renderInline(line)}</p>`);
    i += 1;
  }

  return html`${blocks}`;
}

/**
 * Renders curved cubic Bezier SVG connectors and optional interactive midpoint pills.
 */
export function BezierConnectorLayer({
  links = [],
  nodesMap = {},
  hoveredLinkId = null,
  activeLinkPopoverId = null,
  allComments = [],
  onHoverLink = null,
  onClickLink = null,
}) {
  const interactive = typeof onClickLink === 'function';

  return html`
    <svg class="connector-svg-layer" aria-hidden="true">
      ${links.map((link, idx) => {
        const targetNode = nodesMap?.[link.targetId];
        const roleMeta = getLinkRoleMeta(targetNode);
        const isHovered = hoveredLinkId === link.id || activeLinkPopoverId === link.id;
        const strokeColor = link.stroke || (link.tier === 1 ? roleMeta.stroke : '#3E4652');
        return html`
          <g key=${link.id || `edge-${idx}`}>
            ${interactive && html`
              <path
                d=${link.d}
                fill="none"
                stroke="transparent"
                stroke-width="14"
                class="bezier-hit-path"
                onMouseEnter=${() => onHoverLink?.(link.id)}
                onMouseLeave=${() => onHoverLink?.(null)}
                onClick=${(e) => {
                  e.stopPropagation();
                  onClickLink(link);
                }}
              />
            `}
            <path
              d=${link.d}
              fill="none"
              class="bezier-stroke"
              stroke=${strokeColor}
              stroke-width=${isHovered ? '2.25' : '1.5'}
              stroke-dasharray=${link.dashed ? '4 4' : 'none'}
              opacity=${isHovered ? '1' : '0.68'}
            />
            ${link.x1 != null && link.y1 != null && html`
              <rect x=${link.x1 - 2.5} y=${link.y1 - 2.5} width="5" height="5" fill=${strokeColor} />
            `}
            ${link.x2 != null && link.y2 != null && html`
              <rect x=${link.x2 - 2.5} y=${link.y2 - 2.5} width="5" height="5" fill=${strokeColor} />
            `}
          </g>
        `;
      })}
    </svg>
    ${interactive && links.length > 0 && html`
      <div class="connector-handles-layer">
        ${links.map((link) => {
          const targetNode = nodesMap?.[link.targetId];
          const roleMeta = getLinkRoleMeta(targetNode);
          const linkNoteCount = allComments.filter(
            (c) => !c.resolved && c.node_id === link.targetId && c.scope === 'link'
          ).length;
          const isOpen = activeLinkPopoverId === link.id;
          return html`
            <button
              key=${`handle-${link.id}`}
              type="button"
              class="bezier-link-handle ${roleMeta.toneClass} ${isOpen ? 'is-active' : ''}"
              style=${{ left: `${link.midX}px`, top: `${link.midY}px` }}
              aria-label=${`Inspect or comment on ${roleMeta.label} connection to ${targetNode?.title || link.targetId}`}
              onMouseEnter=${() => onHoverLink?.(link.id)}
              onMouseLeave=${() => onHoverLink?.(null)}
              onClick=${(e) => {
                e.stopPropagation();
                onClickLink(isOpen ? null : link);
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
  `;
}

/**
 * Progressive 1->2->3-column traceability canvas container shared by all compiler UIs.
 */
export function TraceabilityCanvas({
  mainId = 'workspace-main',
  viewportRef,
  gridRef,
  inert = false,
  beforeGridSlot = null,
  showL1 = false,
  showL2 = false,
  bezierProps = {},
  l0Title = 'Document',
  l0Count = null,
  l0Caption = '',
  l0LaneClass = 'column-lane',
  l0AriaLabel = 'Primary Draft Document',
  renderL0,
  l1Title = 'Proof & Reasoning',
  l1Count = null,
  l1ExtraHeader = null,
  l1Ref = null,
  l1LaneClass = 'column-lane lane-analytical lane-evidence',
  l1AriaLabel = 'L1 Supporting Proof and Calculations',
  onCloseL1,
  renderL1,
  defaultRightTitle = null,
  defaultRightCount = null,
  defaultRightAriaLabel = 'Audit Resolution Queue',
  renderDefaultRight = null,
  l2Title = 'Sources & Law',
  l2Count = null,
  l2Ref = null,
  l2AriaLabel = 'L2+ Controlling Rules and Authorities',
  onCloseL2,
  renderL2,
}) {
  const showRightPane = showL1 || Boolean(renderDefaultRight);
  const gridColsClass = showL2 ? 'cols-3' : showRightPane ? 'cols-2' : 'cols-1';

  return html`
    <main
      id=${mainId}
      tabindex="-1"
      class="spatial-viewport"
      ref=${viewportRef}
      inert=${Boolean(inert)}
    >
      ${beforeGridSlot}

      <${BezierConnectorLayer} ...${bezierProps} />

      <div class="bounded-canvas-grid ${gridColsClass}" ref=${gridRef}>
        <section class=${l0LaneClass} aria-label=${l0AriaLabel}>
          <div class="lane-header">
            <span class="lane-title-group">
              <span class="lane-title">${l0Title}</span>
              ${l0Count != null && html`<span class="lane-count font-mono-data">${l0Count}</span>`}
            </span>
            ${l0Caption && html`<span class="lane-caption">${l0Caption}</span>`}
          </div>
          ${renderL0?.()}
        </section>

        ${showL1
          ? html`
              <section class=${l1LaneClass} ref=${l1Ref} aria-label=${l1AriaLabel}>
                <div class="lane-header">
                  <span class="lane-title-group">
                    <span class="lane-title">${l1Title}</span>
                    ${l1Count != null && html`<span class="lane-count font-mono-data">(${l1Count})</span>`}
                  </span>
                  <div style="display: inline-flex; align-items: center; gap: 10px;">
                    ${l1ExtraHeader}
                    <button type="button" class="btn-link is-muted" onClick=${onCloseL1}>
                      <${Icon} name="close" size=${12} />
                      <span>Close</span>
                    </button>
                  </div>
                </div>
                ${renderL1?.()}
              </section>
            `
          : renderDefaultRight
          ? html`
              <section class="column-lane" aria-label=${defaultRightAriaLabel}>
                <div class="lane-header">
                  <span class="lane-title-group">
                    <span class="lane-title">${defaultRightTitle || 'Queue'}</span>
                  </span>
                  ${defaultRightCount != null && html`
                    <span class="lane-count font-mono-data">${defaultRightCount}</span>
                  `}
                </div>
                ${renderDefaultRight()}
              </section>
            `
          : null}

        ${showL2 && html`
          <section class="column-lane lane-analytical" ref=${l2Ref} aria-label=${l2AriaLabel}>
            <div class="lane-header">
              <span class="lane-title-group">
                <span class="lane-title">${l2Title}</span>
                ${l2Count != null && html`<span class="lane-count font-mono-data">(${l2Count})</span>`}
              </span>
              <button type="button" class="btn-link is-muted" onClick=${onCloseL2}>
                <${Icon} name="close" size=${12} />
                <span>Close</span>
              </button>
            </div>
            ${renderL2?.()}
          </section>
        `}
      </div>
    </main>
  `;
}
