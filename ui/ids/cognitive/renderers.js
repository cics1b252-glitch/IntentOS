import {
  normalizeAgent, normalizeCapability, normalizeConfidence, normalizeContext,
  normalizeExecution, normalizeMission, normalizeProvenance, normalizePulse,
  normalizeRelationship, normalizeTimeline,
} from "./contracts.js";
import { escapeHTML, formatPublicTime, statePresentation } from "./shared.js";

const labels = Object.freeze({
  idle: "Idle", preparing: "Preparing", processing: "Processing",
  waiting: "Waiting", executing: "Executing", completed: "Completed",
  warning: "Warning", failed: "Failed", draft: "Draft", ready: "Ready",
  running: "Running", cancelled: "Cancelled", available: "Available",
  selected: "Selected", unavailable: "Unavailable", restricted: "Restricted",
  queued: "Queued", "waiting-for-provider": "Waiting for provider",
  "waiting-for-user": "Waiting for user", retrying: "Retrying",
  "partially-completed": "Partially completed",
});

const titleCase = (value) => String(value ?? "")
  .replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const labelFor = (state) => labels[state] ?? titleCase(state);
const e = escapeHTML;
const time = (value) => formatPublicTime(value);
const optional = (label, value) => value
  ? `<span class="ids-cognitive-meta"><strong>${e(label)}:</strong> ${e(value)}</span>` : "";
const stateMark = (state) => {
  const presentation = statePresentation(state, labelFor(state));
  return `<span class="ids-cognitive-state" data-tone="${e(presentation.tone)}"><span aria-hidden="true">${e(presentation.symbol)}</span> ${e(labelFor(state))}</span>`;
};
const childData = (value) => e(JSON.stringify(value));

export function renderPulse(input) {
  const data = normalizePulse(input);
  return `<span class="ids-cognitive-pulse" data-state="${e(data.state)}" role="status" aria-live="${data.state === "failed" ? "assertive" : "polite"}">
    <span class="ids-cognitive-pulse__mark" aria-hidden="true"></span>
    <span><strong>${e(data.label ?? labelFor(data.state))}</strong>${data.detail ? ` <span class="ids-caption">— ${e(data.detail)}</span>` : ""}</span>
  </span>`;
}

export function renderMission(input) {
  const data = normalizeMission(input);
  const expanded = data.expanded ? "true" : "false";
  const capabilities = data.capabilities.map((name) => (
    `<ids-capability-badge data-json="${childData({ name, state: "selected", description: `${name} capability` })}"></ids-capability-badge>`
  )).join("");
  const actions = data.actions.map((item) => (
    `<button type="button" data-action="${e(item.id)}"${item.disabled ? " disabled" : ""}>${e(item.label)}</button>`
  )).join("");
  return `<article class="ids-cognitive-card ids-mission-card" data-state="${e(data.status)}" data-selected="${data.selected}" tabindex="0" aria-label="Mission: ${e(data.title)}" aria-selected="${data.selected}">
    <header class="ids-cognitive-card__header">
      <div><p class="ids-label">${e(data.domain ?? "Mission")}</p><h3 class="ids-title">${e(data.title)}</h3></div>
      <ids-cognitive-pulse data-json="${childData({ state: data.status === "running" ? "executing" : data.status, label: labelFor(data.status) })}"></ids-cognitive-pulse>
    </header>
    <p>${e(data.objective)}</p>
    <div class="ids-cognitive-meta-row">${stateMark(data.status)}${optional("Priority", data.priority)}${optional("Date", data.date ? time(data.date) : null)}</div>
    ${data.progress === null ? "" : `<label class="ids-cognitive-progress">Progress: ${e(data.progress)}%<progress max="100" value="${e(data.progress)}"></progress></label>`}
    ${capabilities ? `<div class="ids-cognitive-badges" aria-label="Capabilities">${capabilities}</div>` : ""}
    <button type="button" class="ids-cognitive-disclosure" data-expand aria-expanded="${expanded}">Mission details</button>
    <div class="ids-cognitive-details"${data.expanded ? "" : " hidden"}>
      ${optional("Next action", data.nextAction)}
      ${data.alerts.length ? `<ul aria-label="Alerts">${data.alerts.map((alert) => `<li>${e(alert)}</li>`).join("")}</ul>` : ""}
      ${Object.keys(data.metadata).length ? `<dl>${Object.entries(data.metadata).map(([key, value]) => `<dt>${e(key)}</dt><dd>${e(value)}</dd>`).join("")}</dl>` : ""}
    </div>
    ${actions ? `<footer class="ids-cognitive-actions">${actions}</footer>` : ""}
  </article>`;
}

export function renderContext(input) {
  const data = normalizeContext(input);
  const sensitivity = data.sensitive === null ? "Sensitivity not informed"
    : data.sensitive ? "Sensitive content" : "Not marked as sensitive";
  return `<article class="ids-cognitive-card ids-context-card" aria-label="${e(data.title)}">
    <header class="ids-cognitive-card__header"><div><p class="ids-label">${e(titleCase(data.type))} context</p><h3 class="ids-title">${e(data.title)}</h3></div>${stateMark(data.availability)}</header>
    <p>${e(data.summary ?? "Summary not informed")}</p>
    <div class="ids-cognitive-meta-row">${optional("Source", data.source)}${optional("Date", data.date ? time(data.date) : null)}${data.relevance === null ? "" : optional("Provided relevance", `${data.relevance}%`)}</div>
    <p class="ids-caption">${e(sensitivity)}</p>
    ${data.details ? `<details${data.expanded ? " open" : ""}><summary>Context details</summary><p>${e(data.details)}</p></details>` : ""}
  </article>`;
}

export function renderCapability(input) {
  const data = normalizeCapability(input);
  return `<span class="ids-capability-badge" data-state="${e(data.state)}" role="status" aria-label="${e(data.name)}: ${e(labelFor(data.state))}. ${e(data.description)}">
    <span aria-hidden="true">${e(data.icon ?? statePresentation(data.state).symbol)}</span>
    <strong>${e(data.name)}</strong><span>${e(labelFor(data.state))}</span>
    ${data.category ? `<span class="ids-caption">${e(data.category)}</span>` : ""}
  </span>`;
}

export function renderTimeline(input) {
  const data = normalizeTimeline(input);
  const items = data.items.map((item) => `<li data-relevant="${item.relevant}">
    <details><summary><time datetime="${e(item.timestamp ?? "")}">${e(item.timestamp ? time(item.timestamp) : "Time not informed")}</time> — ${e(titleCase(item.type))}</summary>
      <p>${e(item.description)}</p><p class="ids-caption">Source: ${e(item.source)}</p>${item.details ? `<p>${e(item.details)}</p>` : ""}
    </details>
  </li>`).join("");
  return `<section class="ids-decision-timeline" aria-label="${e(data.label)}"><h3 class="ids-title">${e(data.label)}</h3>${items ? `<ol>${items}</ol>` : `<p class="ids-caption" role="status">No public events recorded.</p>`}</section>`;
}

export function renderConfidence(input) {
  const data = normalizeConfidence(input);
  let visual = `<span class="ids-caption">Not informed</span>`;
  if (data.mode === "percentage") {
    visual = `<span>${e(data.label)}: ${e(data.value)}%</span><progress max="100" value="${e(data.value)}" aria-label="${e(data.label)}"></progress>`;
  } else if (data.mode === "range") {
    visual = `<span>${e(data.label)}: ${e(data.minimum)}%–${e(data.maximum)}%</span>`;
  } else if (data.mode === "text") {
    visual = `<span>${e(data.label)}</span>`;
  }
  return `<span class="ids-confidence-indicator" role="status" data-mode="${e(data.mode)}">${visual}${optional("Source", data.source)}${optional("Method", data.method)}</span>`;
}

export function renderExecution(input) {
  const data = normalizeExecution(input);
  const step = data.currentStep !== null && data.totalSteps !== null
    ? `Step ${data.currentStep} of ${data.totalSteps}` : null;
  return `<section class="ids-execution-indicator ids-cognitive-card" data-state="${e(data.state)}" aria-label="${e(data.label)}">
    <header class="ids-cognitive-card__header"><h3 class="ids-title">${e(data.label)}</h3>${stateMark(data.state)}</header>
    ${data.detail ? `<p>${e(data.detail)}</p>` : ""}
    <div class="ids-cognitive-meta-row">${optional("Progress", step)}${optional("Duration", data.duration)}${optional("Provider", data.provider)}${optional("Software agent", data.agent)}${optional("Capability", data.capability)}${optional("Updated", data.updatedAt ? time(data.updatedAt) : null)}</div>
  </section>`;
}

export function renderProvenance(input) {
  const data = normalizeProvenance(input);
  return `<article class="ids-provenance-card ids-cognitive-card" aria-label="Provenance: ${e(data.source)}">
    <header class="ids-cognitive-card__header"><div><p class="ids-label">${e(titleCase(data.type))}</p><h3 class="ids-title">${e(data.source)}</h3></div>${stateMark(data.availability)}</header>
    <div class="ids-cognitive-meta-row">${optional("Date", data.date ? time(data.date) : null)}${optional("Author", data.author)}${optional("Location", data.location)}${optional("Version", data.version)}${optional("Provided reliability", data.reliability)}${optional("Reference", data.reference)}</div>
  </article>`;
}

export function renderAgent(input) {
  const data = normalizeAgent(input);
  return `<article class="ids-agent-status ids-cognitive-card" data-state="${e(data.state)}" aria-label="Software agent: ${e(data.name)}">
    <header class="ids-cognitive-card__header"><div><p class="ids-label">Software component</p><h3 class="ids-title">${e(data.name)}</h3></div>${stateMark(data.state)}</header>
    <p>${e(data.description)}</p><div class="ids-cognitive-meta-row">${optional("Capability", data.capability)}${optional("Updated", data.updatedAt ? time(data.updatedAt) : null)}</div>
  </article>`;
}

export function renderRelationship(input) {
  const data = normalizeRelationship(input);
  return `<article class="ids-knowledge-relationship ids-cognitive-card" aria-label="Knowledge relationship">
    <div class="ids-relationship-flow"><strong>${e(data.source)}</strong><span aria-label="${e(titleCase(data.relationship))}">→ ${e(titleCase(data.relationship))} →</span><strong>${e(data.target)}</strong></div>
    <div class="ids-cognitive-meta-row">${optional("Date", data.date ? time(data.date) : null)}${optional("Provenance", data.provenance)}</div>${data.notes ? `<p>${e(data.notes)}</p>` : ""}
  </article>`;
}

export const cognitiveCatalog = Object.freeze({
  "ids-cognitive-pulse": { normalize: normalizePulse, render: renderPulse },
  "ids-mission-card": { normalize: normalizeMission, render: renderMission, interactive: true },
  "ids-context-card": { normalize: normalizeContext, render: renderContext },
  "ids-capability-badge": { normalize: normalizeCapability, render: renderCapability },
  "ids-decision-timeline": { normalize: normalizeTimeline, render: renderTimeline },
  "ids-confidence-indicator": { normalize: normalizeConfidence, render: renderConfidence },
  "ids-execution-indicator": { normalize: normalizeExecution, render: renderExecution },
  "ids-provenance-card": { normalize: normalizeProvenance, render: renderProvenance },
  "ids-agent-status": { normalize: normalizeAgent, render: renderAgent },
  "ids-knowledge-relationship-card": { normalize: normalizeRelationship, render: renderRelationship },
});
