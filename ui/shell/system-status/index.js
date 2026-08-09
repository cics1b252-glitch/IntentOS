import { escapeHTML } from "../../ids/cognitive/shared.js";

export function renderSystemStatus(state) {
  const status = state.systemStatus;
  const preference = state.preferences;
  return `<footer class="shell-status" aria-label="Shell status">
    <span><strong>Local:</strong> ${escapeHTML(status.local)}</span>
    <span><strong>Theme:</strong> ${escapeHTML(preference.appearance)} · ${escapeHTML(preference.ambient)} · ${escapeHTML(preference.density)} · ${escapeHTML(preference.motion)}</span>
    <span><strong>Connection:</strong> ${escapeHTML(status.connectivity)}</span>
    <span><strong>Providers:</strong> ${escapeHTML(status.providerAvailability)}</span>
    ${status.demonstration ? '<span class="shell-demo">Demonstration mode</span>' : ""}
  </footer>`;
}
