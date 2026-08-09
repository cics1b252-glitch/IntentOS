import {
  clamp, enumValue, isoTime, safeArray, safeBoolean, safeNumber,
  safeOptionalText, safeText, toPlainObject,
} from "./shared.js";

export const PULSE_STATES = Object.freeze([
  "idle", "preparing", "processing", "waiting", "executing",
  "completed", "warning", "failed",
]);
export const MISSION_STATES = Object.freeze([
  "draft", "ready", "running", "waiting", "completed",
  "failed", "cancelled",
]);
export const CONTEXT_TYPES = Object.freeze([
  "user", "project", "knowledge", "historical", "provider", "system",
]);
export const CAPABILITY_STATES = Object.freeze([
  "available", "selected", "executing", "completed",
  "unavailable", "restricted", "failed",
]);
export const TIMELINE_TYPES = Object.freeze([
  "mission-created", "context-added", "capability-selected",
  "provider-selected", "execution-started", "external-effect-requested",
  "confirmation-requested", "confirmation-received",
  "execution-completed", "execution-failed", "decision-recorded",
]);
export const EXECUTION_STATES = Object.freeze([
  "queued", "preparing", "running", "waiting-for-provider",
  "waiting-for-user", "retrying", "completed", "partially-completed",
  "failed", "cancelled",
]);
export const PROVENANCE_TYPES = Object.freeze([
  "user-supplied", "project-memory", "uploaded-file", "knowledge-base",
  "provider-response", "external-source", "system-generated",
]);
export const AGENT_STATES = Object.freeze([
  "available", "selected", "preparing", "executing", "waiting",
  "completed", "unavailable", "restricted", "failed",
]);
export const RELATIONSHIP_TYPES = Object.freeze([
  "supports", "contradicts", "updates", "depends-on", "derived-from",
  "related-to", "replaces", "superseded-by",
]);

const action = (value) => {
  const item = toPlainObject(value);
  const id = safeText(item.id);
  const label = safeText(item.label);
  return id && label ? { id, label, disabled: safeBoolean(item.disabled) } : null;
};

export function normalizePulse(input) {
  const data = toPlainObject(input);
  return {
    state: enumValue(data.state, PULSE_STATES, "idle"),
    label: safeOptionalText(data.label),
    detail: safeOptionalText(data.detail),
    updatedAt: isoTime(data.updatedAt),
  };
}

export function normalizeMission(input) {
  const data = toPlainObject(input);
  const progress = safeNumber(data.progress);
  return {
    title: safeText(data.title, "Untitled mission"),
    objective: safeText(data.objective, "Objective not informed"),
    status: enumValue(data.status, MISSION_STATES, "draft"),
    domain: safeOptionalText(data.domain),
    priority: safeOptionalText(data.priority),
    date: isoTime(data.date),
    progress: progress === null ? null : clamp(progress, 0, 100),
    capabilities: safeArray(data.capabilities).map((item) => safeText(item)).filter(Boolean),
    nextAction: safeOptionalText(data.nextAction),
    alerts: safeArray(data.alerts).map((item) => safeText(item)).filter(Boolean),
    metadata: toPlainObject(data.metadata),
    selected: safeBoolean(data.selected),
    expanded: safeBoolean(data.expanded),
    actions: safeArray(data.actions).map(action).filter(Boolean),
  };
}

export function normalizeContext(input) {
  const data = toPlainObject(input);
  const relevance = safeNumber(data.relevance);
  return {
    title: safeText(data.title, "Context"),
    type: enumValue(data.type, CONTEXT_TYPES, "system"),
    source: safeText(data.source, "Source not informed"),
    date: isoTime(data.date),
    relevance: relevance === null ? null : clamp(relevance, 0, 100),
    availability: safeText(data.availability, "unknown"),
    sensitive: data.sensitive === true ? true : data.sensitive === false ? false : null,
    summary: safeOptionalText(data.summary),
    details: safeOptionalText(data.details),
    expanded: safeBoolean(data.expanded),
  };
}

export function normalizeCapability(input) {
  const data = toPlainObject(input);
  return {
    name: safeText(data.name, "Unnamed capability"),
    category: safeOptionalText(data.category),
    icon: safeOptionalText(data.icon),
    description: safeText(data.description, "Description not informed"),
    origin: safeOptionalText(data.origin),
    state: enumValue(data.state, CAPABILITY_STATES, "unavailable"),
  };
}

export function normalizeTimeline(input) {
  const data = toPlainObject(input);
  const items = safeArray(data.items).map((value, index) => {
    const item = toPlainObject(value);
    return {
      id: safeText(item.id, `event-${index + 1}`),
      type: enumValue(item.type, TIMELINE_TYPES, "decision-recorded"),
      timestamp: isoTime(item.timestamp),
      description: safeText(item.description, "Public description not informed"),
      source: safeText(item.source, "Source not informed"),
      relevant: safeBoolean(item.relevant),
      details: safeOptionalText(item.details),
    };
  }).sort((left, right) => (
    (left.timestamp ?? "9999").localeCompare(right.timestamp ?? "9999")
  ));
  return { label: safeText(data.label, "Decision timeline"), items };
}

export function normalizeConfidence(input) {
  const data = toPlainObject(input);
  const mode = enumValue(data.mode, ["percentage", "range", "text", "unavailable"], "unavailable");
  const value = safeNumber(data.value);
  const minimum = safeNumber(data.minimum);
  const maximum = safeNumber(data.maximum);
  if (mode === "percentage" && value === null) {
    return { mode: "unavailable", label: "Not informed", value: null, minimum: null, maximum: null, source: null, method: null };
  }
  if (mode === "range" && (minimum === null || maximum === null)) {
    return { mode: "unavailable", label: "Not informed", value: null, minimum: null, maximum: null, source: null, method: null };
  }
  return {
    mode,
    label: safeText(data.label, mode === "unavailable" ? "Not informed" : "Confidence"),
    value: value === null ? null : clamp(value, 0, 100),
    minimum: minimum === null ? null : clamp(minimum, 0, 100),
    maximum: maximum === null ? null : clamp(maximum, 0, 100),
    source: safeOptionalText(data.source),
    method: safeOptionalText(data.method),
  };
}

export function normalizeExecution(input) {
  const data = toPlainObject(input);
  const current = safeNumber(data.currentStep);
  const total = safeNumber(data.totalSteps);
  return {
    state: enumValue(data.state, EXECUTION_STATES, "queued"),
    label: safeText(data.label, "Execution"),
    currentStep: current === null ? null : Math.max(0, current),
    totalSteps: total === null ? null : Math.max(0, total),
    duration: safeOptionalText(data.duration),
    provider: safeOptionalText(data.provider),
    agent: safeOptionalText(data.agent),
    capability: safeOptionalText(data.capability),
    updatedAt: isoTime(data.updatedAt),
    detail: safeOptionalText(data.detail),
  };
}

export function normalizeProvenance(input) {
  const data = toPlainObject(input);
  return {
    type: enumValue(data.type, PROVENANCE_TYPES, "system-generated"),
    source: safeText(data.source, "Source not informed"),
    date: isoTime(data.date),
    author: safeOptionalText(data.author),
    location: safeOptionalText(data.location),
    version: safeOptionalText(data.version),
    reliability: safeOptionalText(data.reliability),
    reference: safeOptionalText(data.reference),
    availability: safeText(data.availability, "unknown"),
  };
}

export function normalizeAgent(input) {
  const data = toPlainObject(input);
  return {
    name: safeText(data.name, "Software agent"),
    description: safeText(data.description, "Software component"),
    state: enumValue(data.state, AGENT_STATES, "unavailable"),
    capability: safeOptionalText(data.capability),
    updatedAt: isoTime(data.updatedAt),
  };
}

export function normalizeRelationship(input) {
  const data = toPlainObject(input);
  return {
    source: safeText(data.source, "Source item not informed"),
    relationship: enumValue(data.relationship, RELATIONSHIP_TYPES, "related-to"),
    target: safeText(data.target, "Target item not informed"),
    date: isoTime(data.date),
    provenance: safeOptionalText(data.provenance),
    notes: safeOptionalText(data.notes),
  };
}
