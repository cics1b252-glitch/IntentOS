import {
  normalizeAgent, normalizeCapability, normalizeConfidence, normalizeContext,
  normalizeExecution, normalizeMission, normalizeProvenance, normalizePulse,
  normalizeRelationship, normalizeTimeline,
} from "../ids/cognitive/contracts.js";
import { safeArray, safeBoolean, safeText, toPlainObject } from "../ids/cognitive/shared.js";

export const SHELL_ROUTES = Object.freeze([
  "home", "missions", "knowledge", "atlas", "oem-studio", "settings",
]);
export const WORKSPACE_STATES = Object.freeze([
  "welcome", "empty", "mission-selected", "preparing", "running",
  "waiting-for-user", "completed", "failed", "unavailable",
]);

const route = (value) => SHELL_ROUTES.includes(value) ? value : "home";
const workspaceState = (value) => WORKSPACE_STATES.includes(value) ? value : "welcome";
const panelState = (value) => {
  const data = toPlainObject(value);
  return {
    missionRailOpen: data.missionRailOpen !== false,
    contextOpen: data.contextOpen !== false,
    contextPinned: safeBoolean(data.contextPinned),
    navigationExpanded: data.navigationExpanded !== false,
  };
};

export function normalizeShellState(input) {
  const data = toPlainObject(input);
  const missions = safeArray(data.missions).map(normalizeMission);
  const selectedMission = safeText(data.selectedMission);
  const preferences = toPlainObject(data.preferences);
  const status = toPlainObject(data.systemStatus);
  return {
    route: route(data.route),
    navigation: { current: route(data.navigation?.current ?? data.route) },
    selectedMission: missions.some((mission) => mission.title === selectedMission)
      ? selectedMission : null,
    missions,
    workspaceState: workspaceState(data.workspaceState),
    context: safeArray(data.context).map(normalizeContext),
    provenance: safeArray(data.provenance).map(normalizeProvenance),
    capabilities: safeArray(data.capabilities).map(normalizeCapability),
    agents: safeArray(data.agents).map(normalizeAgent),
    relationships: safeArray(data.relationships).map(normalizeRelationship),
    activity: {
      pulse: normalizePulse(data.activity?.pulse),
      execution: normalizeExecution(data.activity?.execution),
      timeline: normalizeTimeline(data.activity?.timeline),
      confidence: normalizeConfidence(data.activity?.confidence),
      message: safeText(data.activity?.message, "No public activity."),
    },
    systemStatus: {
      local: safeText(status.local, "ready"),
      connectivity: safeText(status.connectivity, "demo"),
      providerAvailability: safeText(status.providerAvailability, "simulated"),
      demonstration: status.demonstration !== false,
    },
    panels: panelState(data.panels),
    preferences: {
      appearance: safeText(preferences.appearance, "system"),
      ambient: safeText(preferences.ambient, "neutral"),
      density: safeText(preferences.density, "comfortable"),
      motion: safeText(preferences.motion, "full"),
    },
  };
}

export function updateShellState(current, patch) {
  const next = { ...current, ...toPlainObject(patch) };
  if (patch?.panels) next.panels = { ...current.panels, ...patch.panels };
  if (patch?.preferences) next.preferences = { ...current.preferences, ...patch.preferences };
  if (patch?.navigation) next.navigation = { ...current.navigation, ...patch.navigation };
  return normalizeShellState(next);
}

export function selectMission(current, title) {
  const mission = current.missions.find((item) => item.title === title);
  if (!mission) return current;
  return updateShellState(current, {
    route: "missions",
    navigation: { current: "missions" },
    selectedMission: mission.title,
    workspaceState: mission.status === "failed" ? "failed"
      : mission.status === "completed" ? "completed"
        : mission.status === "waiting" ? "waiting-for-user" : "mission-selected",
  });
}
