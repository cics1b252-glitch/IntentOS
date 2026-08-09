import { escapeHTML } from "../../ids/cognitive/shared.js";

const data = (value) => escapeHTML(JSON.stringify(value));

export function renderContextPanel(state) {
  const cards = [
    ...state.context.map((item) => `<ids-context-card data-json="${data(item)}"></ids-context-card>`),
    ...state.provenance.map((item) => `<ids-provenance-card data-json="${data(item)}"></ids-provenance-card>`),
    ...state.agents.map((item) => `<ids-agent-status data-json="${data(item)}"></ids-agent-status>`),
    ...state.relationships.map((item) => `<ids-knowledge-relationship-card data-json="${data(item)}"></ids-knowledge-relationship-card>`),
  ].join("");
  return `<aside id="context-panel" class="shell-context" aria-label="Mission context" data-open="${state.panels.contextOpen}" data-pinned="${state.panels.contextPinned}">
    <header><div><p class="ids-label">Supplied context</p><h2 class="ids-title">Context</h2></div>
      <div class="ids-cluster"><button type="button" data-shell-action="pin-context" aria-pressed="${state.panels.contextPinned}">Pin</button>
      <button type="button" data-shell-action="toggle-context" aria-expanded="${state.panels.contextOpen}" aria-controls="context-panel">×</button></div>
    </header>
    <div class="ids-cluster" aria-label="Available capabilities">${state.capabilities.map((item) => `<ids-capability-badge data-json="${data(item)}"></ids-capability-badge>`).join("")}</div>
    <div class="ids-stack">${cards || `<ids-empty-state role="status"><h3 class="ids-title">No context</h3><p>No public context was supplied.</p></ids-empty-state>`}</div>
  </aside>`;
}
