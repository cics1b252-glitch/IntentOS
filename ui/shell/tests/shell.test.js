import test from "node:test";
import assert from "node:assert/strict";
import { CognitiveShell, bootstrapShell } from "../bootstrap.js";
import { demoFixture, demoMissions, emptyDemoFixture } from "../fixtures/index.js";
import { renderShellLayout } from "../layout/index.js";
import { renderMissionRail, groupMissions } from "../mission-rail/index.js";
import { NAV_ITEMS, renderNavigation } from "../navigation/index.js";
import { createLocalRouter, normalizeRoute } from "../router.js";
import {
  SHELL_ROUTES, WORKSPACE_STATES, normalizeShellState, selectMission,
  updateShellState,
} from "../state.js";
import { renderSystemStatus } from "../system-status/index.js";
import {
  renderComingSoon, renderMissions, renderSettings, renderWelcome, renderWorkspace,
} from "../workspace/index.js";

test("Shell state is serializable and has safe defaults", () => {
  const state = normalizeShellState(null);
  assert.equal(state.route, "home");
  assert.equal(state.workspaceState, "welcome");
  assert.equal(state.missions.length, 0);
  assert.doesNotThrow(() => JSON.stringify(state));
  assert.equal(normalizeShellState({ route: "bad", workspaceState: "bad" }).route, "home");
});

test("every route and workspace state is preserved by the presentation contract", () => {
  for (const route of SHELL_ROUTES) assert.equal(normalizeShellState({ route }).route, route);
  for (const workspaceState of WORKSPACE_STATES) {
    assert.equal(normalizeShellState({ workspaceState }).workspaceState, workspaceState);
  }
});

test("state updates preserve nested panels, preferences and navigation", () => {
  const state = normalizeShellState(demoFixture);
  const next = updateShellState(state, {
    panels: { contextOpen: false }, preferences: { ambient: "cream" },
    navigation: { current: "missions" },
  });
  assert.equal(next.panels.contextOpen, false);
  assert.equal(next.panels.missionRailOpen, true);
  assert.equal(next.preferences.ambient, "cream");
  assert.equal(next.navigation.current, "missions");
});

test("mission selection is local and handles known and unknown values", () => {
  const state = normalizeShellState(demoFixture);
  assert.equal(selectMission(state, "missing"), state);
  assert.equal(selectMission(state, demoMissions[3].title).workspaceState, "waiting-for-user");
  assert.equal(selectMission(state, demoMissions[4].title).workspaceState, "completed");
  assert.equal(selectMission(state, demoMissions[5].title).workspaceState, "failed");
  assert.equal(selectMission(state, demoMissions[1].title).workspaceState, "mission-selected");
});

test("local router normalizes, announces and disposes without framework", () => {
  const events = new Map();
  const target = {
    addEventListener: (name, listener) => events.set(name, listener),
    removeEventListener: (name) => events.delete(name),
  };
  const location = { hash: "#/home" };
  const router = createLocalRouter({ location, eventTarget: target });
  const observed = [];
  const unsubscribe = router.subscribe((value) => observed.push(value));
  assert.equal(router.current(), "home");
  assert.equal(router.navigate("missions"), "missions");
  assert.equal(location.hash, "#/missions");
  events.get("hashchange")();
  assert.deepEqual(observed, ["missions", "missions"]);
  unsubscribe();
  assert.equal(normalizeRoute("#/bad"), "home");
  router.dispose();
  assert.equal(events.size, 0);
});

test("navigation exposes all routes, current state and future placeholders", () => {
  const markup = renderNavigation(normalizeShellState(demoFixture));
  assert.equal(NAV_ITEMS.length, 6);
  assert.match(markup, /aria-current="page"/);
  assert.match(markup, /aria-disabled="true"/);
  for (const route of SHELL_ROUTES) assert.match(markup, new RegExp(route));
});

test("mission rail groups states and renders empty, compactable content", () => {
  const groups = groupMissions(normalizeShellState(demoFixture).missions);
  assert.ok(groups.Active.length);
  assert.ok(groups.Recent.length);
  assert.match(renderMissionRail(normalizeShellState(demoFixture)), /data-mission=/);
  assert.match(renderMissionRail(normalizeShellState(emptyDemoFixture)), /No missions/);
});

test("workspace renders Home, Missions, Settings and future routes", () => {
  const state = normalizeShellState(demoFixture);
  assert.match(renderWelcome(state), /Recent missions/);
  assert.match(renderMissions({ ...state, route: "missions", workspaceState: "running" }), /Mission selected|Running/);
  assert.match(renderMissions({ ...state, selectedMission: null }), /Select a mission/);
  assert.match(renderSettings(state), /data-theme-axis="appearance"/);
  assert.match(renderComingSoon("oem-studio"), /OEM Studio/);
  for (const route of SHELL_ROUTES) {
    assert.ok(renderWorkspace({ ...state, route }).length > 20);
  }
});

test("layout composes landmarks, panels, cognitive components and status", () => {
  const state = normalizeShellState(demoFixture);
  const markup = renderShellLayout(state);
  for (const expected of [
    "Skip to workspace", "Global navigation", "Mission rail",
    "primary-workspace", "Mission context", "Shell status",
  ]) assert.match(markup, new RegExp(expected));
  assert.match(markup, /ids-cognitive-pulse/);
  assert.match(renderSystemStatus(state), /Demonstration mode/);
});

const fakeRoot = () => {
  const listeners = new Map();
  return {
    innerHTML: "", listeners,
    addEventListener(name, listener) { listeners.set(name, listener); },
    removeEventListener(name) { listeners.delete(name); },
    querySelector() { return null; },
    replaceChildren() { this.innerHTML = ""; },
  };
};
const fakeRouter = () => ({
  value: "home", listener: null, disposed: false,
  current() { return this.value; },
  subscribe(listener) { this.listener = listener; return () => { this.listener = null; }; },
  navigate(value) { this.value = value; this.listener?.(value); return value; },
  dispose() { this.disposed = true; },
});
const fakeTheme = () => ({
  disposed: false,
  load: () => ({ theme: demoFixture.preferences }),
  set: (patch) => ({ theme: { ...demoFixture.preferences, ...patch } }),
  dispose() { this.disposed = true; },
});

test("bootstrap, interactions, theme changes and destruction have a complete lifecycle", () => {
  const root = fakeRoot();
  const router = fakeRouter();
  const theme = fakeTheme();
  const shell = bootstrapShell({ root, router, theme, initialState: demoFixture });
  assert.ok(root.innerHTML.includes("cognitive-shell"));
  assert.equal(root.listeners.size, 3);
  shell.handleAction("toggle-navigation");
  shell.handleAction("toggle-missions");
  shell.handleAction("toggle-context");
  shell.handleAction("pin-context");
  shell.handleAction("new-demo");
  shell.handleChange({ target: { dataset: { themeAxis: "ambient" }, value: "atlas" } });
  assert.equal(shell.state.preferences.ambient, "atlas");
  shell.handleKeydown({ key: "Escape" });
  shell.handleKeydown({ key: "Other" });
  shell.destroy();
  assert.equal(root.listeners.size, 0);
  assert.equal(router.disposed, true);
  assert.equal(theme.disposed, true);
});

test("click delegation routes, selects, acts and respects disabled destinations", () => {
  const shell = new CognitiveShell({
    root: fakeRoot(), router: fakeRouter(), theme: fakeTheme(), initialState: demoFixture,
  }).start();
  const event = (match) => ({
    prevented: false,
    preventDefault() { this.prevented = true; },
    target: { closest: (selector) => match[selector] ?? null },
  });
  const routeEvent = event({ "a[data-route], button[data-route]": {
    dataset: { route: "missions" }, getAttribute: () => null,
  } });
  shell.handleClick(routeEvent);
  assert.equal(shell.state.route, "missions");
  const disabledEvent = event({ "a[data-route], button[data-route]": {
    dataset: { route: "atlas" }, getAttribute: () => "true",
  } });
  shell.handleClick(disabledEvent);
  assert.equal(shell.state.route, "missions");
  shell.handleClick(event({ "[data-mission]": { dataset: { mission: demoMissions[2].title } } }));
  assert.equal(shell.state.selectedMission, demoMissions[2].title);
  shell.handleClick(event({ "[data-shell-action]": { dataset: { shellAction: "pin-context" } } }));
  shell.destroy();
});
