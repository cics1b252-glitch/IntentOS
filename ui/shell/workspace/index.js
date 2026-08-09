import { escapeHTML } from "../../ids/cognitive/shared.js";
import { renderActivityLayer } from "../activity-layer/index.js";

const data = (value) => escapeHTML(JSON.stringify(value));

const stateMessages = Object.freeze({
  welcome: ["Welcome", "Continue a recent mission or review public activity."],
  empty: ["Nothing active", "No demonstration mission is selected."],
  "mission-selected": ["Mission selected", "Review the supplied objective and observable status."],
  preparing: ["Preparing", "The public operation is being prepared."],
  running: ["Running", "A public operation is active."],
  "waiting-for-user": ["Confirmation required", "Review the request before continuing."],
  completed: ["Completed", "The public operation has completed."],
  failed: ["Unable to complete", "The public operation reported a failure."],
  unavailable: ["Unavailable", "This demonstration workspace is unavailable."],
});

function renderWelcome(state) {
  const recent = state.missions.slice(0, 3).map((mission) => (
    `<ids-mission-card data-json="${data(mission)}"></ids-mission-card>`
  )).join("");
  return `<div class="ids-stack"><header class="shell-hero"><p class="ids-label">Cognitive Shell</p><h1 class="ids-display">Welcome</h1><p>Choose a supplied mission or inspect recent public activity.</p>
    <div class="ids-cluster"><button type="button" data-route="missions">View missions</button><button type="button" data-shell-action="new-demo">Start a demonstration</button></div></header>
    <section aria-labelledby="recent-title" class="ids-stack"><h2 id="recent-title" class="ids-title">Recent missions</h2>${recent || "<p>No recent missions.</p>"}</section>
    <section aria-labelledby="available-title" class="ids-stack"><h2 id="available-title" class="ids-title">Available capabilities</h2><div class="ids-cluster">${state.capabilities.map((item) => `<ids-capability-badge data-json="${data(item)}"></ids-capability-badge>`).join("")}</div></section>
    ${renderActivityLayer(state.activity)}</div>`;
}

function renderMissions(state) {
  const selected = state.missions.find((mission) => mission.title === state.selectedMission);
  const [heading, message] = stateMessages[state.workspaceState];
  return `<div class="ids-stack"><header class="shell-section-heading"><div><p class="ids-label">Mission centered</p><h1 class="ids-heading">${escapeHTML(heading)}</h1></div><button type="button" data-shell-action="toggle-context" aria-controls="context-panel">Context</button></header>
    <p>${escapeHTML(message)}</p>
    ${selected ? `<ids-mission-card data-json="${data({ ...selected, expanded: true, selected: true })}"></ids-mission-card>` : `<ids-empty-state role="status"><h2 class="ids-title">Select a mission</h2><p>Choose a local demonstration mission from the rail.</p></ids-empty-state>`}
    ${renderActivityLayer(state.activity)}</div>`;
}

function renderSettings(state) {
  const p = state.preferences;
  const select = (axis, values) => `<label><span>${escapeHTML(axis[0].toUpperCase() + axis.slice(1))}</span><select data-theme-axis="${escapeHTML(axis)}">${values.map((value) => `<option value="${value}"${p[axis] === value ? " selected" : ""}>${value}</option>`).join("")}</select></label>`;
  return `<div class="ids-stack"><header><p class="ids-label">Local preferences</p><h1 class="ids-heading">Settings</h1><p>These controls use the existing Theme Engine.</p></header>
    <div class="shell-settings">${select("appearance", ["system", "light", "dark"])}${select("ambient", ["neutral", "lavender", "steel", "cream", "atlas"])}${select("density", ["comfortable", "compact"])}${select("motion", ["full", "reduced"])}</div></div>`;
}

function renderComingSoon(route) {
  const label = route === "oem-studio" ? "OEM Studio" : route[0].toUpperCase() + route.slice(1);
  return `<ids-empty-state role="status"><p class="ids-label">Future workspace</p><h1 class="ids-heading">${escapeHTML(label)}</h1><p>This accessible placeholder contains no product behavior yet.</p></ids-empty-state>`;
}

export function renderWorkspace(state) {
  if (state.route === "home") return renderWelcome(state);
  if (state.route === "missions") return renderMissions(state);
  if (state.route === "settings") return renderSettings(state);
  return renderComingSoon(state.route);
}

export { renderComingSoon, renderMissions, renderSettings, renderWelcome };
