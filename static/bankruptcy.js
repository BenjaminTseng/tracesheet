import { h, render } from 'preact';
import { useState, useEffect, useRef, useCallback, useMemo } from 'preact/hooks';
import htm from 'htm';

const html = htm.bind(h);

const RULE_TITLE_MAP = {
  SECURED_LOAN_MISSING_COLLATERAL_VALUE: 'Missing Collateral Property & Market Value',
  SECURED_CLAIM_MISSING_INTENTION: 'Missing Chapter 7 Statement of Intention',
  UNLISTED_CREDITOR_FROM_BANK_OUTFLOW: 'Possible Unlisted Creditor in Bank Activity',
  ASSET_MISSING_LIEN_STATUS: 'Unconfirmed Asset Lien Status',
  POTENTIAL_PERSONAL_INJURY_OR_WORKERS_COMP_CLAIM: 'Possible Unscheduled Personal Injury / Workers Comp Claim',
  SOFA_LAWSUIT_PLAINTIFF_MISSING_ON_AB: 'SOFA Line 9 Plaintiff Action Missing on Schedule A/B',
  SOFA_LAWSUIT_DEFENDANT_MISSING_ON_EF: 'SOFA Line 9 Lawsuit Defendant Claim Missing on Schedule E/F',
  RENTER_MISSING_SECURITY_DEPOSIT_LINE_28: 'Renter Security Deposit Check (Schedule A/B Line 22/28)',
  PAYSTUB_60_DAY_CONTINUITY_GAP: '60-Day Pre-Petition Paystub Continuity Gap (§ 521)',
  HOMESTEAD_522P_ROLLOVER_INQUIRY: 'Homestead § 522(p)(2)(B) Same-State Rollover Inquiry',
  MARRIED_SEPARATE_703_SPOUSAL_WAIVER: 'Married Filing Separately CCP § 703.140(a)(2) Spousal Waiver',
  UNKNOWN_VALUATION_CAPPED_EXEMPTION_RISK: 'Schwab v. Reilly Unknown-Value Windfall Risk Under Capped System',
  CH13_FOUR_YEAR_TAX_RETURN_MISSING: 'Chapter 13 Four-Year Tax Return Verification (11 U.S.C. § 1308)',
  MANDATORY_ASSET_AND_WINDFALL_SWEEP: 'Mandatory Asset Sweep & 180-Day Windfall Check (§ 541(a)(5))',
};

const TENSION_TITLE_MAP = {
  LARGE_UNEXPLAINED_DEPOSIT: 'Large Unexplained Deposit vs. Scheduled Income',
  INCOME_VS_TAX_VARIANCE: 'Paystub CMI vs. Tax Return Income Variance',
  tension_ch13_plan_infeasible: 'Chapter 13 Plan Feasibility Shortfall (11 U.S.C. § 1325(a)(6))',
  tension_180_day_windfall: '180-Day Post-Petition Windfall Estate Inclusion (§ 541(a)(5))',
};

const FORM_LABEL_MAP = {
  B101: 'Form B 101 (Petition)',
  B106Sum: 'Form B 106Sum (Summary)',
  B106AB: 'Schedule A/B (B 106A/B)',
  B106C: 'Schedule C (B 106C)',
  B106D: 'Schedule D (B 106D)',
  B106EF: 'Schedule E/F (B 106E/F)',
  B106G: 'Schedule G (B 106G)',
  B106H: 'Schedule H (B 106H)',
  B106I: 'Schedule I (B 106I)',
  B106J: 'Schedule J (B 106J)',
  B106Dec: 'Form B 106Dec',
  B107: 'Form B 107 (SOFA)',
  B108: 'Form B 108 (Intention)',
  B121: 'Form B 121 (Private SSN)',
  B122A1: 'Form B 122A-1 (Ch. 7 CMI)',
  B122A2: 'Form B 122A-2 (Means Test)',
  B122C1: 'Form B 122C-1 (Ch. 13 CMI)',
  B122C2: 'Form B 122C-2 (Disposable Income)',
  CACB_F1007_1: 'CACB Form F 1007-1 (Matrix Verif.)',
  CACB_F5005_4: 'CACB Form F 9011-1 (E-Sig Dec.)',
  CACB_F3015_1_01: 'CACB Form F 3015-1.01 (Ch. 13 Plan)',
  CACB_F3015_1_7_RARA: 'CACB Form F 3015-1.7 (RARA)',
  CAEB_EDC_3_080: 'CAEB Form EDC 3-080 (Ch. 13 Plan)',
  CAEB_ESIG: 'CAEB Form EDC 2-100 (Matrix Verif.)',
  CAEB_EDC_3_096: 'CAEB Form EDC 3-096 (RARA)',
};

const SUBMISSION_MODE_LABELS = {
  ecf_train: 'CM/ECF Court Training Sandbox',
  filing_agent: 'Design Partner Supervised Filing Agent',
  firm_attorney: 'Firm Live Attorney Credentials',
};

function CloseIcon() {
  return html`
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
      <path d="M3 3l10 10M13 3L3 13" />
    </svg>
  `;
}

function ArrowRightIcon() {
  return html`
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
      <path d="M3 8h10M9 4l4 4-4 4" />
    </svg>
  `;
}

function ArrowLeftIcon() {
  return html`
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
      <path d="M13 8H3M7 4L3 8l4 4" />
    </svg>
  `;
}

function ExternalIcon() {
  return html`
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
      <path d="M7 3H3v10h10V9M9 3h4v4M6 10L13 3" />
    </svg>
  `;
}

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
  return map[status] || 'Pending';
}

function formatRegimeLabel(ev) {
  if (ev.display_name) return ev.display_name;
  if (ev.regime_id === 'CA_CCP_703_140') return 'CCP § 703.140(b) (Wildcard System)';
  if (ev.regime_id === 'CA_CCP_704') return 'CCP § 704 (Homestead System)';
  return ev.regime_id;
}

function formatFormChip(formCode) {
  return FORM_LABEL_MAP[formCode] || formCode;
}

function formatQuestionTitle(ruleId) {
  return RULE_TITLE_MAP[ruleId] || ruleId.replaceAll('_', ' ');
}

function formatTensionTitle(tension) {
  const key = tension?.tension_id?.split(':')?.[0] || '';
  if (TENSION_TITLE_MAP[key]) return TENSION_TITLE_MAP[key];
  return tension?.severity === 'blocker' ? 'Critical Schedule Contradiction' : 'Financial Plausibility Advisory';
}

function isCaveat(status) {
  return status === 'unverified' || status === 'disputed' || status === 'assumption' || status === 'extrapolation';
}

function getToneForNode(node) {
  const status = node?.audit?.status || 'verified';
  if (isCaveat(status)) return { cls: 'plate-caveat', stroke: '#B45309', tag: 'Unverified / Gap' };
  if (node?.type === 'calculation') return { cls: 'plate-financial', stroke: '#14532D', tag: 'Deterministic Math' };
  if (node?.type === 'authority') return { cls: 'plate-authority', stroke: '#B84A27', tag: 'Statutory Authority' };
  if (node?.type === 'reasoning') return { cls: '', stroke: '#14284B', tag: 'Counsel Override' };
  return { cls: '', stroke: '#14284B', tag: 'Source Record' };
}

/**
 * Renders section prose + Official Form markdown tables with interactive `<ref id="...">` spans.
 */
function RichRefBlock({ content, nodes, pinnedClaimId, onSelectClaim }) {
  if (!content) return null;
  const lines = content.split('\n');
  const blocks = [];
  let i = 0;

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
      const dimmed = pinnedClaimId && !active;
      parts.push(html`
        <button
          type="button"
          data-ref-id=${refId}
          aria-pressed=${active ? 'true' : 'false'}
          class=${`clause-highlight ${active ? 'is-active' : ''} ${caveat ? 'is-caveat' : ''} ${dimmed ? 'is-dimmed' : ''}`}
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
        const alignSpecs = parseRow(tableLines[1]);
        const isNumericCol = alignSpecs.map((spec) => spec.endsWith(':'));
        const dataRows = tableLines.slice(2).map(parseRow);
        blocks.push(html`
          <div class="bk-table-wrap">
            <table class="sheet-table">
              <thead>
                <tr>
                  ${headers.map((hCell, colIdx) => html`
                    <th class=${isNumericCol[colIdx] ? 'cell-numeric' : ''}>${hCell}</th>
                  `)}
                </tr>
              </thead>
              <tbody>
                ${dataRows.map((row) => html`
                  <tr>
                    ${row.map((cell, colIdx) => html`
                      <td class=${isNumericCol[colIdx] ? 'cell-numeric' : ''}>${renderInline(cell)}</td>
                    `)}
                  </tr>
                `)}
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

/**
 * Right-hand focused stepper for resolving one blocker, emerging question, or advisory at a time.
 */
function NextBlockerStepper({
  triageItems,
  currentIndex,
  onChangeIndex,
  matterId,
  nodes,
  onUpdated,
  onLocateRef,
}) {
  const activeItem = triageItems[currentIndex] || triageItems[0];
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState(null);

  // Inputs start empty with zero fake defaults.
  const [desc, setDesc] = useState('');
  const [val, setVal] = useState('');
  const [unknownVal, setUnknownVal] = useState(false);
  const [claimCat, setClaimCat] = useState('personal_injury');
  const [rolloverAmt, setRolloverAmt] = useState('');
  const [sweepAssetsChecked, setSweepAssetsChecked] = useState(false);
  const [sweepWindfallChecked, setSweepWindfallChecked] = useState(false);
  const [intention, setIntention] = useState('');
  const [credName, setCredName] = useState('');
  const [credAmt, setCredAmt] = useState('');
  const [rationale, setRationale] = useState('');

  useEffect(() => {
    setErr(null);
    setDesc('');
    setVal('');
    setUnknownVal(false);
    setClaimCat('personal_injury');
    setRolloverAmt('');
    setSweepAssetsChecked(false);
    setSweepWindfallChecked(false);
    setIntention('');
    setCredName('');
    setCredAmt('');
    setRationale('');
  }, [activeItem?.itemId]);

  if (!activeItem) return null;

  const isQuestion = activeItem.kind === 'question';
  const q = activeItem.question;
  const t = activeItem.tension;

  const findRelatedClaimId = () => {
    const keyHint = isQuestion ? (q.entity_id || '') : (t?.affected_node_ids?.[0] || '');
    const allClaims = Object.values(nodes).filter((n) => n.type === 'claim');
    if (keyHint) {
      const match = allClaims.find(
        (n) =>
          n.id.toLowerCase().includes(keyHint.toLowerCase()) ||
          n.title.toLowerCase().includes(keyHint.toLowerCase()) ||
          (n.clause_text || '').toLowerCase().includes(keyHint.toLowerCase())
      );
      if (match) return match.id;
    }
    return allClaims.find((n) => isCaveat(n.audit?.status))?.id || allClaims[0]?.id || null;
  };

  const relatedClaimId = findRelatedClaimId();

  const submitQuestion = async (selectedOption, payload = {}, explicitRationale = '') => {
    setSubmitting(true);
    setErr(null);
    try {
      const res = await fetch(
        `/api/v1/bankruptcy/matters/${encodeURIComponent(matterId)}/questions/${encodeURIComponent(q.question_id)}/answer`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            selected_option: selectedOption,
            actor_name: 'Supervising Paralegal',
            actor_role: 'paralegal',
            rationale: explicitRationale || 'Verified and resolved in case audit stepper.',
            payload,
          }),
        }
      );
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `Server returned HTTP ${res.status}`);
      }
      const nextState = await res.json();
      onUpdated(nextState);
    } catch (e) {
      setErr(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const submitTension = async () => {
    if (!rationale.trim()) {
      setErr('Enter a specific verification note before marking this item resolved.');
      return;
    }
    setSubmitting(true);
    setErr(null);
    try {
      const res = await fetch(
        `/api/v1/bankruptcy/matters/${encodeURIComponent(matterId)}/tensions/${encodeURIComponent(t.tension_id)}/resolve`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            actor_name: 'Supervising Paralegal',
            actor_role: 'paralegal',
            rationale: rationale.trim(),
          }),
        }
      );
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `Server returned HTTP ${res.status}`);
      }
      const nextState = await res.json();
      onUpdated(nextState);
    } catch (e) {
      setErr(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const blockerCount = triageItems.filter((x) => x.severity === 'blocker').length;
  const advisoryCount = triageItems.filter((x) => x.severity !== 'blocker').length;
  const validMoney = (s) => /^\d+(\.\d{1,2})?$/.test(s.trim()) && Number(s.trim()) >= 0;

  return html`
    <div class=${`bk-stepper-panel ${activeItem.severity === 'blocker' ? 'is-blocker' : 'is-advisory'}`}>
      <div class="bk-stepper-bar">
        <div class="bk-stepper-counts">
          <span class=${`bk-severity-pill ${activeItem.severity === 'blocker' ? 'is-blocker' : 'is-advisory'}`}>
            ${activeItem.severity === 'blocker' ? 'Filing Blocker' : 'Advisory Check'}
          </span>
          <span class="kicker-label">
            Item <span class="font-mono-data">${currentIndex + 1}</span> of <span class="font-mono-data">${triageItems.length}</span>
            (${blockerCount} Blocker, ${advisoryCount} Advisory)
          </span>
        </div>
        <div class="bk-stepper-nav">
          <button
            type="button"
            class="btn btn-compact"
            disabled=${currentIndex <= 0}
            aria-label="Previous audit item"
            onClick=${() => onChangeIndex(Math.max(0, currentIndex - 1))}
          >
            <${ArrowLeftIcon} /> Prev
          </button>
          <button
            type="button"
            class="btn btn-compact"
            disabled=${currentIndex >= triageItems.length - 1}
            aria-label="Next audit item"
            onClick=${() => onChangeIndex(Math.min(triageItems.length - 1, currentIndex + 1))}
          >
            Next <${ArrowRightIcon} />
          </button>
        </div>
      </div>

      <h2 class="bk-stepper-title">
        ${isQuestion ? formatQuestionTitle(q.rule_id) : formatTensionTitle(t)}
      </h2>

      <p class="bk-triage-prompt">${isQuestion ? q.prompt : t.description}</p>

      ${isQuestion && q.trigger_forms?.length > 0 && html`
        <div class="bk-form-tags" aria-label="Affected Official Bankruptcy Forms">
          ${q.trigger_forms.map((fc) => html`<span class="bk-form-chip">${formatFormChip(fc)}</span>`)}
        </div>
      `}

      ${isQuestion && q.rule_id === 'SECURED_LOAN_MISSING_COLLATERAL_VALUE' && html`
        <div class="bk-stack-form">
          <div class="bk-field-group">
            <label class="bk-label" htmlFor="bk-collat-desc">Collateral Property Description (Schedule A/B)</label>
            <input
              id="bk-collat-desc"
              class="bk-input"
              value=${desc}
              onInput=${(e) => setDesc(e.target.value)}
              placeholder="e.g., 2021 Toyota Camry LE"
            />
          </div>
          <div class="bk-field-group">
            <label class="bk-label" htmlFor="bk-collat-val">Fair Market Value (USD)</label>
            <input
              id="bk-collat-val"
              class="bk-input font-mono-data"
              inputMode="decimal"
              value=${val}
              onInput=${(e) => setVal(e.target.value)}
              placeholder="0.00"
            />
          </div>
          <div class="bk-inline-form">
            <button
              type="button"
              class="btn btn-primary"
              disabled=${submitting || !desc.trim() || !validMoney(val)}
              onClick=${() => submitQuestion('add_or_link_collateral_asset', { description: desc.trim(), category: 'vehicle', current_value: val.trim() }, `Linked collateral ${desc.trim()} valued at $${val.trim()}`)}
            >
              ${submitting ? 'Linking Asset...' : 'Link Collateral to Schedule A/B'}
            </button>
            ${relatedClaimId && html`
              <button type="button" class="btn" onClick=${() => onLocateRef(relatedClaimId)}>
                Locate in Schedule
              </button>
            `}
          </div>
        </div>
      `}

      ${isQuestion && q.rule_id === 'SECURED_CLAIM_MISSING_INTENTION' && html`
        <div class="bk-stack-form">
          <div class="bk-field-group">
            <label class="bk-label" htmlFor="bk-form108-intent">Chapter 7 Debtor Election (Official Form 108)</label>
            <select id="bk-form108-intent" class="bk-select" value=${intention} onChange=${(e) => setIntention(e.target.value)}>
              <option value="">Select intention under 11 U.S.C. § 521(a)(2)...</option>
              <option value="retain_and_reaffirm">Retain Property & Execute Reaffirmation Agreement</option>
              <option value="retain_and_redeem">Retain Property & Redeem Collateral (§ 722)</option>
              <option value="surrender">Surrender Collateral to Creditor</option>
            </select>
          </div>
          <div class="bk-inline-form">
            <button
              type="button"
              class="btn btn-primary"
              disabled=${submitting || !intention}
              onClick=${() => submitQuestion('set_statement_of_intention', { statement_of_intention: intention }, `Set Form 108 intention to ${intention}`)}
            >
              ${submitting ? 'Saving...' : 'Save Form 108 Intention'}
            </button>
            ${relatedClaimId && html`
              <button type="button" class="btn" onClick=${() => onLocateRef(relatedClaimId)}>
                Locate in Schedule
              </button>
            `}
          </div>
        </div>
      `}

      ${isQuestion && q.rule_id === 'UNLISTED_CREDITOR_FROM_BANK_OUTFLOW' && html`
        <div class="bk-stack-form">
          <div class="bk-field-group">
            <label class="bk-label" htmlFor="bk-unlisted-cred">Creditor / Payee Legal Name (Schedule E/F)</label>
            <input
              id="bk-unlisted-cred"
              class="bk-input"
              value=${credName}
              onInput=${(e) => setCredName(e.target.value)}
              placeholder="e.g., Synchrony Bank"
            />
          </div>
          <div class="bk-field-group">
            <label class="bk-label" htmlFor="bk-unlisted-amt">Current Unpaid Claim Balance (USD)</label>
            <input
              id="bk-unlisted-amt"
              class="bk-input font-mono-data"
              inputMode="decimal"
              value=${credAmt}
              onInput=${(e) => setCredAmt(e.target.value)}
              placeholder="0.00"
            />
          </div>
          <div class="bk-inline-form">
            <button
              type="button"
              class="btn btn-primary"
              disabled=${submitting || !credName.trim() || !validMoney(credAmt)}
              onClick=${() => submitQuestion('add_creditor_claim', { creditor_name: credName.trim(), total_claim_amount: credAmt.trim(), priority_type: 'general_unsecured' }, `Added creditor ${credName.trim()} ($${credAmt.trim()})`)}
            >
              ${submitting ? 'Adding...' : 'Add to Schedule E/F'}
            </button>
            <button
              type="button"
              class="btn"
              disabled=${submitting}
              onClick=${() => submitQuestion('confirm_non_debt_payee', {}, 'Confirmed recurring payee is a non-debt household expense.')}
            >
              Mark as Non-Debt Expense
            </button>
          </div>
        </div>
      `}

      ${isQuestion && q.rule_id === 'ASSET_MISSING_LIEN_STATUS' && html`
        <div class="bk-inline-form">
          <button
            type="button"
            class="btn btn-primary"
            disabled=${submitting}
            onClick=${() => submitQuestion('confirm_free_and_clear', {}, 'Confirmed property is owned free and clear of liens.')}
          >
            ${submitting ? 'Confirming...' : 'Confirm Owned Free & Clear'}
          </button>
          ${relatedClaimId && html`
            <button type="button" class="btn" onClick=${() => onLocateRef(relatedClaimId)}>
              Locate in Schedule
            </button>
          `}
        </div>
      `}

      ${isQuestion && (q.rule_id === 'POTENTIAL_PERSONAL_INJURY_OR_WORKERS_COMP_CLAIM' || q.rule_id === 'SOFA_LAWSUIT_PLAINTIFF_MISSING_ON_AB') && html`
        <div class="bk-stack-form">
          <div class="bk-field-group">
            <label class="bk-label" htmlFor="bk-pi-cat">Schedule A/B Claim Category (Line 33/34)</label>
            <select id="bk-pi-cat" class="bk-select" value=${claimCat} onChange=${(e) => setClaimCat(e.target.value)}>
              <option value="personal_injury">Line 33: Personal Injury Cause of Action (CCP § 704.140)</option>
              <option value="workers_comp">Line 33: Workers Compensation Claim (CCP § 704.160)</option>
              <option value="legal_claims">Line 34: Other Third-Party / Counterclaim</option>
            </select>
          </div>
          <div class="bk-field-group">
            <label class="bk-label" htmlFor="bk-pi-desc">Claim or Lawsuit Description</label>
            <input
              id="bk-pi-desc"
              class="bk-input"
              value=${desc}
              onInput=${(e) => setDesc(e.target.value)}
              placeholder="e.g., Auto collision claim v. Third Party Driver"
            />
          </div>
          <label class="bk-checkbox-row" htmlFor="bk-pi-unknown">
            <input
              id="bk-pi-unknown"
              type="checkbox"
              checked=${unknownVal}
              onChange=${(e) => setUnknownVal(e.target.checked)}
            />
            <span>Value is Unknown (Unliquidated) — check "100% of Fair Market Value" on Form 106C (Schwab v. Reilly)</span>
          </label>
          ${!unknownVal && html`
            <div class="bk-field-group">
              <label class="bk-label" htmlFor="bk-pi-val">Estimated Settlement Value (USD)</label>
              <input
                id="bk-pi-val"
                class="bk-input font-mono-data"
                inputMode="decimal"
                value=${val}
                onInput=${(e) => setVal(e.target.value)}
                placeholder="0.00"
              />
            </div>
          `}
          <div class="bk-inline-form">
            <button
              type="button"
              class="btn btn-primary"
              disabled=${submitting || !desc.trim() || (!unknownVal && !validMoney(val))}
              onClick=${() => submitQuestion(
                q.rule_id === 'SOFA_LAWSUIT_PLAINTIFF_MISSING_ON_AB' ? 'sync_lawsuit_to_schedule_ab' : 'add_unliquidated_claim_asset',
                {
                  category: claimCat,
                  description: desc.trim(),
                  valuation_state: unknownVal ? 'unknown' : 'estimated',
                  current_value: unknownVal ? '0.00' : val.trim(),
                },
                `Scheduled ${claimCat} claim '${desc.trim()}' (${unknownVal ? 'Unknown FMV / 100% FMV' : `$${val.trim()}`})`
              )}
            >
              ${submitting ? 'Scheduling...' : 'Add Claim to Schedule A/B & C'}
            </button>
            ${q.rule_id === 'POTENTIAL_PERSONAL_INJURY_OR_WORKERS_COMP_CLAIM' && html`
              <button
                type="button"
                class="btn"
                disabled=${submitting}
                onClick=${() => submitQuestion('confirm_no_injury_claim', {}, 'Client confirmed medical treatment did not arise from any personal injury or workers comp claim.')}
              >
                Confirm No Injury / WC Claim
              </button>
            `}
          </div>
        </div>
      `}

      ${isQuestion && q.rule_id === 'SOFA_LAWSUIT_DEFENDANT_MISSING_ON_EF' && html`
        <div class="bk-stack-form">
          <div class="bk-field-group">
            <label class="bk-label" htmlFor="bk-sofa-def-cred">Opposing Plaintiff Legal Name (Schedule E/F)</label>
            <input
              id="bk-sofa-def-cred"
              class="bk-input"
              value=${credName}
              onInput=${(e) => setCredName(e.target.value)}
              placeholder="e.g., Plaintiff / Opposing Claimant"
            />
          </div>
          <div class="bk-field-group">
            <label class="bk-label" htmlFor="bk-sofa-def-amt">Claimed or Disputed Demand Amount (USD)</label>
            <input
              id="bk-sofa-def-amt"
              class="bk-input font-mono-data"
              inputMode="decimal"
              value=${credAmt}
              onInput=${(e) => setCredAmt(e.target.value)}
              placeholder="0.00"
            />
          </div>
          <div class="bk-inline-form">
            <button
              type="button"
              class="btn btn-primary"
              disabled=${submitting || !credName.trim() || !validMoney(credAmt)}
              onClick=${() => submitQuestion('sync_lawsuit_to_schedule_ef', { creditor_name: credName.trim(), total_claim_amount: credAmt.trim(), contingent: true, unliquidated: true }, `Synced SOFA defendant suit '${credName.trim()}' to Schedule E/F for stay notice.`)}
            >
              ${submitting ? 'Syncing...' : 'Sync Contingent Claim to Schedule E/F'}
            </button>
          </div>
        </div>
      `}

      ${isQuestion && q.rule_id === 'RENTER_MISSING_SECURITY_DEPOSIT_LINE_28' && html`
        <div class="bk-stack-form">
          <div class="bk-field-group">
            <label class="bk-label" htmlFor="bk-secdep-val">Landlord / Utility Security Deposit Held (USD)</label>
            <input
              id="bk-secdep-val"
              class="bk-input font-mono-data"
              inputMode="decimal"
              value=${val}
              onInput=${(e) => setVal(e.target.value)}
              placeholder="0.00"
            />
          </div>
          <div class="bk-inline-form">
            <button
              type="button"
              class="btn btn-primary"
              disabled=${submitting || !validMoney(val)}
              onClick=${() => submitQuestion('add_security_deposit_asset', { description: 'Residential Security Deposit', current_value: val.trim() }, `Scheduled security deposit of $${val.trim()} on Line 22/28.`)}
            >
              ${submitting ? 'Adding...' : 'Add Deposit to Schedule A/B'}
            </button>
            <button
              type="button"
              class="btn"
              disabled=${submitting}
              onClick=${() => submitQuestion('confirm_no_security_deposit', {}, 'Client confirmed zero refundable security deposits held.')}
            >
              Confirm No Deposit
            </button>
          </div>
        </div>
      `}

      ${isQuestion && q.rule_id === 'HOMESTEAD_522P_ROLLOVER_INQUIRY' && html`
        <div class="bk-stack-form">
          <div class="bk-field-group">
            <label class="bk-label" htmlFor="bk-522p-rollover">Same-State Prior Residence Rollover Amount Under § 522(p)(2)(B) (USD)</label>
            <input
              id="bk-522p-rollover"
              class="bk-input font-mono-data"
              inputMode="decimal"
              value=${rolloverAmt}
              onInput=${(e) => setRolloverAmt(e.target.value)}
              placeholder="0.00"
            />
          </div>
          <div class="bk-inline-form">
            <button
              type="button"
              class="btn btn-primary"
              disabled=${submitting || !validMoney(rolloverAmt)}
              onClick=${() => submitQuestion('apply_522p_rollover', { rollover_amount: rolloverAmt.trim() }, `Applied $${rolloverAmt.trim()} same-state rollover exception under 11 U.S.C. § 522(p)(2)(B).`)}
            >
              ${submitting ? 'Applying...' : 'Apply § 522(p)(2)(B) Rollover'}
            </button>
            <button
              type="button"
              class="btn"
              disabled=${submitting}
              onClick=${() => submitQuestion('confirm_no_rollover', {}, 'Confirmed no prior same-state residence rollover; $214,000 § 522(p) cap applies.')}
            >
              Confirm No Rollover ($214k Cap)
            </button>
          </div>
        </div>
      `}

      ${isQuestion && q.rule_id === 'MARRIED_SEPARATE_703_SPOUSAL_WAIVER' && html`
        <div class="bk-inline-form">
          <button
            type="button"
            class="btn btn-primary"
            disabled=${submitting}
            onClick=${() => submitQuestion('confirm_spousal_waiver_signed', {}, 'Written CCP § 703.140(a)(2) spousal waiver executed and retained.')}
          >
            Confirm Written Waiver Signed
          </button>
          <button
            type="button"
            class="btn"
            disabled=${submitting}
            onClick=${() => submitQuestion('switch_to_704_regime', {}, 'Switched exemption election to CCP § 704 Homestead System.')}
          >
            Switch to CCP § 704 System
          </button>
        </div>
      `}

      ${isQuestion && q.rule_id === 'UNKNOWN_VALUATION_CAPPED_EXEMPTION_RISK' && html`
        <div class="bk-inline-form">
          <button
            type="button"
            class="btn btn-primary"
            disabled=${submitting}
            onClick=${() => submitQuestion('switch_to_704_regime', {}, 'Switched to CCP § 704 for unlimited personal injury / workers comp protection.')}
          >
            Switch to CCP § 704 (Unlimited PI)
          </button>
          <button
            type="button"
            class="btn"
            disabled=${submitting}
            onClick=${() => submitQuestion('confirm_unknown_within_cap', {}, 'Attorney reviewed capped exemption windfall risk and elected to proceed.')}
          >
            Confirm Recovery Within Cap
          </button>
        </div>
      `}

      ${isQuestion && q.rule_id === 'MANDATORY_ASSET_AND_WINDFALL_SWEEP' && html`
        <div class="bk-stack-form">
          <label class="bk-checkbox-row" htmlFor="bk-sweep-assets">
            <input
              id="bk-sweep-assets"
              type="checkbox"
              checked=${sweepAssetsChecked}
              onChange=${(e) => setSweepAssetsChecked(e.target.checked)}
            />
            <span>Negative Confirmation: Client holds no unlisted cash on hand, tax refunds, inheritances, or third-party legal claims (Lines 16–35).</span>
          </label>
          <label class="bk-checkbox-row" htmlFor="bk-sweep-windfall">
            <input
              id="bk-sweep-windfall"
              type="checkbox"
              checked=${sweepWindfallChecked}
              onChange=${(e) => setSweepWindfallChecked(e.target.checked)}
            />
            <span>180-Day Windfall Advisement: Advised debtor of 11 U.S.C. § 541(a)(5) estate inclusion for inheritances, divorce decrees, or life insurance proceeds within 180 days post-filing.</span>
          </label>
          <div class="bk-inline-form">
            <button
              type="button"
              class="btn btn-primary"
              disabled=${submitting || !sweepAssetsChecked || !sweepWindfallChecked}
              onClick=${() => submitQuestion('confirm_mandatory_asset_and_windfall_sweep', {}, 'Completed Tier-2 negative asset sweep and 180-day windfall advisement.')}
            >
              ${submitting ? 'Recording...' : 'Confirm Asset Sweep & Windfall Advisement'}
            </button>
          </div>
        </div>
      `}

      ${isQuestion && !['SECURED_LOAN_MISSING_COLLATERAL_VALUE', 'SECURED_CLAIM_MISSING_INTENTION', 'UNLISTED_CREDITOR_FROM_BANK_OUTFLOW', 'ASSET_MISSING_LIEN_STATUS', 'POTENTIAL_PERSONAL_INJURY_OR_WORKERS_COMP_CLAIM', 'SOFA_LAWSUIT_PLAINTIFF_MISSING_ON_AB', 'SOFA_LAWSUIT_DEFENDANT_MISSING_ON_EF', 'RENTER_MISSING_SECURITY_DEPOSIT_LINE_28', 'HOMESTEAD_522P_ROLLOVER_INQUIRY', 'MARRIED_SEPARATE_703_SPOUSAL_WAIVER', 'UNKNOWN_VALUATION_CAPPED_EXEMPTION_RISK', 'MANDATORY_ASSET_AND_WINDFALL_SWEEP'].includes(q.rule_id) && html`
        <div class="bk-stack-form">
          <div class="bk-field-group">
            <label class="bk-label" htmlFor="bk-generic-rationale">Verification Note</label>
            <input
              id="bk-generic-rationale"
              class="bk-input"
              value=${rationale}
              onInput=${(e) => setRationale(e.target.value)}
              placeholder="Enter source confirmation or closing detail..."
            />
          </div>
          <div class="bk-inline-form">
            <button
              type="button"
              class="btn btn-primary"
              disabled=${submitting || !rationale.trim()}
              onClick=${() => submitQuestion(q.resolution_options?.[0] || 'confirm_closed_account', {}, rationale.trim())}
            >
              ${submitting ? 'Saving...' : 'Resolve Audit Gap'}
            </button>
          </div>
        </div>
      `}

      ${!isQuestion && html`
        <div class="bk-stack-form">
          <div class="bk-field-group">
            <label class="bk-label" htmlFor="bk-tension-rationale">Paralegal / Attorney Audit Explanation</label>
            <input
              id="bk-tension-rationale"
              class="bk-input"
              value=${rationale}
              onInput=${(e) => setRationale(e.target.value)}
              placeholder="Explain verified source document reconciling this variance..."
            />
          </div>
          <div class="bk-inline-form">
            <button
              type="button"
              class="btn btn-primary"
              disabled=${submitting || !rationale.trim()}
              onClick=${submitTension}
            >
              ${submitting ? 'Recording...' : 'Record Explanation & Resolve'}
            </button>
            ${relatedClaimId && html`
              <button type="button" class="btn" onClick=${() => onLocateRef(relatedClaimId)}>
                Locate in Schedule
              </button>
            `}
          </div>
        </div>
      `}

      ${err && html`<div class="bk-error-text" role="alert">${err}</div>`}
    </div>
  `;
}

function SourceInspectorDrawer({ node, matterId, onClose }) {
  useEffect(() => {
    if (!node) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [node, onClose]);

  if (!node) return null;
  const loc = node.locator;
  const rawUrl =
    loc?.file_name && matterId
      ? `/api/v1/bankruptcy/matters/${encodeURIComponent(matterId)}/files/${encodeURIComponent(loc.file_name)}/raw${loc.page ? `#page=${loc.page}` : ''}`
      : null;

  return html`
    <div class="inspector-backdrop" onClick=${onClose}>
      <aside
        class="source-inspector-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="bk-src-inspector-title"
        onClick=${(e) => e.stopPropagation()}
      >
        <div class="drawer-header">
          <div>
            <h3 id="bk-src-inspector-title" class="card-heading">${node.title}</h3>
            <div class="kicker-label">Source Verification Inspector</div>
          </div>
          <button type="button" class="btn btn-compact" onClick=${onClose}>
            <${CloseIcon} /> Close
          </button>
        </div>
        <div class="drawer-body">
          ${loc && html`
            <div class="pdf-page-simulator">
              <div class="kicker-label">
                Document: <span class="font-mono-data">${loc.file_name}</span>
                ${loc.page ? html` · Page <span class="font-mono-data">${loc.page}</span>` : ''}
                ${loc.bounding_box ? html` · Coordinates <span class="font-mono-data">[${loc.bounding_box.join(', ')}]</span>` : ''}
              </div>
              <div class="pdf-bbox-highlight">
                “${node.quote || node.body}”
              </div>
              <div class="kicker-label">
                Locator <span class="font-mono-data">${loc.locator_key || 'N/A'}</span> · Digest <span class="font-mono-data">${loc.payload_hash || 'N/A'}</span>
              </div>
            </div>
          `}
          ${!loc && html`
            <div class="pdf-page-simulator">
              <div class="kicker-label">${node.type === 'authority' ? 'Controlling Statutory Authority' : 'Deterministic Calculation'}</div>
              <p class="card-body-prose">${node.quote || node.body || node.formula}</p>
            </div>
          `}
          ${rawUrl && html`
            <a class="btn btn-primary" href=${rawUrl} target="_blank" rel="noopener noreferrer">
              Open Original Client PDF ${loc?.page ? `(Page ${loc.page})` : ''} <${ExternalIcon} />
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
  const [uploadingDecl, setUploadingDecl] = useState(false);
  const [attyName, setAttyName] = useState(graph.attorney_name || '');
  const [barNum, setBarNum] = useState(graph.attorney_bar_number || '');
  const [subMode, setSubMode] = useState('ecf_train');
  const [attested, setAttested] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [latestReceipt, setLatestReceipt] = useState(
    (caseState.filing_receipts || []).slice(-1)[0] || null
  );

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

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
        throw new Error(data.detail?.message || data.detail || `Server returned HTTP ${res.status}`);
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
    setUploadingDecl(true);
    setErrorMsg(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch(
        `/api/v1/bankruptcy/matters/${encodeURIComponent(graph.matter_id)}/declaration`,
        { method: 'POST', body: fd }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `Declaration upload failed (HTTP ${res.status})`);
      }
      onStateUpdated(data);
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setUploadingDecl(false);
    }
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
            attorney_name: attyName.trim(),
            attorney_bar_number: barNum.trim(),
            attested,
          }),
        }
      );
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || `Court submission failed (HTTP ${res.status})`);
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

  const readyToCompile = readiness?.status === 'READY';
  const readyToSubmit =
    readyToCompile &&
    Boolean(graph.signed_declaration_uploaded) &&
    packetFiles.length > 0 &&
    Boolean(attyName.trim()) &&
    Boolean(barNum.trim()) &&
    attested;

  return html`
    <div class="inspector-backdrop" onClick=${onClose}>
      <aside
        class="source-inspector-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="bk-packet-drawer-title"
        onClick=${(e) => e.stopPropagation()}
      >
        <div class="drawer-header">
          <div>
            <h3 id="bk-packet-drawer-title" class="card-heading">Official Packet & Rule 9011 Submission</h3>
            <div class="kicker-label">Zero-Doubt Gate · ${graph.district} Chapter ${graph.chapter}</div>
          </div>
          <button type="button" class="btn btn-compact" onClick=${onClose}>
            <${CloseIcon} /> Close
          </button>
        </div>
        <div class="drawer-body">
          <div class=${`bk-gate-banner ${readyToCompile ? 'is-ready' : 'is-blocked'}`}>
            <strong>Filing Gate: ${readiness?.status || 'BLOCKED'}</strong>
            ${(readiness?.blocking_reasons || []).map((r) => html`<div>${r}</div>`)}
            ${readyToCompile && html`<div>All extracted schedule values verified with zero open blockers.</div>`}
          </div>

          <section class="bk-section-box" aria-labelledby="bk-step-1-heading">
            <h4 id="bk-step-1-heading" class="bk-section-step-title">Step 1: Compile & Bake Official PDF Packet</h4>
            <div class="bk-inline-form">
              <button
                type="button"
                class=${`btn ${readyToCompile ? 'btn-primary' : ''}`}
                disabled=${compiling || !readyToCompile}
                onClick=${() => compilePacket(false)}
              >
                ${compiling ? 'Baking Official PDFs...' : 'Compile Official Filing Packet'}
              </button>
              <button
                type="button"
                class="btn"
                disabled=${compiling}
                onClick=${() => compilePacket(true)}
              >
                Preview Watermarked Draft
              </button>
            </div>
            ${packetFiles.length > 0 && html`
              <div>
                <div class="kicker-label">Generated Court Artifacts (${packetFiles.length})</div>
                <ul class="bk-file-list">
                  ${packetFiles.map((fn) => html`
                    <li>
                      <a
                        class="font-mono-data"
                        href=${`/api/v1/bankruptcy/matters/${encodeURIComponent(graph.matter_id)}/packet/files/${encodeURIComponent(fn)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        ${fn} <${ExternalIcon} />
                      </a>
                    </li>
                  `)}
                </ul>
              </div>
            `}
          </section>

          <section class="bk-section-box" aria-labelledby="bk-step-2-heading">
            <h4 id="bk-step-2-heading" class="bk-section-step-title">
              Step 2: Wet-Signed Declaration (${graph.district === 'CACB' ? 'CACB Form F 9011-1 / F 5005-4' : 'CAEB Electronic Signature Declaration'})
            </h4>
            <div class="bk-field-group">
              <label class="bk-label" htmlFor="bk-decl-upload">Upload Scanned Debtor Signature PDF</label>
              <input id="bk-decl-upload" type="file" accept=".pdf" disabled=${uploadingDecl} onChange=${uploadDecl} />
              <div class="kicker-label">
                ${uploadingDecl
                  ? 'Uploading declaration...'
                  : graph.signed_declaration_uploaded
                    ? html`Uploaded · Digest <span class="font-mono-data">${graph.signed_declaration_sha256?.slice(0, 18)}</span>`
                    : 'Required before court submission'}
              </div>
            </div>
          </section>

          <section class="bk-section-box" aria-labelledby="bk-step-3-heading">
            <h4 id="bk-step-3-heading" class="bk-section-step-title">Step 3: Rule 9011 Attorney Attestation & Submit</h4>
            <div class="bk-stack-form">
              <div class="bk-field-group">
                <label class="bk-label" htmlFor="bk-atty-name">Supervising Attorney Full Name</label>
                <input
                  id="bk-atty-name"
                  class="bk-input"
                  value=${attyName}
                  onInput=${(e) => setAttyName(e.target.value)}
                  placeholder="Enter supervising attorney name"
                />
              </div>
              <div class="bk-field-group">
                <label class="bk-label" htmlFor="bk-atty-bar">California State Bar Number</label>
                <input
                  id="bk-atty-bar"
                  class="bk-input font-mono-data"
                  value=${barNum}
                  onInput=${(e) => setBarNum(e.target.value)}
                  placeholder="e.g., CA-310044"
                />
              </div>
              <div class="bk-field-group">
                <label class="bk-label" htmlFor="bk-sub-mode">Court Transmission Mode</label>
                <select id="bk-sub-mode" class="bk-select" value=${subMode} onChange=${(e) => setSubMode(e.target.value)}>
                  <option value="ecf_train">${SUBMISSION_MODE_LABELS.ecf_train}</option>
                  <option value="filing_agent">${SUBMISSION_MODE_LABELS.filing_agent}</option>
                  <option value="firm_attorney">${SUBMISSION_MODE_LABELS.firm_attorney}</option>
                </select>
              </div>
              <label class="bk-checkbox-row" htmlFor="bk-rule-9011-chk">
                <input
                  id="bk-rule-9011-chk"
                  type="checkbox"
                  checked=${attested}
                  onChange=${(e) => setAttested(e.target.checked)}
                />
                <span>I certify under Fed. R. Bankr. P. 9011 that all schedules, means test figures, and source locators are accurate.</span>
              </label>
              <button
                type="button"
                class="btn btn-primary"
                disabled=${submitting || !readyToSubmit}
                onClick=${submitToCourt}
              >
                ${submitting ? 'Transmitting to Court...' : `Submit Packet to ${graph.district}`}
              </button>
            </div>
          </section>

          ${errorMsg && html`<div class="bk-error-banner" role="alert"><span>${errorMsg}</span></div>`}

          ${latestReceipt && html`
            <div class="bk-receipt-card">
              <div class="kicker-label">Court Filing Receipt · ${latestReceipt.district}</div>
              <div>Case Number: <strong class="font-mono-data">${latestReceipt.assigned_case_number}</strong></div>
              <div>
                Mode: ${SUBMISSION_MODE_LABELS[latestReceipt.submission_mode] || latestReceipt.submission_mode} ·
                Receipt: <span class="font-mono-data">${latestReceipt.receipt_sha256}</span>
              </div>
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
  const [loadingMatters, setLoadingMatters] = useState(true);
  const [activeMatterId, setActiveMatterId] = useState(null);
  const [caseState, setCaseState] = useState(null);
  const [appError, setAppError] = useState(null);
  const [pinnedClaimId, setPinnedClaimId] = useState(null);
  const [expandedL2Ids, setExpandedL2Ids] = useState([]);
  const [stepperIndex, setStepperIndex] = useState(0);
  const [inspectorNode, setInspectorNode] = useState(null);
  const [showPacketDrawer, setShowPacketDrawer] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [newCaseId, setNewCaseId] = useState('');
  const [newChapter, setNewChapter] = useState('7');
  const [newDistrict, setNewDistrict] = useState('CACB');
  const [uploadFiles, setUploadFiles] = useState([]);
  const [busyMsg, setBusyMsg] = useState(null);
  const [tableSyncStatus, setTableSyncStatus] = useState(null);
  const [modalError, setModalError] = useState(null);
  const [paths, setPaths] = useState([]);

  const viewportRef = useRef(null);
  const l1Ref = useRef(null);
  const l2Ref = useRef(null);

  const loadMatters = useCallback(async (selectId = null) => {
    setLoadingMatters(true);
    setAppError(null);
    try {
      const res = await fetch('/api/v1/bankruptcy/matters');
      if (!res.ok) throw new Error(`Failed to load case matters (HTTP ${res.status})`);
      const data = await res.json();
      const list = data.matters || [];
      setMatters(list);
      const chosen = selectId || activeMatterId || list[0]?.matter_id || null;
      if (chosen) {
        setActiveMatterId(chosen);
        const cRes = await fetch(`/api/v1/bankruptcy/matters/${encodeURIComponent(chosen)}/case`);
        if (!cRes.ok) throw new Error(`Failed to open case '${chosen}' (HTTP ${cRes.status})`);
        setCaseState(await cRes.json());
      } else {
        setCaseState(null);
      }
    } catch (e) {
      setAppError(e.message);
    } finally {
      setLoadingMatters(false);
    }
  }, [activeMatterId]);

  useEffect(() => {
    loadMatters();
  }, []);

  useEffect(() => {
    if (!showUploadModal) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape' && !busyMsg) setShowUploadModal(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [showUploadModal, busyMsg]);

  const selectMatter = async (mId) => {
    setActiveMatterId(mId);
    setPinnedClaimId(null);
    setExpandedL2Ids([]);
    setStepperIndex(0);
    setAppError(null);
    try {
      const res = await fetch(`/api/v1/bankruptcy/matters/${encodeURIComponent(mId)}/case`);
      if (!res.ok) throw new Error(`Failed to load matter '${mId}' (HTTP ${res.status})`);
      setCaseState(await res.json());
    } catch (e) {
      setAppError(e.message);
    }
  };

  const bundle = caseState?.compiled_bundle || null;
  const nodes = bundle?.nodes || {};
  const l1Ids = useMemo(() => {
    if (!pinnedClaimId || !nodes[pinnedClaimId]) return [];
    return nodes[pinnedClaimId].direct_child_ids || [];
  }, [pinnedClaimId, nodes]);

  const openQuestions = (caseState?.emerging_questions || []).filter((q) => q.status === 'open');
  const openTensions = [
    ...(caseState?.tensions || []),
    ...(caseState?.plausibility_warnings || []),
  ].filter((t) => !(caseState?.resolved_tension_records || {})[t.tension_id]);

  // Unified Next-Blocker queue ordered: Critical Blockers -> Open Critical Questions -> Warning Advisories
  const triageItems = useMemo(() => {
    const items = [];
    for (const t of openTensions.filter((x) => x.severity === 'blocker')) {
      items.push({ kind: 'tension', severity: 'blocker', itemId: `t:${t.tension_id}`, tension: t });
    }
    for (const q of openQuestions.filter((x) => x.severity !== 'warning')) {
      items.push({ kind: 'question', severity: 'blocker', itemId: `q:${q.question_id}`, question: q });
    }
    for (const q of openQuestions.filter((x) => x.severity === 'warning')) {
      items.push({ kind: 'question', severity: 'advisory', itemId: `q:${q.question_id}`, question: q });
    }
    for (const t of openTensions.filter((x) => x.severity !== 'blocker')) {
      items.push({ kind: 'tension', severity: 'advisory', itemId: `t:${t.tension_id}`, tension: t });
    }
    return items;
  }, [openQuestions, openTensions]);

  const handleSyncTables = async () => {
    setTableSyncStatus('Syncing...');
    try {
      const res = await fetch('/api/v1/bankruptcy/tables/sync', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Sync failed (${res.status})`);
      const staleCount = (data.stale_warnings || []).length;
      setTableSyncStatus(
        staleCount > 0
          ? `${data.tables_verified?.length || 0} tables (${staleCount} stale)`
          : `${data.tables_verified?.length || 0} tables verified`
      );
      if (activeMatterId) await loadMatters(activeMatterId);
    } catch (e) {
      setTableSyncStatus(`Sync error: ${e.message}`);
    }
  };

  useEffect(() => {
    if (stepperIndex >= triageItems.length && triageItems.length > 0) {
      setStepperIndex(0);
    }
  }, [triageItems.length, stepperIndex]);

  const showRightRail = l1Ids.length > 0 || Boolean(caseState);
  const colsClass = expandedL2Ids.length > 0 ? 'cols-3' : showRightRail ? 'cols-2' : 'cols-1';

  const selectL0Claim = useCallback((refId, shouldScrollL0 = false) => {
    setPinnedClaimId((prev) => {
      if (prev === refId && !shouldScrollL0) {
        setExpandedL2Ids([]);
        return null;
      }
      setExpandedL2Ids([]);
      return refId;
    });
    requestAnimationFrame(() => {
      if (shouldScrollL0 && viewportRef.current) {
        const refEl = viewportRef.current.querySelector(`[data-ref-id="${refId}"]`);
        refEl?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      if (window.innerWidth <= 1180) {
        l1Ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    });
  }, []);

  const recomputeBezierPaths = useCallback(() => {
    const vp = viewportRef.current;
    if (!vp || !pinnedClaimId || window.innerWidth <= 1180) {
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
    setBusyMsg('Creating matter, ingesting PDFs, and checking statutory gates...');
    setModalError(null);
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
      if (!initRes.ok) {
        const d = await initRes.json().catch(() => ({}));
        throw new Error(d.detail || `Failed to initialize case (HTTP ${initRes.status})`);
      }
      const created = await initRes.json();
      const targetId = created.case_graph.matter_id;

      if (uploadFiles.length > 0) {
        const fd = new FormData();
        for (const f of uploadFiles) fd.append('files', f);
        const upRes = await fetch(`/api/v1/bankruptcy/matters/${encodeURIComponent(targetId)}/upload`, {
          method: 'POST',
          body: fd,
        });
        if (!upRes.ok) throw new Error(`File upload failed (HTTP ${upRes.status})`);
      }
      const exRes = await fetch(`/api/v1/bankruptcy/matters/${encodeURIComponent(targetId)}/extract`, {
        method: 'POST',
      });
      if (!exRes.ok) throw new Error(`Extraction pipeline failed (HTTP ${exRes.status})`);
      setShowUploadModal(false);
      setNewCaseId('');
      setUploadFiles([]);
      await loadMatters(targetId);
    } catch (err) {
      setModalError(err.message);
    } finally {
      setBusyMsg(null);
    }
  };

  const graph = caseState?.case_graph;
  const calcs = caseState?.calculations;
  const readiness = caseState?.readiness;
  const isReady = readiness?.status === 'READY';
  const plannedForms = bundle?.artifact?.metadata?.planned_pdf_forms || [];

  return html`
    <div class="app-shell">
      <header class="top-bar">
        <div class="top-bar-left">
          <span class="brand-title">Bankruptcy Case Workbench</span>
          ${matters.length > 0 && html`
            <select
              class="bk-select bk-select-topbar"
              aria-label="Select bankruptcy matter"
              value=${activeMatterId || ''}
              onChange=${(e) => selectMatter(e.target.value)}
            >
              ${matters.map((m) => html`
                <option value=${m.matter_id}>
                  ${m.matter_id} · Ch. ${m.chapter} (${m.district}) · ${m.readiness_status}
                </option>
              `)}
            </select>
          `}
        </div>
        <div class="top-bar-right">
          ${tableSyncStatus && html`<span class="kicker-label font-mono-data">${tableSyncStatus}</span>`}
          <button type="button" class="btn btn-compact" onClick=${handleSyncTables}>
            Sync Statutory Tables
          </button>
          <button type="button" class="btn" onClick=${() => { setModalError(null); setShowUploadModal(true); }}>
            New Case & Upload PDFs
          </button>
          ${caseState && html`
            <button
              type="button"
              class=${`btn ${isReady ? 'btn-primary' : ''}`}
              onClick=${() => setShowPacketDrawer(true)}
            >
              Filing Gate: ${readiness?.status || 'BLOCKED'} <${ArrowRightIcon} />
            </button>
          `}
        </div>
      </header>

      <main id="bk-workspace-main" class="spatial-viewport" ref=${viewportRef}>
        <svg class="connector-svg-layer" aria-hidden="true">
          ${paths.map((p) => html`
            <g>
              <path d=${p.d} fill="none" stroke=${p.stroke} stroke-width="1.5" />
              <rect x=${p.x1 - 2.5} y=${p.y1 - 2.5} width="5" height="5" fill=${p.stroke} />
              <rect x=${p.x2 - 2.5} y=${p.y2 - 2.5} width="5" height="5" fill=${p.stroke} />
            </g>
          `)}
        </svg>

        ${appError && html`
          <div class="bk-error-banner" role="alert">
            <span>${appError}</span>
            <button type="button" class="btn btn-compact" onClick=${() => loadMatters()}>Retry</button>
          </div>
        `}

        ${loadingMatters && !caseState && !appError && html`
          <div class="bk-empty-state">
            <h2 class="section-heading">Loading Bankruptcy Case Workbench</h2>
            <p class="bk-triage-prompt">Retrieving case files and verifying statutory exemption and means-test tables...</p>
          </div>
        `}

        ${!loadingMatters && !caseState && !appError && html`
          <div class="bk-empty-state">
            <h2 class="section-heading">No Bankruptcy Matters Yet</h2>
            <p class="bk-triage-prompt">
              Create your first Chapter 7 or Chapter 13 matter and upload uncategorized client financial PDFs (intake sheets, paystubs, bank statements, tax returns, or loan statements).
            </p>
            <div>
              <button type="button" class="btn btn-primary" onClick=${() => setShowUploadModal(true)}>
                Create First Case
              </button>
            </div>
          </div>
        `}

        ${caseState && html`
          <div class=${`bounded-canvas-grid ${colsClass}`}>
            <!-- Column 1 (L0): Official-Form-Mirrored Broadsheet -->
            <section class="column-lane lane-analytical" aria-label="Official Forms Schedules Broadsheet">
              <div class="lane-header">
                <div class="lane-title-group">
                  <span class="lane-title">Official Schedules & Forms</span>
                </div>
                <span class="lane-count font-mono-data">
                  ${bundle?.audit_summary?.verified_count || 0}/${bundle?.audit_summary?.total_claims || 0} Verified
                </span>
              </div>

              <div class="artifact-sheet">
                <header class="artifact-header">
                  <h1 class="artifact-title">${bundle?.artifact?.title || `Chapter ${graph.chapter} Official Forms`}</h1>
                  <div class="artifact-meta-ledger">
                    <span class="meta-pair">Chapter <strong>${graph.chapter}</strong></span>
                    <span class="meta-pair">District <strong>${graph.district}</strong></span>
                    <span class="meta-pair">
                      Target Filing Date <span class="font-mono-data">${graph.expected_filing_date}</span>
                    </span>
                    ${plannedForms.length > 0 && html`
                      <span class="meta-pair">Required Court Forms <strong class="font-mono-data">${plannedForms.length}</strong></span>
                    `}
                  </div>
                  ${bundle?.artifact?.summary && html`
                    <p class="artifact-summary">${bundle.artifact.summary}</p>
                  `}
                  ${calcs?.exemptions && html`
                    <div class="bk-opt-grid" aria-label="California Exemption Regime Comparison">
                      ${calcs.exemptions.evaluations.map((ev) => {
                        const isRec = ev.regime_id === calcs.exemptions.recommended_regime_id;
                        return html`
                          <div class=${`bk-opt-card ${isRec ? 'is-recommended' : ''}`}>
                            <div class="bk-opt-head">
                              <span>${formatRegimeLabel(ev)}</span>
                              ${isRec && html`<span class="bk-severity-pill is-ready">Recommended</span>`}
                              ${!isRec && ev.has_unbounded_unknown_exposure && html`<span class="bk-severity-pill is-advisory">Unknown Cap Risk</span>`}
                            </div>
                            <div class="bk-opt-stat">
                              <span>Exempt Protected Equity</span>
                              <strong class="font-mono-data">${formatCurrency(ev.total_exempt_equity)}</strong>
                            </div>
                            <div class="bk-opt-stat">
                              <span>Non-Exempt Exposed</span>
                              <strong class="font-mono-data">${formatCurrency(ev.total_non_exempt_equity)}</strong>
                            </div>
                          </div>
                        `;
                      })}
                    </div>
                  `}
                </header>

                ${(bundle?.artifact?.sections || []).map((sec) => html`
                  <article class="artifact-section">
                    <h2 class="section-heading">${sec.section_title}</h2>
                    <${RichRefBlock}
                      content=${sec.content}
                      nodes=${nodes}
                      pinnedClaimId=${pinnedClaimId}
                      onSelectClaim=${(id) => selectL0Claim(id, false)}
                    />
                  </article>
                `)}
              </div>
            </section>

            <!-- Column 2: Either Next Blocker Stepper (default) OR L1 Evidence/Math when a Schedule Ref is pinned -->
            ${l1Ids.length === 0 && html`
              <section class="column-lane" aria-label="Next Audit Blocker Stepper">
                <div class="lane-header">
                  <span class="lane-title">Audit Resolution Queue</span>
                  <span class="lane-count font-mono-data">${triageItems.length} Open</span>
                </div>
                <div class="spatial-card-stack">
                  ${triageItems.length > 0 ? html`
                    <${NextBlockerStepper}
                      triageItems=${triageItems}
                      currentIndex=${Math.min(stepperIndex, triageItems.length - 1)}
                      onChangeIndex=${setStepperIndex}
                      matterId=${graph.matter_id}
                      nodes=${nodes}
                      onUpdated=${setCaseState}
                      onLocateRef=${(refId) => selectL0Claim(refId, true)}
                    />
                  ` : html`
                    <div class="bk-stepper-panel is-ready">
                      <div class="bk-stepper-bar">
                        <span class="bk-severity-pill is-ready">Zero-Doubt Gate Passed</span>
                      </div>
                      <h2 class="bk-stepper-title">Ready to Compile Official Filing Packet</h2>
                      <p class="bk-triage-prompt">
                        All extracted figures are matched to source coordinates, all Form 108 elections are set, and zero unresolved contradictions remain across ${plannedForms.length || 14} court forms.
                      </p>
                      <div>
                        <button type="button" class="btn btn-primary" onClick=${() => setShowPacketDrawer(true)}>
                          Compile & Sign Filing Packet <${ArrowRightIcon} />
                        </button>
                      </div>
                    </div>
                  `}
                </div>
              </section>
            `}

            ${l1Ids.length > 0 && html`
              <section class="column-lane" ref=${l1Ref} aria-label="L1 Deterministic Math and Client PDF Evidence">
                <div class="lane-header">
                  <span class="lane-title">Source Proof & Math Trace</span>
                  <button
                    type="button"
                    class="btn btn-compact"
                    onClick=${() => {
                      setPinnedClaimId(null);
                      setExpandedL2Ids([]);
                    }}
                  >
                    ${triageItems.length > 0 ? `Return to Blocker (${triageItems.length})` : 'Close Proof'}
                  </button>
                </div>
                <div class="spatial-card-stack">
                  ${nodes[pinnedClaimId] && html`
                    <div class="claim-context-bar">
                      <div class="kicker-label">Selected Schedule Entry</div>
                      <strong>${nodes[pinnedClaimId].title}</strong>
                    </div>
                  `}
                  ${l1Ids.map((nid) => {
                    const node = nodes[nid];
                    if (!node) return null;
                    const tone = getToneForNode(node);
                    const childAuths = node.direct_child_ids || [];
                    return html`
                      <article class=${`spatial-node-card ${tone.cls}`} data-card-id=${nid}>
                        <div class="plate-header-strip">
                          <div class="plate-role-meta">
                            <span class="plate-role-name">${tone.tag}</span>
                          </div>
                          <span class="arch-stamp">${formatAuditLabel(node.audit?.status)}</span>
                        </div>
                        <div class="plate-body-stage">
                          <h3 class="card-heading">${node.title}</h3>
                          ${node.formula && html`<pre class="font-mono-data bk-formula-box">${node.formula}</pre>`}
                          ${node.quote && html`<blockquote class="evidence-blockquote">“${node.quote}”</blockquote>`}
                          ${node.body && html`<p class="card-body-prose">${node.body}</p>`}
                        </div>
                        <div class="plate-footer-row">
                          <div class="plate-actions-group">
                            <button type="button" class="btn btn-compact" onClick=${() => setInspectorNode(node)}>
                              Inspect Source PDF
                            </button>
                          </div>
                          ${childAuths.length > 0 && html`
                            <div class="plate-actions-group">
                              <button
                                type="button"
                                class="btn btn-compact"
                                onClick=${() => {
                                  setExpandedL2Ids(childAuths);
                                  if (window.innerWidth <= 1180) {
                                    requestAnimationFrame(() => l2Ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
                                  }
                                }}
                              >
                                Governing Law (${childAuths.length}) <${ArrowRightIcon} />
                              </button>
                            </div>
                          `}
                        </div>
                      </article>
                    `;
                  })}
                </div>
              </section>
            `}

            <!-- Column 3 (L2+): Controlling Statutory Authorities & Reference Tables -->
            ${expandedL2Ids.length > 0 && html`
              <section class="column-lane" ref=${l2Ref} aria-label="L2+ Controlling Statutory Authorities">
                <div class="lane-header">
                  <span class="lane-title">Controlling Law & Tables</span>
                  <button type="button" class="btn btn-compact" onClick=${() => setExpandedL2Ids([])}>
                    <${CloseIcon} /> Close
                  </button>
                </div>
                <div class="spatial-card-stack">
                  ${expandedL2Ids.map((nid) => {
                    const node = nodes[nid];
                    if (!node) return null;
                    return html`
                      <article class="spatial-node-card plate-authority" data-card-id=${nid}>
                        <div class="plate-header-strip">
                          <div class="plate-role-meta">
                            <span class="plate-role-name is-copper">Statutory Authority</span>
                          </div>
                        </div>
                        <div class="plate-body-stage">
                          <h3 class="card-heading">${node.title}</h3>
                          <blockquote class="evidence-blockquote">${node.quote}</blockquote>
                        </div>
                      </article>
                    `;
                  })}
                </div>
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
        <div class="bk-modal-backdrop" onClick=${() => !busyMsg && setShowUploadModal(false)}>
          <div
            class="bk-modal-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="bk-new-case-title"
            onClick=${(e) => e.stopPropagation()}
          >
            <div class="drawer-header">
              <div>
                <h3 id="bk-new-case-title" class="card-heading">Create Case & Upload Client PDFs</h3>
                <div class="kicker-label">Client Intake & OCR Extraction</div>
              </div>
              <button type="button" class="btn btn-compact" disabled=${Boolean(busyMsg)} onClick=${() => setShowUploadModal(false)}>
                <${CloseIcon} /> Close
              </button>
            </div>
            <form class="drawer-body" onSubmit=${handleCreateAndExtract}>
              <div class="bk-field-group">
                <label class="bk-label" htmlFor="bk-new-matter-id">Matter Identifier (Slug)</label>
                <input
                  id="bk-new-matter-id"
                  class="bk-input"
                  required
                  placeholder="e.g., bk_ch7_doe_2026"
                  value=${newCaseId}
                  onInput=${(e) => setNewCaseId(e.target.value)}
                />
              </div>
              <div class="bk-inline-form">
                <div class="bk-field-group">
                  <label class="bk-label" htmlFor="bk-new-chapter">Bankruptcy Chapter</label>
                  <select id="bk-new-chapter" class="bk-select" value=${newChapter} onChange=${(e) => setNewChapter(e.target.value)}>
                    <option value="7">Chapter 7 (Liquidation)</option>
                    <option value="13">Chapter 13 (Wage Earner Plan)</option>
                  </select>
                </div>
                <div class="bk-field-group">
                  <label class="bk-label" htmlFor="bk-new-district">Filing Court District</label>
                  <select id="bk-new-district" class="bk-select" value=${newDistrict} onChange=${(e) => setNewDistrict(e.target.value)}>
                    <option value="CACB">CACB (Central District of CA)</option>
                    <option value="CAEB">CAEB (Eastern District of CA)</option>
                  </select>
                </div>
              </div>
              <div class="bk-field-group">
                <label class="bk-label" htmlFor="bk-upload-files">Client Source Documents (PDF, CSV, XLSX, MD)</label>
                <input
                  id="bk-upload-files"
                  type="file"
                  multiple
                  accept=".pdf,.csv,.xlsx,.md,.txt"
                  onChange=${(e) => setUploadFiles(Array.from(e.target.files || []))}
                />
              </div>
              ${modalError && html`<div class="bk-error-text" role="alert">${modalError}</div>`}
              <button class="btn btn-primary" type="submit" disabled=${Boolean(busyMsg) || !newCaseId.trim()}>
                ${busyMsg || 'Create Case & Run Audit Extraction'}
              </button>
            </form>
          </div>
        </div>
      `}
    </div>
  `;
}

render(html`<${BankruptcyApp} />`, document.getElementById('bk-app-root'));
