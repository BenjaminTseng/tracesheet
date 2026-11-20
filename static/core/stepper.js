/**
 * Shared blocker/advisory triage stepper frame wrapping app-specific resolution forms.
 */

import { html, ArrowLeftIcon, ArrowRightIcon } from './shell.js';

export function TriageStepperFrame({
  currentIndex = 0,
  totalItems = 0,
  blockerCount = 0,
  advisoryCount = 0,
  severity = 'blocker',
  title = '',
  prompt = '',
  tags = [],
  tagsAriaLabel = 'Affected Outputs',
  formatTag = (t) => t,
  error = null,
  onPrev,
  onNext,
  children,
}) {
  if (totalItems <= 0) return null;
  const isBlocker = severity === 'blocker';

  return html`
    <div class=${`bk-stepper-panel ${isBlocker ? 'is-blocker' : 'is-advisory'}`}>
      <div class="bk-stepper-bar">
        <div class="bk-stepper-counts">
          <span class=${`bk-severity-pill ${isBlocker ? 'is-blocker' : 'is-advisory'}`}>
            ${isBlocker ? 'Filing Blocker' : 'Advisory Check'}
          </span>
          <span class="kicker-label">
            Item <span class="font-mono-data">${currentIndex + 1}</span> of <span class="font-mono-data">${totalItems}</span>
            (${blockerCount} Blocker, ${advisoryCount} Advisory)
          </span>
        </div>
        <div class="bk-stepper-nav">
          <button
            type="button"
            class="btn btn-compact"
            disabled=${currentIndex <= 0}
            aria-label="Previous audit item"
            onClick=${onPrev}
          >
            <${ArrowLeftIcon} /> Prev
          </button>
          <button
            type="button"
            class="btn btn-compact"
            disabled=${currentIndex >= totalItems - 1}
            aria-label="Next audit item"
            onClick=${onNext}
          >
            Next <${ArrowRightIcon} />
          </button>
        </div>
      </div>

      <h2 class="bk-stepper-title">${title}</h2>
      ${prompt && html`<p class="bk-triage-prompt">${prompt}</p>`}

      ${tags?.length > 0 && html`
        <div class="bk-form-tags" aria-label=${tagsAriaLabel}>
          ${tags.map((fc) => html`<span key=${fc} class="bk-form-chip">${formatTag(fc)}</span>`)}
        </div>
      `}

      ${children}

      ${error && html`<div class="bk-error-text" role="alert">${error}</div>`}
    </div>
  `;
}
