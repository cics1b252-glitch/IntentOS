import { renderContextPanel } from "../context-panel/index.js";
import { renderMissionRail } from "../mission-rail/index.js";
import { renderNavigation } from "../navigation/index.js";
import { renderSystemStatus } from "../system-status/index.js";
import { renderWorkspace } from "../workspace/index.js";

export function renderShellLayout(state) {
  return `<a class="shell-skip-link" href="#primary-workspace">Skip to workspace</a>
    <div class="cognitive-shell" data-current-route="${state.route}">
      ${renderNavigation(state)}
      <button class="shell-mobile-trigger shell-mobile-trigger--missions" type="button" data-shell-action="toggle-missions" aria-controls="mission-rail">Missions</button>
      ${renderMissionRail(state)}
      <main id="primary-workspace" class="shell-workspace" tabindex="-1">${renderWorkspace(state)}</main>
      <button class="shell-mobile-trigger shell-mobile-trigger--context" type="button" data-shell-action="toggle-context" aria-controls="context-panel">Context</button>
      ${renderContextPanel(state)}
      ${renderSystemStatus(state)}
    </div>`;
}
