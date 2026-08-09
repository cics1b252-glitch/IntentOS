import { escapeHTML } from "../../ids/cognitive/shared.js";

export const NAV_ITEMS = Object.freeze([
  { route: "home", label: "Home", symbol: "⌂" },
  { route: "missions", label: "Missions", symbol: "◎" },
  { route: "knowledge", label: "Knowledge", symbol: "◇", future: true },
  { route: "atlas", label: "Atlas", symbol: "△", future: true },
  { route: "oem-studio", label: "OEM Studio", symbol: "□", future: true },
  { route: "settings", label: "Settings", symbol: "⚙" },
]);

export function renderNavigation(state) {
  const expanded = state.panels.navigationExpanded;
  const links = NAV_ITEMS.map((item) => {
    const current = state.route === item.route;
    const disabled = item.future ? ' aria-disabled="true" data-future="true"' : "";
    return `<a href="#/${escapeHTML(item.route)}" data-route="${escapeHTML(item.route)}"${disabled}${current ? ' aria-current="page"' : ""} title="${escapeHTML(item.label)}">
      <span aria-hidden="true">${escapeHTML(item.symbol)}</span>
      <span class="shell-nav__label">${escapeHTML(item.label)}</span>
    </a>`;
  }).join("");
  return `<nav class="shell-nav" aria-label="Global navigation" data-expanded="${expanded}">
    <div class="shell-brand" aria-label="Intent OS"><span aria-hidden="true">●</span><strong>Intent</strong></div>
    <button type="button" data-shell-action="toggle-navigation" aria-expanded="${expanded}" aria-label="${expanded ? "Collapse" : "Expand"} navigation">☰</button>
    <div class="shell-nav__items">${links}</div>
  </nav>`;
}
