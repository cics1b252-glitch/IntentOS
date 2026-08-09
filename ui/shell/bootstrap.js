import { registerIDSComponents } from "../ids/components/index.js";
import { registerCognitiveComponents } from "../ids/cognitive/index.js";
import { ThemeEngine } from "../ids/theme/index.js";
import { demoFixture } from "./fixtures/index.js";
import { renderShellLayout } from "./layout/index.js";
import { createLocalRouter } from "./router.js";
import { normalizeShellState, selectMission, updateShellState } from "./state.js";

export class CognitiveShell {
  constructor({
    root, initialState = demoFixture, router = createLocalRouter(),
    theme = new ThemeEngine(),
  } = {}) {
    if (!root) throw new Error("Cognitive Shell requires a root element.");
    this.root = root;
    this.router = router;
    this.theme = theme;
    this.state = normalizeShellState({
      ...initialState,
      route: router.current(),
      navigation: { current: router.current() },
    });
    this.unsubscribe = null;
    this.onClick = (event) => this.handleClick(event);
    this.onChange = (event) => this.handleChange(event);
    this.onKeydown = (event) => this.handleKeydown(event);
  }

  start() {
    registerIDSComponents();
    registerCognitiveComponents();
    const resolved = this.theme.load();
    this.state = updateShellState(this.state, { preferences: resolved.theme });
    this.unsubscribe = this.router.subscribe((route) => {
      this.setState({
        route,
        navigation: { current: route },
        workspaceState: route === "missions"
          ? (this.state.selectedMission ? "mission-selected" : "empty")
          : route === "home" ? "welcome" : this.state.workspaceState,
      });
    });
    this.root.addEventListener("click", this.onClick);
    this.root.addEventListener("change", this.onChange);
    this.root.addEventListener("keydown", this.onKeydown);
    this.render();
    return this;
  }

  destroy() {
    this.root.removeEventListener("click", this.onClick);
    this.root.removeEventListener("change", this.onChange);
    this.root.removeEventListener("keydown", this.onKeydown);
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.router.dispose();
    this.theme.dispose();
    this.root.replaceChildren();
  }

  setState(patch, focusSelector = null) {
    this.state = updateShellState(this.state, patch);
    this.render();
    this.root.querySelector(focusSelector)?.focus();
    return this.state;
  }

  render() {
    this.root.innerHTML = renderShellLayout(this.state);
  }

  handleClick(event) {
    const routeLink = event.target.closest?.("a[data-route], button[data-route]");
    if (routeLink) {
      event.preventDefault();
      if (routeLink.getAttribute("aria-disabled") === "true") return;
      this.router.navigate(routeLink.dataset.route);
      return;
    }
    const mission = event.target.closest?.("[data-mission]")?.dataset.mission;
    if (mission) {
      this.state = selectMission(this.state, mission);
      this.render();
      return;
    }
    const action = event.target.closest?.("[data-shell-action]")?.dataset.shellAction;
    if (action) this.handleAction(action);
  }

  handleAction(action) {
    const panels = this.state.panels;
    if (action === "toggle-navigation") {
      this.setState({ panels: { navigationExpanded: !panels.navigationExpanded } });
    } else if (action === "toggle-missions") {
      this.setState({ panels: { missionRailOpen: !panels.missionRailOpen } },
        !panels.missionRailOpen ? "#mission-rail button" : null);
    } else if (action === "toggle-context") {
      this.setState({ panels: { contextOpen: !panels.contextOpen } },
        !panels.contextOpen ? "#context-panel button" : null);
    } else if (action === "pin-context") {
      this.setState({ panels: { contextPinned: !panels.contextPinned } });
    } else if (action === "new-demo") {
      this.router.navigate("missions");
    }
  }

  handleChange(event) {
    const axis = event.target.dataset?.themeAxis;
    if (!axis) return;
    const resolved = this.theme.set({ [axis]: event.target.value });
    this.setState({ preferences: resolved.theme });
  }

  handleKeydown(event) {
    if (event.key !== "Escape") return;
    if (this.state.panels.contextOpen && !this.state.panels.contextPinned) {
      this.setState({ panels: { contextOpen: false } });
    } else if (this.state.panels.missionRailOpen) {
      this.setState({ panels: { missionRailOpen: false } });
    }
  }
}

export function bootstrapShell(options = {}) {
  const root = options.root ?? globalThis.document?.querySelector("#intent-shell");
  return new CognitiveShell({ ...options, root }).start();
}

if (globalThis.document) bootstrapShell();
