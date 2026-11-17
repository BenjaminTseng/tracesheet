import { h, render } from 'preact';
import { useState, useEffect, useRef, useCallback, useMemo } from 'preact/hooks';
import htm from 'htm';

const html = htm.bind(h);

function formatCurrency(val) {
  if (val === null || val === undefined || val === '') return '$0.00';
  const num = Number(val);
  if (Number.isNaN(num)) return String(val);
  return num.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
}

function formatAuditLabel(status) {
  const map = {
    verified: 'Verified',
    extrapolation: 'Extrapolation',
    assumption: 'Unverified',
    disputed: 'Contradicted',
    unverified: 'Unverified',
  };
  return map[status] || status;
}

function isCaveat(status) {
  return status === 'unverified' || status === 'disputed' || status === 'assumption' || status === 'extrapolation';
}

function getToneForNode(node) {
  const status = node?.audit?.status || 'verified';
  if (isCaveat(status)) return { cls: 'plate-caveat', stroke: '#B45309', tag: 'Gap / Caveat' };
  if (node?.type === 'calculation') return { cls: 'plate-financial', stroke: '#14532D', tag: 'Calculation' };
  if (node?.type === 'authority') return { cls: 'plate-authority', stroke: '#B84A27', tag: 'Authority' };
  if (node?.type === 'reasoning') return { cls: '', stroke: '#14284B', tag: 'Override / Logic' };
  return { cls: '', stroke: '#14284B', tag: 'Primary Record' };
}

/**
 * Renders section prose + GitHub-style markdown tables with inline `<ref id="...">` buttons.
 */
function RichRefBlock({ content, nodes, pinnedClaimId, onSelectClaim }) {
  if (!content) return null;
  const lines = content.split('\n');
  const blocks = [];
  let i = 0;

  const renderInline = (raw) => {
    const parts = [];
    const regex = /<ref\s+id=['"]([^'"]+)['"]>(.*?)<\/ref>/gs;
    let last = 0;
    let m;
    while ((m = regex.exec(raw)) !== null) {
      if (m.index > last) {
        parts.push(renderBoldAndCode(raw.slice(last, m.index)));
      }
      const refId = m[1];
      const inner = m[2];
      const target = nodes[refId];
      const active = pinnedClaimId === refId;
      const caveat = isCaveat(target?.audit?.status);
      parts.push(html`
        <button
          type="button"
          data-ref-id=${refId}
          class=${`clause-highlight ${active ? 'is-active' : ''} ${caveat ? 'is-caveat' : ''}`}
          onClick=${(e) => {
            e.stopPropagation();
            onSelectClaim(refId);
          }}
        >
          ${inner}
        </button>
      `);
      last = m.index + m[0].length;
    }
    if (last < raw.length) {
      parts.push(renderBoldAndCode(raw.slice(last)));
    }
    return parts;
  };

  const renderBoldAndCode = (txt) => {
    const segs = txt.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    return segs.map((seg) => {
      if (seg.startsWith('**') && seg.endsWith('**')) {
        return html`<strong>${seg.slice(2, -2)}</strong>`;
      }
      if (seg.startsWith('`') && seg.endsWith('`')) {
        return html`<code class="font-mono-data">${seg.slice(1, -1)}</code>`;
      }
      return seg;
    });
  };

  while (i < lines.length) {
    const line = lines[i].trim();
    if (!line) {
      i++;
      continue;
    }
    if (line.startsWith('|')) {
      const tableLines = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        tableLines.push(lines[i].trim());
        i++;
      }
      if (tableLines.length >= 2) {
        const parseRow = (rowStr) =>
          rowStr
            .replace(/^\|/, '')
            .replace(/\|$/, '')
            .split('|')
            .map((c) => c.trim());
        const headers = parseRow(tableLines[0]);
        const dataRows = tableLines.slice(2).map(parseRow);
        blocks.push(html`
          <div class="bk-table-wrap">
            <table class="bk-schedule-table">
              <thead>
                <tr>
                  ${headers.map((hCell) => html`<th>${hCell}</th>`)}
                </tr>
              </thead>
              <tbody>
                ${dataRows.map(
                  (row) => html`
                    <tr>
                      ${row.map((cell) => html`<td>${renderInline(cell)}</td>`)}
                    </tr>
                  `
                )}
              </tbody>
            </table>
          </div>
        `);
        continue;
      }
    }
    blocks.push(html`<p class="bk-prose-line">${renderInline(line)}</p>`);
    i++;
  }
  return html`<div>${blocks}</div>`;
}

function EmergingQuestionCard({ question, matterId, onUpdated }) {
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState(null);
  const [desc, setDesc] = useState('2021 Toyota Camry');
  const [val, setVal] = useState('16500.00');
  const [intention, setIntention] = useState('retain_and_reaffirm');
  const [credName, setCredName] = useState(question.entity_id || 'Synchrony Bank');
  const [credAmt, setCredAmt] = useState('2400.00');
  const [rationale, setRationale] = useState('Confirmed with client and source documents.');

  const submitAnswer = async (selectedOption, payload = {}) => {
    setSubmitting(true);
    setErr(null);
    try {
      const res = await fetch(
        `/api/v1/bankruptcy/matters/${encodeURIComponent(matterId)}/questions/${encodeURIComponent(question.question_id)}/answer`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            selected_option: selectedOption,
            actor_name: 'Paralegal Workbench',
            actor_role: 'paralegal',
            rationale,
            payload,
          }),
        }
      );
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${res.status}`);
      }
      const nextState = await res.json();
      onUpdated(nextState);
    } catch (e) {
      setErr(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return html`
    <div class="bk-triage-card is-question">
      <div class="bk-triage-head">
        <span class="arch-stamp is-caveat font-mono-data">▪ ${question.rule_id}</span>
        <span class="kicker-label">${(question.trigger_forms || []).join(', ')}</span>
      </div>
      <p class="bk-triage-prompt">${question.prompt}</p>

      ${question.rule_id === 'SECURED_LOAN_MISSING_COLLATERAL_VALUE' && html`
        <div class="bk-inline-form">
          <input class="bk-input" value=${desc} onInput=${(e) => setDesc(e.target.value)} placeholder="Vehicle / Property Description" />
          <input class="bk-input font-mono-data" value=${val} onInput=${(e) => setVal(e.target.value)} placeholder="Market Value ($)" />
          <button
            class="btn btn-primary btn-compact"
            disabled=${submitting}
            onClick=${() => submitAnswer('add_or_link_collateral_asset', { description: desc, category: 'vehicle', current_value: val })}
          >
            ${submitting ? 'Saving...' : 'Link Collateral'}
          </button>
        </div>
      `}

      ${question.rule_id === 'SECURED_CLAIM_MISSING_INTENTION' && html`
        <div class="bk-inline-form">
          <select class="bk-select" value=${intention} onChange=${(e) => setIntention(e.target.value)}>
            <option value="retain_and_reaffirm">Retain & Reaffirm</option>
            <option value="retain_and_redeem">Retain & Redeem</option>
            <option value="surrender">Surrender Collateral</option>
          </select>
          <button
            class="btn btn-primary btn-compact"
            disabled=${submitting}
            onClick=${() => submitAnswer('set_statement_of_intention', { statement_of_intention: intention })}
          >
            Set Form 108
          </button>
        </div>
      `}

      ${question.rule_id === 'UNLISTED_CREDITOR_FROM_BANK_OUTFLOW' && html`
        <div class="bk-inline-form">
          <input class="bk-input" value=${credName} onInput=${(e) => setCredName(e.target.value)} placeholder="Creditor Name" />
          <input class="bk-input font-mono-data" value=${credAmt} onInput=${(e) => setCredAmt(e.target.value)} placeholder="Claim Balance ($)" />
          <button
            class="btn btn-primary btn-compact"
            disabled=${submitting}
            onClick=${() => submitAnswer('add_creditor_claim', { creditor_name: credName, total_claim_amount: credAmt, priority_type: 'general_unsecured' })}
          >
            Add Creditor
          </button>
          <button
            class="btn btn-compact"
            disabled=${submitting}
            onClick=${() => submitAnswer('confirm_non_debt_payee', {})}
          >
            Not a Debt
          </button>
        </div>
      `}

      ${question.rule_id === 'ASSET_MISSING_LIEN_STATUS' && html`
        <div class="bk-inline-form">
          <button
            class="btn btn-primary btn-compact"
            disabled=${submitting}
            onClick=${() => submitAnswer('confirm_free_and_clear', {})}
          >
            Confirm Owned Free & Clear
          </button>
        </div>
      `}

      ${!['SECURED_LOAN_MISSING_COLLATERAL_VALUE', 'SECURED_CLAIM_MISSING_INTENTION', 'UNLISTED_CREDITOR_FROM_BANK_OUTFLOW', 'ASSET_MISSING_LIEN_STATUS'].includes(question.rule_id) && html`
        <div class="bk-inline-form">
          <input class="bk-input" value=${rationale} onInput=${(e) => setRationale(e.target.value)} placeholder="Audit rationale" />
          <button
            class="btn btn-primary btn-compact"
            disabled=${submitting}
            onClick=${() => submitAnswer(question.resolution_options?.[0] || 'confirm_closed_account', { current_value: val })}
          >
            Resolve Gap
          </button>
        </div>
      `}

      ${err && html`<div class="bk-error-text">${err}</div>`}
    </div>
  `;
}

function TensionResolveCard({ tension, matterId, onUpdated }) {
  const [rationale, setRationale] = useState('Verified gift/reimbursement from relative; excluded from CMI.');
  const [busy, setBusy] = useState(false);

  const handleResolve = async () => {
    setBusy(true);
    try {
      const res = await fetch(
        `/api/v1/bankruptcy/matters/${encodeURIComponent(matterId)}/tensions/${encodeURIComponent(tension.tension_id)}/resolve`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            actor_name: 'Paralegal Workbench',
            actor_role: 'paralegal',
            rationale,
          }),
        }
      );
      if (res.ok) {
        onUpdated(await res.json());
      }
    } finally {
      setBusy(false);
    }
  };

  return html`
    <div class=${`tension-callout ${tension.severity === 'warning' ? 'is-warning' : ''}`}>
      <div class=${`tension-callout-header ${tension.severity === 'warning' ? 'is-warning' : ''}`}>
        <span>▪ ${tension.severity === 'blocker' ? 'CRITICAL CONTRADICTION' : 'ADVISORY WARNING'} · ${tension.tension_id}</span>
      </div>
      <p class="bk-triage-prompt">${tension.description}</p>
      <div class="bk-inline-form">
        <input class="bk-input" value=${rationale} onInput=${(e) => setRationale(e.target.value)} placeholder="Resolution rationale..." />
        <button class="btn btn-compact" disabled=${busy} onClick=${handleResolve}>
          ${busy ? 'Resolving...' : 'Mark Resolved'}
        </button>
      </div>
    </div>
  `;
}

function SourceInspectorDrawer({ node, matterId, onClose }) {
  if (!node) return null;
  const loc = node.locator;
  const rawUrl =
    loc?.file_name && matterId
      ? `/api/v1/bankruptcy/matters/${encodeURIComponent(matterId)}/files/${encodeURIComponent(loc.file_name)}/raw${loc.page ? `#page=${loc.page}` : ''}`
      : null;

  return html`
    <div class="inspector-backdrop" onClick=${onClose}>
      <aside class="source-inspector-drawer" onClick=${(e) => e.stopPropagation()} aria-label="Source Inspector">
        <div class="drawer-header">
          <div>
            <div class="kicker-label">Source Verification Inspector</div>
            <h3 class="card-heading">${node.title}</h3>
          </div>
          <button class="btn btn-compact" onClick=${onClose}>Close ×</button>
        </div>
        <div class="drawer-body">
          ${loc && html`
            <div class="pdf-page-simulator">
              <div class="kicker-label font-mono-data">
                FILE: ${loc.file_name} ${loc.page ? `· PAGE ${loc.page}` : ''}
                ${loc.bounding_box ? ` · BBOX [${loc.bounding_box.join(', ')}]` : ''}
              </div>
              <div class="pdf-bbox-highlight">
                “${node.quote || node.body}”
              </div>
              <div class="kicker-label font-mono-data">
                LOCATOR KEY: ${loc.locator_key || 'N/A'} · DIGEST: ${loc.payload_hash || 'N/A'}
              </div>
            </div>
          `}
          ${!loc && html`
            <div class="pdf-page-simulator">
              <div class="kicker-label">${node.type === 'authority' ? 'Controlling Statutory Rule' : 'Deterministic Calculation'}</div>
              <p>${node.quote || node.body || node.formula}</p>
            </div>
          `}
          ${rawUrl && html`
            <a class="btn btn-primary" href=${rawUrl} target="_blank" rel="noopener noreferrer">
              Open Original Client PDF ${loc?.page ? `(p. ${loc.page})` : ''} ↗
            </a>
          `}
        </div>
      </aside>
    </div>
  `;
}

function FilingPacketDrawer({ caseState, onClose, onStateUpdated }) {
  const graph = caseState.case_graph;
  const readiness = caseState.readiness;
  const [packetFiles, setPacketFiles] = useState(caseState.last_packet_files || []);
  const [compiling, setCompiling] = useState(false);
  const [attyName, setAttyName] = useState(graph.attorney_name || 'Elena Counsel, Esq.');
  const [barNum, setBarNum] = useState(graph.attorney_bar_number || 'CA-310044');
  const [subMode, setSubMode] = useState('ecf_train');
  const [attested, setAttested] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [latestReceipt, setLatestReceipt] = useState(
    (caseState.filing_receipts || []).slice(-1)[0] || null
  );

  const compilePacket = async (allowDraft = false) => {
    setCompiling(true);
    setErrorMsg(null);
    try {
      const res = await fetch(
        `/api/v1/bankruptcy/matters/${encodeURIComponent(graph.matter_id)}/compile-packet`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ allow_draft: allowDraft }),
        }
      );
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail?.message || data.detail || `HTTP ${res.status}`);
      }
      setPacketFiles(data.files || []);
      const refreshed = await fetch(`/api/v1/bankruptcy/matters/${encodeURIComponent(graph.matter_id)}/case`);
      if (refreshed.ok) onStateUpdated(await refreshed.json());
    } catch (e) {
      setErrorMsg(e.message);
    } finally {
      setCompiling(false);
    }
  };

  const uploadDecl = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(
      `/api/v1/bankruptcy/matters/${encodeURIComponent(graph.matter_id)}/declaration`,
      { method: 'POST', body: fd }
    );
    if (res.ok) onStateUpdated(await res.json());
  };

  const submitToCourt = async () => {
    setSubmitting(true);
    setErrorMsg(null);
    try {
      const res = await fetch(
        `/api/v1/bankruptcy/matters/${encodeURIComponent(graph.matter_id)}/submit`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            submission_mode: subMode,
            attorney_name: attyName,
            attorney_bar_number: barNum,
            attested,
          }),
        }
      );
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || `HTTP ${res.status}`);
      }
      setLatestReceipt(data);
      const refreshed = await fetch(`/api/v1/bankruptcy/matters/${encodeURIComponent(graph.matter_id)}/case`);
      if (refreshed.ok) onStateUpdated(await refreshed.json());
    } catch (e) {
      setErrorMsg(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return html`
    <div class="inspector-backdrop" onClick=${onClose}>
      <aside class="source-inspector-drawer" onClick=${(e) => e.stopPropagation()} aria-label="Filing Readiness and Submission">
        <div class="drawer-header">
          <div>
            <div class="kicker-label">Strict Zero-Doubt Gate · ${graph.district} Ch. ${graph.chapter}</div>
            <h3 class="card-heading">Official Packet & Rule 9011 Submission</h3>
          </div>
          <button class="btn btn-compact" onClick=${onClose}>Close ×</button>
        </div>
        <div class="drawer-body">
          <div class=${`bk-gate-banner ${readiness?.status === 'READY' ? 'is-ready' : 'is-blocked'}`}>
            <strong>GATE STATUS: ${readiness?.status || 'BLOCKED'}</strong>
            ${(readiness?.blocking_reasons || []).map((r) => html`<div>• ${r}</div>`)}
            ${readiness?.status === 'READY' && html`<div>All extracted values verified, zero open questions, zero critical contradictions.</div>`}
          </div>

          <div class="bk-inline-form">
            <button
              class="btn btn-primary"
              disabled=${compiling || readiness?.status !== 'READY'}
              onClick=${() => compilePacket(false)}
            >
              ${compiling ? 'Baking PDFs...' : 'Compile Official Packet'}
            </button>
            <button
              class="btn"
              disabled=${compiling}
              onClick=${() => compilePacket(true)}
            >
              Preview Draft Packet
            </button>
          </div>

          ${packetFiles.length > 0 && html`
            <div>
              <div class="kicker-label">Compiled Artifacts (${packetFiles.length})</div>
              <ul class="bk-file-list">
                ${packetFiles.map((fn) => html`
                  <li>
                    <a
                      class="font-mono-data"
                      href=${`/api/v1/bankruptcy/matters/${encodeURIComponent(graph.matter_id)}/packet/files/${encodeURIComponent(fn)}`}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      ${fn} ↗
                    </a>
                  </li>
                `)}
              </ul>
            </div>
          `}

          <div class="bk-section-box">
            <div class="kicker-label">Step 2: Wet-Signed Declaration (${graph.district === 'CACB' ? 'F 5005-4' : 'CAEB e-Sig'})</div>
            <div class="bk-inline-form">
              <input type="file" accept=".pdf" onChange=${uploadDecl} />
              <span class="font-mono-data">
                ${graph.signed_declaration_uploaded ? `Signed ✓ (${graph.signed_declaration_sha256?.slice(0, 18)})` : 'Not uploaded yet'}
              </span>
            </div>
          </div>

          <div class="bk-section-box">
            <div class="kicker-label">Step 3: Rule 9011 Attorney Attestation & Submit</div>
            <div class="bk-stack-form">
              <input class="bk-input" value=${attyName} onInput=${(e) => setAttyName(e.target.value)} placeholder="Supervising Attorney Name" />
              <input class="bk-input font-mono-data" value=${barNum} onInput=${(e) => setBarNum(e.target.value)} placeholder="CA State Bar #" />
              <select class="bk-select" value=${subMode} onChange=${(e) => setSubMode(e.target.value)}>
                <option value="ecf_train">ecf_train (Court Training Sandbox)</option>
                <option value="filing_agent">filing_agent (Design Partner Agent)</option>
                <option value="firm_attorney">firm_attorney (Firm Live Credentials)</option>
              </select>
              <label class="bk-checkbox-row">
                <input type="checkbox" checked=${attested} onChange=${(e) => setAttested(e.target.checked)} />
                <span>I certify under Fed. R. Bankr. P. 9011 that all schedules and calculations are accurate.</span>
              </label>
              <button
                class="btn btn-primary"
                disabled=${submitting || readiness?.status !== 'READY' || !graph.signed_declaration_uploaded || packetFiles.length === 0}
                onClick=${submitToCourt}
              >
                ${submitting ? 'Submitting to Court...' : `Submit to ${graph.district} Court`}
              </button>
            </div>
          </div>

          ${errorMsg && html`<div class="bk-error-text">${errorMsg}</div>`}

          ${latestReceipt && html`
            <div class="bk-receipt-card">
              <div class="kicker-label">Court Filing Receipt · ${latestReceipt.district}</div>
              <div class="font-mono-data">Case Number: <strong>${latestReceipt.assigned_case_number}</strong></div>
              <div class="font-mono-data">Mode: ${latestReceipt.submission_mode} · Receipt: ${latestReceipt.receipt_sha256}</div>
              <ol class="bk-step-log">
                ${(latestReceipt.step_log || []).map((st) => html`<li>${st}</li>`)}
              </ol>
            </div>
          `}
        </div>
      </aside>
    </div>
  `;
}

function BankruptcyApp() {
  const [matters, setMatters] = useState([]);
  const [activeMatterId, setActiveMatterId] = useState(null);
  const [caseState, setCaseState] = useState(null);
  const [pinnedClaimId, setPinnedClaimId] = useState(null);
  const [expandedL2Ids, setExpandedL2Ids] = useState([]);
  const [inspectorNode, setInspectorNode] = useState(null);
  const [showPacketDrawer, setShowPacketDrawer] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [newCaseId, setNewCaseId] = useState('');
  const [newChapter, setNewChapter] = useState('7');
  const [newDistrict, setNewDistrict] = useState('CACB');
  const [uploadFiles, setUploadFiles] = useState([]);
  const [busyMsg, setBusyMsg] = useState(null);
  const [paths, setPaths] = useState([]);

  const viewportRef = useRef(null);

  const loadMatters = useCallback(async (selectId = null) => {
    const res = await fetch('/api/v1/bankruptcy/matters');
    if (!res.ok) return;
    const data = await res.json();
    const list = data.matters || [];
    setMatters(list);
    const chosen = selectId || activeMatterId || list[0]?.matter_id || null;
    if (chosen) {
      setActiveMatterId(chosen);
      const cRes = await fetch(`/api/v1/bankruptcy/matters/${encodeURIComponent(chosen)}/case`);
      if (cRes.ok) setCaseState(await cRes.json());
    }
  }, [activeMatterId]);

  useEffect(() => {
    loadMatters();
  }, []);

  const selectMatter = async (mId) => {
    setActiveMatterId(mId);
    setPinnedClaimId(null);
    setExpandedL2Ids([]);
    const res = await fetch(`/api/v1/bankruptcy/matters/${encodeURIComponent(mId)}/case`);
    if (res.ok) setCaseState(await res.json());
  };

  const bundle = caseState?.compiled_bundle || null;
  const nodes = bundle?.nodes || {};
  const l1Ids = useMemo(() => {
    if (!pinnedClaimId || !nodes[pinnedClaimId]) return [];
    return nodes[pinnedClaimId].direct_child_ids || [];
  }, [pinnedClaimId, nodes]);

  const colsClass = expandedL2Ids.length > 0 ? 'cols-3' : l1Ids.length > 0 ? 'cols-2' : 'cols-1';

  const recomputeBezierPaths = useCallback(() => {
    const vp = viewportRef.current;
    if (!vp || !pinnedClaimId) {
      setPaths([]);
      return;
    }
    const vpRect = vp.getBoundingClientRect();
    const nextPaths = [];
    const anchorEl = vp.querySelector(`[data-ref-id="${pinnedClaimId}"]`);
    if (anchorEl) {
      const aRect = anchorEl.getBoundingClientRect();
      const x1 = aRect.right - vpRect.left;
      const y1 = aRect.top + aRect.height / 2 - vpRect.top;
      for (const cid of l1Ids) {
        const cardEl = vp.querySelector(`[data-card-id="${cid}"]`);
        if (!cardEl) continue;
        const cRect = cardEl.getBoundingClientRect();
        const x2 = cRect.left - vpRect.left;
        const y2 = cRect.top + 22 - vpRect.top;
        const dx = Math.max(40, (x2 - x1) * 0.5);
        nextPaths.push({
          d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
          stroke: getToneForNode(nodes[cid]).stroke,
          x1,
          y1,
          x2,
          y2,
        });
      }
    }
    for (const l2Id of expandedL2Ids) {
      const parentCard = l1Ids.find((id) => (nodes[id]?.direct_child_ids || []).includes(l2Id));
      const pEl = parentCard ? vp.querySelector(`[data-card-id="${parentCard}"]`) : null;
      const cEl = vp.querySelector(`[data-card-id="${l2Id}"]`);
      if (!pEl || !cEl) continue;
      const pRect = pEl.getBoundingClientRect();
      const cRect = cEl.getBoundingClientRect();
      const x1 = pRect.right - vpRect.left;
      const y1 = pRect.top + 22 - vpRect.top;
      const x2 = cRect.left - vpRect.left;
      const y2 = cRect.top + 22 - vpRect.top;
      const dx = Math.max(40, (x2 - x1) * 0.5);
      nextPaths.push({
        d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
        stroke: '#B84A27',
        x1,
        y1,
        x2,
        y2,
      });
    }
    setPaths(nextPaths);
  }, [pinnedClaimId, l1Ids, expandedL2Ids, nodes]);

  useEffect(() => {
    const id = requestAnimationFrame(recomputeBezierPaths);
    window.addEventListener('resize', recomputeBezierPaths);
    return () => {
      cancelAnimationFrame(id);
      window.removeEventListener('resize', recomputeBezierPaths);
    };
  }, [recomputeBezierPaths, caseState]);

  const handleCreateAndExtract = async (e) => {
    e.preventDefault();
    if (!newCaseId.trim()) return;
    setBusyMsg('Creating matter, uploading PDFs, and verifying coordinates...');
    try {
      const initRes = await fetch('/api/v1/bankruptcy/matters', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          matter_id: newCaseId.trim(),
          chapter: newChapter,
          district: newDistrict,
        }),
      });
      if (!initRes.ok) throw new Error('Failed to initialize case.');
      const created = await initRes.json();
      const targetId = created.case_graph.matter_id;

      if (uploadFiles.length > 0) {
        const fd = new FormData();
        for (const f of uploadFiles) fd.append('files', f);
        await fetch(`/api/v1/bankruptcy/matters/${encodeURIComponent(targetId)}/upload`, {
          method: 'POST',
          body: fd,
        });
      }
      await fetch(`/api/v1/bankruptcy/matters/${encodeURIComponent(targetId)}/extract`, {
        method: 'POST',
      });
      setShowUploadModal(false);
      setNewCaseId('');
      setUploadFiles([]);
      await loadMatters(targetId);
    } finally {
      setBusyMsg(null);
    }
  };

  const graph = caseState?.case_graph;
  const calcs = caseState?.calculations;
  const readiness = caseState?.readiness;
  const openQuestions = (caseState?.emerging_questions || []).filter((q) => q.status === 'open');
  const openTensions = [
    ...(caseState?.tensions || []),
    ...(caseState?.plausibility_warnings || []),
  ].filter((t) => !(caseState?.resolved_tension_records || {})[t.tension_id]);

  return html`
    <div class="app-shell">
      <header class="top-bar">
        <div class="top-bar-left">
          <span class="brand-title">Bankruptcy Case Workbench</span>
          <select
            class="bk-select"
            aria-label="Select bankruptcy matter"
            value=${activeMatterId || ''}
            onChange=${(e) => selectMatter(e.target.value)}
          >
            ${matters.map(
              (m) => html`
                <option value=${m.matter_id}>
                  ${m.matter_id} · Ch.${m.chapter} (${m.district}) · ${m.readiness_status}
                </option>
              `
            )}
          </select>
          ${graph && html`
            <span class="arch-stamp font-mono-data">CH. ${graph.chapter} · ${graph.district}</span>
          `}
        </div>
        <div class="top-bar-right">
          <button class="btn" onClick=${() => setShowUploadModal(true)}>+ New Case / Upload PDFs</button>
          ${caseState && html`
            <button
              class=${`btn ${readiness?.status === 'READY' ? 'btn-primary' : ''}`}
              onClick=${() => setShowPacketDrawer(true)}
            >
              Filing Gate: ${readiness?.status || 'BLOCKED'} →
            </button>
          `}
        </div>
      </header>

      <main id="bk-workspace-main" class="spatial-viewport" ref=${viewportRef}>
        <svg class="connector-svg-layer" aria-hidden="true">
          ${paths.map(
            (p) => html`
              <g>
                <path d=${p.d} fill="none" stroke=${p.stroke} stroke-width="1.5" />
                <rect x=${p.x1 - 2.5} y=${p.y1 - 2.5} width="5" height="5" fill=${p.stroke} />
                <rect x=${p.x2 - 2.5} y=${p.y2 - 2.5} width="5" height="5" fill=${p.stroke} />
              </g>
            `
          )}
        </svg>

        ${!caseState && html`<div class="bk-empty-state">Loading bankruptcy case matters...</div>`}

        ${caseState && html`
          <div class=${`bounded-canvas-grid ${colsClass}`}>
            <!-- Column 1 (L0): Audit Triage + Schedules & Calculators Broadsheet -->
            <section class="canvas-column" aria-label="L0 Case Schedules and Audit Triage">
              <div class="lane-header">
                <span class="lane-title">L0 · Case Schedules & Calculators</span>
                <span class="font-mono-data">
                  ${bundle?.audit_summary?.verified_count || 0}/${bundle?.audit_summary?.total_claims || 0} VERIFIED
                </span>
              </div>

              ${(openQuestions.length > 0 || openTensions.length > 0) && html`
                <div class="bk-triage-strip">
                  <div class="kicker-label">
                    Audit Triage Queue (${openQuestions.length} Open Question(s), ${openTensions.length} Contradiction/Advisory)
                  </div>
                  ${openQuestions.map(
                    (q) => html`<${EmergingQuestionCard} question=${q} matterId=${graph.matter_id} onUpdated=${setCaseState} />`
                  )}
                  ${openTensions.map(
                    (t) => html`<${TensionResolveCard} tension=${t} matterId=${graph.matter_id} onUpdated=${setCaseState} />`
                  )}
                </div>
              `}

              ${calcs?.exemptions && html`
                <div class="bk-opt-grid">
                  ${calcs.exemptions.evaluations.map((ev) => {
                    const isRec = ev.regime_id === calcs.exemptions.recommended_regime_id;
                    return html`
                      <div class=${`bk-opt-card ${isRec ? 'is-recommended' : ''}`}>
                        <div class="kicker-label">${ev.regime_id} ${isRec ? '★ RECOMMENDED' : ''}</div>
                        <div class="font-mono-data">Exempt: <strong>${formatCurrency(ev.total_exempt_equity)}</strong></div>
                        <div class="font-mono-data">Non-Exempt Exposed: <strong>${formatCurrency(ev.total_non_exempt_equity)}</strong></div>
                      </div>
                    `;
                  })}
                </div>
              `}

              ${(bundle?.artifact?.sections || []).map((sec) => html`
                <article class="broadsheet-section">
                  <h2 class="section-heading">${sec.section_title}</h2>
                  <div class="section-prose">
                    <${RichRefBlock}
                      content=${sec.content}
                      nodes=${nodes}
                      pinnedClaimId=${pinnedClaimId}
                      onSelectClaim=${(id) => {
                        if (pinnedClaimId === id) {
                          setPinnedClaimId(null);
                          setExpandedL2Ids([]);
                        } else {
                          setPinnedClaimId(id);
                          setExpandedL2Ids([]);
                        }
                      }}
                    />
                  </div>
                </article>
              `)}
            </section>

            <!-- Column 2 (L1): Primary Support (Calculations & Client PDF Evidence) -->
            ${l1Ids.length > 0 && html`
              <section class="canvas-column" aria-label="L1 Primary Support">
                <div class="lane-header">
                  <span class="lane-title">L1 · Deterministic Math & Client PDFs</span>
                  <button
                    class="btn btn-compact"
                    onClick=${() => {
                      setPinnedClaimId(null);
                      setExpandedL2Ids([]);
                    }}
                  >
                    × Close L1
                  </button>
                </div>
                ${l1Ids.map((nid, idx) => {
                  const node = nodes[nid];
                  if (!node) return null;
                  const tone = getToneForNode(node);
                  const childAuths = node.direct_child_ids || [];
                  return html`
                    <article class=${`spatial-node-card ${tone.cls}`} data-card-id=${nid}>
                      <div class="plate-header-strip">
                        <span class="kicker-label">▪ FIG. 1.${idx + 1} · ${tone.tag}</span>
                        <span class="arch-stamp font-mono-data">${formatAuditLabel(node.audit?.status)}</span>
                      </div>
                      <h3 class="card-heading">${node.title}</h3>
                      ${node.formula && html`<pre class="font-mono-data bk-formula-box">${node.formula}</pre>`}
                      ${node.quote && html`<blockquote class="evidence-blockquote">“${node.quote}”</blockquote>`}
                      ${node.body && html`<p class="card-body-prose">${node.body}</p>`}
                      <div class="plate-footer-actions">
                        <button class="btn btn-compact" onClick=${() => setInspectorNode(node)}>
                          Inspect Source
                        </button>
                        ${childAuths.length > 0 && html`
                          <button
                            class="btn btn-compact"
                            onClick=${() => setExpandedL2Ids(childAuths)}
                          >
                            View Authority (${childAuths.length}) →
                          </button>
                        `}
                      </div>
                    </article>
                  `;
                })}
              </section>
            `}

            <!-- Column 3 (L2+): Controlling Statutory Authorities & Reference Tables -->
            ${expandedL2Ids.length > 0 && html`
              <section class="canvas-column" aria-label="L2+ Controlling Authorities">
                <div class="lane-header">
                  <span class="lane-title">L2+ · Statutes & Reference Tables</span>
                  <button class="btn btn-compact" onClick=${() => setExpandedL2Ids([])}>
                    × Close L2+
                  </button>
                </div>
                ${expandedL2Ids.map((nid, idx) => {
                  const node = nodes[nid];
                  if (!node) return null;
                  return html`
                    <article class="spatial-node-card plate-authority" data-card-id=${nid}>
                      <div class="plate-header-strip">
                        <span class="kicker-label">▪ FIG. 2.${idx + 1} · STATUTORY AUTHORITY</span>
                      </div>
                      <h3 class="card-heading">${node.title}</h3>
                      <blockquote class="evidence-blockquote">${node.quote}</blockquote>
                    </article>
                  `;
                })}
              </section>
            `}
          </div>
        `}
      </main>

      ${inspectorNode && html`
        <${SourceInspectorDrawer}
          node=${inspectorNode}
          matterId=${graph?.matter_id}
          onClose=${() => setInspectorNode(null)}
        />
      `}

      ${showPacketDrawer && caseState && html`
        <${FilingPacketDrawer}
          caseState=${caseState}
          onClose=${() => setShowPacketDrawer(false)}
          onStateUpdated=${setCaseState}
        />
      `}

      ${showUploadModal && html`
        <div class="inspector-backdrop" onClick=${() => setShowUploadModal(false)}>
          <div class="source-inspector-drawer" onClick=${(e) => e.stopPropagation()}>
            <div class="drawer-header">
              <h3 class="card-heading">Create Case & Upload Uncategorized Client PDFs</h3>
              <button class="btn btn-compact" onClick=${() => setShowUploadModal(false)}>Close ×</button>
            </div>
            <form class="drawer-body" onSubmit=${handleCreateAndExtract}>
              <input class="bk-input" required placeholder="Case Slug (e.g., bk_ch7_doe_2026)" value=${newCaseId} onInput=${(e) => setNewCaseId(e.target.value)} />
              <div class="bk-inline-form">
                <select class="bk-select" value=${newChapter} onChange=${(e) => setNewChapter(e.target.value)}>
                  <option value="7">Chapter 7</option>
                  <option value="13">Chapter 13</option>
                </select>
                <select class="bk-select" value=${newDistrict} onChange=${(e) => setNewDistrict(e.target.value)}>
                  <option value="CACB">CACB (Central Dist. CA)</option>
                  <option value="CAEB">CAEB (Eastern Dist. CA)</option>
                </select>
              </div>
              <input type="file" multiple accept=".pdf,.csv,.xlsx,.md,.txt" onChange=${(e) => setUploadFiles(Array.from(e.target.files || []))} />
              <button class="btn btn-primary" type="submit" disabled=${Boolean(busyMsg)}>
                ${busyMsg || 'Upload, Extract & Audit Case'}
              </button>
            </form>
          </div>
        </div>
      `}
    </div>
  `;
}

render(html`<${BankruptcyApp} />`, document.getElementById('bk-app-root'));
