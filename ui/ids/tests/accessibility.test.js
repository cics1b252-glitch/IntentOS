import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { validateContrast, validateComponentContract } from "../accessibility/index.js";
import {
  componentCatalog, focusWrapTarget, registerIDSComponents, tabDestination,
} from "../components/index.js";
import { appearanceTokens, semanticTokens } from "../tokens/index.js";
import { renderIcon } from "../icons/index.js";

test("primary text combinations meet WCAG 2.2 AA", () => {
  for (const appearance of Object.values(appearanceTokens)) {
    assert.equal(validateContrast(appearance.text, appearance.background).passes, true);
    assert.equal(validateContrast(appearance.text, appearance.surface).passes, true);
  }
  assert.equal(validateContrast(semanticTokens.error, semanticTokens.errorSurface).passes, true);
  assert.equal(validateContrast(semanticTokens.success, semanticTokens.successSurface).passes, true);
  assert.equal(validateContrast(semanticTokens.warning, semanticTokens.warningSurface).passes, true);
  assert.equal(validateContrast(semanticTokens.info, semanticTokens.infoSurface).passes, true);
});

test("all required reusable components expose valid contracts", () => {
  const required = [
    "button", "icon-button", "card", "panel", "divider", "badge", "chip",
    "tag", "progress", "status-indicator", "toolbar", "search-field",
    "text-field", "select", "checkbox", "radio", "switch", "tooltip",
    "modal", "drawer", "accordion", "tabs", "toast", "spinner",
    "metric-card", "empty-state", "skeleton",
  ].map((name) => `ids-${name}`);
  assert.deepEqual(Object.keys(componentCatalog), required);
  for (const [name, contract] of Object.entries(componentCatalog)) {
    assert.deepEqual(validateComponentContract(name, contract), []);
  }
});

test("showcase contains every required component", async () => {
  const showcase = await readFile(
    new URL("../showcase/index.html", import.meta.url),
    "utf8",
  );
  for (const name of Object.keys(componentCatalog)) {
    assert.match(showcase, new RegExp(`<${name}(?:[ >])`));
  }
});

test("component registration is idempotent and keyboard rules wrap", () => {
  const entries = new Map();
  const registry = {
    get: (name) => entries.get(name),
    define: (name, implementation) => entries.set(name, implementation),
  };
  assert.equal(registerIDSComponents(registry).length, 27);
  assert.equal(registerIDSComponents(registry).length, 27);
  assert.equal(entries.size, 27);
  assert.equal(new Set(entries.values()).size, 27);
  assert.equal(tabDestination(0, "ArrowLeft", 3), 2);
  assert.equal(tabDestination(2, "ArrowRight", 3), 0);
  assert.equal(tabDestination(1, "Home", 3), 0);
  assert.equal(tabDestination(1, "End", 3), 2);
  assert.equal(tabDestination(1, "Enter", 3), 1);
  assert.equal(tabDestination(0, "ArrowRight", 0), -1);
  const first = {};
  const last = {};
  assert.equal(focusWrapTarget(first, first, last, true), last);
  assert.equal(focusWrapTarget(last, first, last, false), first);
  assert.equal(focusWrapTarget(first, first, last, false), null);
});

test("icons have one library, three sizes, two variants and safe labels", () => {
  assert.match(renderIcon("check"), /aria-hidden="true"/);
  assert.match(renderIcon("info", { size: "large", variant: "filled", label: 'Info "safe"' }), /role="img"/);
  assert.match(renderIcon("info", { label: 'Info "safe"' }), /&quot;/);
  assert.throws(() => renderIcon("missing"), /Unknown icon/);
});

test("focus, reduced motion, responsive rules and non-color status are present", async () => {
  const root = new URL("../", import.meta.url);
  const accessibility = await readFile(new URL("accessibility/accessibility.css", root), "utf8");
  const motion = await readFile(new URL("motion/motion.css", root), "utf8");
  const layout = await readFile(new URL("layout/layout.css", root), "utf8");
  const showcase = await readFile(new URL("showcase/index.html", root), "utf8");
  assert.match(accessibility, /:focus-visible/);
  assert.match(accessibility, /forced-colors/);
  assert.match(motion, /prefers-reduced-motion/);
  assert.match(motion, /\[data-ids-motion="reduced"\]/);
  assert.match(layout, /@media \(max-width:/);
  assert.match(showcase, /✓ Success/);
  assert.match(showcase, /⚠ Warning/);
  assert.match(showcase, /× Error/);
});
