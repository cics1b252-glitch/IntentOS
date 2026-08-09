import { escapeHTML } from "../../ids/cognitive/shared.js";

const data = (value) => escapeHTML(JSON.stringify(value));

export function renderActivityLayer(activity) {
  return `<section class="shell-activity ids-stack" aria-labelledby="activity-title">
    <header class="shell-section-heading"><div><p class="ids-label">Observable activity</p><h2 id="activity-title" class="ids-title">Activity</h2></div>
      <ids-cognitive-pulse data-json="${data(activity.pulse)}"></ids-cognitive-pulse></header>
    <p>${escapeHTML(activity.message)}</p>
    <ids-execution-indicator data-json="${data(activity.execution)}"></ids-execution-indicator>
    ${activity.confidence.mode === "unavailable" ? "" : `<ids-confidence-indicator data-json="${data(activity.confidence)}"></ids-confidence-indicator>`}
    <ids-decision-timeline data-json="${data(activity.timeline)}"></ids-decision-timeline>
  </section>`;
}
