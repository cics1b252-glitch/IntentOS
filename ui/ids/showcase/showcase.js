import { ThemeEngine } from "../theme/index.js";
import { registerIDSComponents } from "../components/index.js";
import { renderIcon } from "../icons/index.js";
import { registerCognitiveComponents } from "../cognitive/index.js";

registerIDSComponents();
registerCognitiveComponents();
const engine = new ThemeEngine();
const resolved = engine.load();

for (const axis of ["appearance", "ambient", "density", "motion"]) {
  const control = document.querySelector(`#${axis}`);
  control.value = engine.preference[axis] ?? resolved.theme[axis];
  control.addEventListener("change", () => engine.set({ [axis]: control.value }));
}

const swatches = document.querySelector("#swatches");
for (const name of [
  "colorIdentity", "colorAmbient", "colorAction", "colorSuccess",
  "colorWarning", "colorError", "colorInfo", "colorData1", "colorData2",
  "colorData3", "colorData4", "colorData5",
]) {
  const item = document.createElement("div");
  item.className = "showcase-swatch";
  const tokenName = name
    .replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)
    .replace(/([a-z])(\d+)/g, "$1-$2");
  item.style.background = `var(--ids-${tokenName})`;
  item.title = name;
  item.setAttribute("aria-label", name);
  swatches.append(item);
}

const icons = document.querySelector("#icons");
for (const variant of ["outlined", "filled"]) {
  for (const size of ["small", "medium", "large"]) {
    const item = document.createElement("span");
    item.innerHTML = renderIcon("info", { variant, size, label: `${variant} ${size}` });
    icons.append(item);
  }
}

for (const [trigger, overlay] of [
  ["#open-modal", "#sample-modal"],
  ["#open-drawer", "#sample-drawer"],
]) {
  document.querySelector(trigger).addEventListener("click", () => document.querySelector(overlay).open());
}
document.querySelectorAll("[data-close]").forEach((button) => {
  button.addEventListener("click", () => button.closest("ids-modal, ids-drawer").close());
});
document.querySelector("#open-toast").addEventListener("click", () => {
  const toast = document.querySelector("#sample-toast");
  toast.hidden = false;
  globalThis.setTimeout(() => { toast.hidden = true; }, 4000);
});

const setData = (selector, data) => {
  const element = document.querySelector(selector);
  if (element) element.data = data;
};

setData("#mission-composition", {
  title: "Prepare accessibility review",
  objective: "Validate observable states across the cognitive component catalog.",
  status: "running", domain: "Design validation", priority: "High",
  date: "2026-07-29T13:00:00Z", progress: 64,
  capabilities: ["Accessibility review", "Visual inspection"],
  nextAction: "Inspect compact layout at 200% zoom.",
  alerts: ["Manual forced-colors validation remains conditional on browser support."],
  selected: true, expanded: true,
  actions: [{ id: "details", label: "Review public details" }],
});
setData("#execution-sample", {
  state: "waiting-for-user", label: "Showcase validation", currentStep: 3,
  totalSteps: 5, duration: "4 minutes", provider: "Not required",
  agent: "Visual test runner", capability: "Browser validation",
  updatedAt: "2026-07-29T13:12:00Z",
  detail: "Waiting for an observable confirmation.",
});
setData("#context-sample", {
  title: "Design foundation", type: "project", source: "IDS documentation",
  date: "2026-07-28T10:00:00Z", relevance: 92, availability: "available",
  sensitive: false, summary: "Public presentation guidance for this validation.",
  details: "No domain object or private processing detail is represented.", expanded: true,
});
setData("#timeline-sample", {
  label: "Public decision events",
  items: [
    { type: "mission-created", timestamp: "2026-07-29T13:00:00Z", description: "Validation mission created.", source: "Showcase" },
    { type: "capability-selected", timestamp: "2026-07-29T13:02:00Z", description: "Browser validation selected.", source: "Public capability registry", relevant: true },
    { type: "confirmation-requested", timestamp: "2026-07-29T13:05:00Z", description: "Manual visual confirmation requested.", source: "Validation workflow", details: "Only the public event is shown." },
  ],
});
setData("#provenance-sample", {
  type: "project-memory", source: "IDS-006 Cognitive Interaction",
  date: "2026-07-29T12:30:00Z", author: "Intent OS team", version: "1.0",
  reliability: "Reviewed", reference: "IDS-006", availability: "available",
});
setData("#agent-sample", {
  name: "Visual test runner", description: "Software component used for browser checks.",
  state: "available", capability: "Visual inspection",
});
setData("#relationship-sample", {
  source: "IDS executable foundation", relationship: "supports",
  target: "Cognitive component library", date: "2026-07-29T12:00:00Z",
  provenance: "Architecture boundary",
  notes: "This explicit relation was supplied by showcase data.",
});
setData("#confidence-sample", {
  mode: "range", label: "Provided confidence range", minimum: 70, maximum: 85,
  source: "Public validation contract", method: "Manual review",
});

for (const state of [
  "idle", "preparing", "processing", "waiting", "executing",
  "completed", "warning", "failed",
]) {
  const pulse = document.createElement("ids-cognitive-pulse");
  pulse.data = { state, label: state };
  document.querySelector("#pulse-states").append(pulse);
}

for (const state of [
  "available", "selected", "executing", "completed",
  "unavailable", "restricted", "failed",
]) {
  const badge = document.createElement("ids-capability-badge");
  badge.data = { name: "Capability", state, description: `${state} state` };
  document.querySelector("#capability-states").append(badge);
}
