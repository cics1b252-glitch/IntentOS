import test from "node:test";
import assert from "node:assert/strict";
import {
  AGENT_STATES, CAPABILITY_STATES, CONTEXT_TYPES, EXECUTION_STATES,
  MISSION_STATES, PROVENANCE_TYPES, PULSE_STATES, RELATIONSHIP_TYPES,
  TIMELINE_TYPES, cognitiveCatalog, isActivationKey, normalizeAgent,
  normalizeCapability, normalizeConfidence, normalizeContext, normalizeExecution,
  normalizeMission, normalizeProvenance, normalizePulse, normalizeRelationship,
  normalizeTimeline, parsePresentationData, registerCognitiveComponents,
  renderAgent, renderCapability, renderConfidence, renderContext, renderExecution,
  renderMission, renderProvenance, renderPulse, renderRelationship, renderTimeline,
  statePresentation, toggleDisclosure,
} from "../cognitive/index.js";

const all = (values, normalize, render, key = "state") => {
  for (const value of values) {
    const normalized = normalize({ [key]: value });
    assert.equal(normalized[key], value);
    const markup = render({ [key]: value });
    assert.match(markup, new RegExp(value.replaceAll("-", "[ -]"), "i"));
  }
};

test("all public observable states normalize and render", () => {
  all(PULSE_STATES, normalizePulse, renderPulse);
  all(MISSION_STATES, normalizeMission, renderMission, "status");
  all(CAPABILITY_STATES, normalizeCapability, renderCapability);
  all(EXECUTION_STATES, normalizeExecution, renderExecution);
  all(AGENT_STATES, normalizeAgent, renderAgent);
  all(CONTEXT_TYPES, normalizeContext, renderContext, "type");
  all(PROVENANCE_TYPES, normalizeProvenance, renderProvenance, "type");
  all(RELATIONSHIP_TYPES, normalizeRelationship, renderRelationship, "relationship");
});

test("timeline uses public events in chronological order", () => {
  const data = normalizeTimeline({ items: [
    { type: TIMELINE_TYPES[1], timestamp: "2026-07-29T12:00:00Z", description: "Second" },
    { type: TIMELINE_TYPES[0], timestamp: "2026-07-29T10:00:00Z", description: "First" },
  ] });
  assert.equal(data.items[0].description, "First");
  assert.ok(renderTimeline(data).indexOf("First") < renderTimeline(data).indexOf("Second"));
  for (const type of TIMELINE_TYPES) {
    assert.equal(normalizeTimeline({ items: [{ type }] }).items[0].type, type);
  }
});

test("contracts provide serializable fallbacks and clamp supplied values", () => {
  const values = [
    normalizePulse(null), normalizeMission(null), normalizeContext(null),
    normalizeCapability(null), normalizeTimeline(null), normalizeConfidence(null),
    normalizeExecution(null), normalizeProvenance(null), normalizeAgent(null),
    normalizeRelationship(null),
  ];
  for (const value of values) assert.doesNotThrow(() => JSON.stringify(value));
  assert.equal(normalizeMission({ progress: 120 }).progress, 100);
  assert.equal(normalizeContext({ relevance: -1 }).relevance, 0);
  assert.equal(normalizeMission({ capabilities: "bad", actions: [{ id: "x" }] }).actions.length, 0);
  assert.equal(normalizeExecution({ currentStep: -1, totalSteps: -2 }).currentStep, 0);
});

test("confidence is only displayed when explicitly supplied", () => {
  assert.equal(normalizeConfidence({ mode: "percentage" }).mode, "unavailable");
  assert.equal(normalizeConfidence({ mode: "range", minimum: 20 }).mode, "unavailable");
  assert.match(renderConfidence({ mode: "unavailable" }), /Not informed/);
  assert.match(renderConfidence({ mode: "percentage", value: 72, source: "Public score" }), /72%/);
  assert.match(renderConfidence({ mode: "range", minimum: 60, maximum: 80 }), /60%–80%/);
  assert.match(renderConfidence({ mode: "text", label: "Moderate" }), /Moderate/);
});

test("renderers escape unsafe and preserve long translatable presentation text", () => {
  const attack = `<img src=x onerror="alert(1)">`;
  const long = `Descrição ${"muito ".repeat(100)}`;
  const outputs = [
    renderPulse({ label: attack, detail: long }),
    renderMission({ title: attack, objective: long, metadata: { source: attack } }),
    renderContext({ title: attack, summary: long, details: attack }),
    renderCapability({ name: attack, description: long }),
    renderTimeline({ items: [{ description: attack, details: long }] }),
    renderExecution({ label: attack, detail: long }),
    renderProvenance({ source: attack, author: long }),
    renderAgent({ name: attack, description: long }),
    renderRelationship({ source: attack, target: long, notes: attack }),
  ];
  for (const output of outputs) {
    assert.doesNotMatch(output, /<img/);
    assert.match(output, /&lt;img|Descrição/);
  }
});

test("mission renderer composes cognitive components and optional actions", () => {
  const output = renderMission({
    title: "Review", status: "running", capabilities: ["Search"],
    actions: [{ id: "pause", label: "Pause" }], expanded: true,
  });
  assert.match(output, /ids-cognitive-pulse/);
  assert.match(output, /ids-capability-badge/);
  assert.match(output, /data-action="pause"/);
  assert.doesNotMatch(output, /details" hidden/);
});

test("shared visual meanings remain stable and independent from color", () => {
  for (const state of ["success", "warning", "error", "waiting", "restricted", "unavailable"]) {
    const presentation = statePresentation(state);
    assert.ok(presentation.label);
    assert.ok(presentation.symbol);
    assert.ok(presentation.tone);
  }
  assert.equal(statePresentation("unknown", "Observed").label, "Observed");
});

test("framework-free registry registers every component exactly once", () => {
  const definitions = new Map();
  const registry = {
    get: (name) => definitions.get(name),
    define: (name, value) => definitions.set(name, value),
  };
  const first = registerCognitiveComponents(registry);
  const second = registerCognitiveComponents(registry);
  assert.deepEqual(first, Object.keys(cognitiveCatalog));
  assert.deepEqual(second, first);
  assert.equal(definitions.size, 10);
  assert.equal(new Set(definitions.values()).size, 10);
});

test("presentation JSON and keyboard helpers fail safely", () => {
  assert.deepEqual(parsePresentationData('{"state":"ready"}'), { state: "ready" });
  assert.deepEqual(parsePresentationData("bad"), {});
  assert.deepEqual(parsePresentationData("[]"), {});
  assert.deepEqual(parsePresentationData(""), {});
  assert.equal(isActivationKey("Enter"), true);
  assert.equal(isActivationKey(" "), true);
  assert.equal(isActivationKey("Escape"), false);
});

test("disclosure helper toggles expanded state without domain behavior", () => {
  const attributes = new Map([["aria-expanded", "false"]]);
  const details = { hidden: true };
  const trigger = {
    nextElementSibling: details,
    getAttribute: (name) => attributes.get(name),
    setAttribute: (name, value) => attributes.set(name, value),
  };
  assert.equal(toggleDisclosure(trigger), true);
  assert.equal(details.hidden, false);
  assert.equal(toggleDisclosure(trigger), false);
  assert.equal(details.hidden, true);
  assert.equal(toggleDisclosure({ nextElementSibling: null }), false);
});

test("empty timelines and unavailable presentation remain understandable", () => {
  assert.match(renderTimeline({}), /No public events recorded/);
  assert.match(renderContext({}), /Sensitivity not informed/);
  assert.match(renderAgent({}), /Software component/);
  assert.match(renderRelationship({}), /not informed/);
});
