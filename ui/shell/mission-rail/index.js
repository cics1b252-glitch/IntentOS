import { escapeHTML } from "../../ids/cognitive/shared.js";

const dataAttribute = (value) => escapeHTML(JSON.stringify(value));

export function groupMissions(missions) {
  return missions.reduce((groups, mission) => {
    const group = ["completed", "failed", "cancelled"].includes(mission.status)
      ? "Recent" : "Active";
    groups[group].push(mission);
    return groups;
  }, { Active: [], Recent: [] });
}

export function renderMissionRail(state) {
  const groups = groupMissions(state.missions);
  const contents = Object.entries(groups).map(([name, missions]) => missions.length
    ? `<section aria-labelledby="mission-group-${name.toLowerCase()}"><h3 id="mission-group-${name.toLowerCase()}" class="ids-label">${name}</h3>
      <div class="shell-mission-list">${missions.map((mission) => `<ids-mission-card class="shell-mission-choice" data-mission="${escapeHTML(mission.title)}" data-json="${dataAttribute({ ...mission, selected: state.selectedMission === mission.title })}"></ids-mission-card>`).join("")}</div></section>` : "").join("");
  return `<aside id="mission-rail" class="shell-mission-rail" aria-label="Mission rail" data-open="${state.panels.missionRailOpen}">
    <header><div><p class="ids-label">Local demonstration</p><h2 class="ids-title">Missions</h2></div>
      <button type="button" data-shell-action="toggle-missions" aria-expanded="${state.panels.missionRailOpen}" aria-controls="mission-rail">×</button>
    </header>
    ${state.missions.length ? contents : `<ids-empty-state role="status"><h3 class="ids-title">No missions</h3><p>The demonstration list is empty.</p></ids-empty-state>`}
  </aside>`;
}
