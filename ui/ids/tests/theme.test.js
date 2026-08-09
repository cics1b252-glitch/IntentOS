import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { ThemeEngine, THEME_STORAGE_KEY } from "../theme/engine.js";
import { normalizeTheme, resolveTokens, serializeCssVariables } from "../theme/resolver.js";
import {
  AMBIENTS, APPEARANCES, DENSITIES, MOTIONS, tokenCatalog,
} from "../tokens/index.js";

test("all theme axes resolve independently and deterministically", () => {
  let combinations = 0;
  for (const appearance of APPEARANCES) for (const ambient of AMBIENTS) {
    for (const density of DENSITIES) for (const motion of MOTIONS) {
      const input = { appearance, ambient, density, motion };
      assert.deepEqual(resolveTokens(input, { dark: false }), resolveTokens(input, { dark: false }));
      combinations += 1;
    }
  }
  assert.equal(combinations, 60);
});

test("the executable token catalog exposes every required category", () => {
  const required = [
    "primitives", "semantic", "component", "motion", "typography",
    "elevation", "spacing", "radius", "borders", "opacity",
    "transitions", "zIndex", "dataVisualization",
  ];
  for (const category of required) assert.ok(category in tokenCatalog);
});

test("system appearance and reduced-motion preference are respected", () => {
  assert.equal(normalizeTheme({ appearance: "system" }, { dark: true }).resolvedAppearance, "dark");
  assert.equal(normalizeTheme({ motion: "full" }, { reducedMotion: true }).motion, "reduced");
  assert.equal(resolveTokens({ motion: "reduced" }).values.motionNormal, "0ms");
});

test("invalid axes fail explicitly", () => {
  assert.throws(() => resolveTokens({ ambient: "random" }), /Invalid ambient/);
  assert.throws(() => resolveTokens({ density: "tiny" }), /Invalid density/);
});

test("CSS serialization is stable", () => {
  const variables = resolveTokens({ appearance: "light" }).cssVariables;
  assert.equal(serializeCssVariables(variables), serializeCssVariables(variables));
  assert.match(serializeCssVariables(variables), /--ids-color-background:/);
});

test("ThemeEngine persists, restores and applies only presentation state", () => {
  const values = new Map();
  const styleValues = new Map();
  const root = {
    style: {
      colorScheme: "",
      setProperty: (name, value) => styleValues.set(name, value),
    },
    dataset: {},
  };
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
  const matchMedia = (query) => ({ matches: query.includes("dark") });
  const engine = new ThemeEngine({ root, storage, matchMedia });
  engine.set({ appearance: "system", ambient: "steel", density: "compact" });

  assert.equal(JSON.parse(values.get(THEME_STORAGE_KEY)).ambient, "steel");
  assert.equal(root.dataset.idsResolvedAppearance, "dark");
  assert.equal(root.dataset.idsDensity, "compact");
  assert.ok(styleValues.has("--ids-color-background"));

  const restored = new ThemeEngine({ root, storage, matchMedia }).load();
  assert.equal(restored.theme.ambient, "steel");
});

test("ThemeEngine survives unavailable or invalid storage", () => {
  const engine = new ThemeEngine({
    root: null,
    storage: { getItem: () => "{invalid", setItem: () => {} },
  });
  assert.equal(engine.load().theme.ambient, "neutral");
});

test("ThemeEngine observes system preference changes and disposes cleanly", () => {
  const listeners = new Map();
  const queries = new Map();
  const matchMedia = (query) => {
    if (!queries.has(query)) {
      const state = {
        matches: false,
        addEventListener: (_, listener) => listeners.set(query, listener),
        removeEventListener: () => listeners.delete(query),
      };
      queries.set(query, state);
    }
    return queries.get(query);
  };
  const root = {
    style: { setProperty: () => {}, colorScheme: "" },
    dataset: {},
  };
  const engine = new ThemeEngine({ root, matchMedia });
  engine.load();
  const darkQuery = "(prefers-color-scheme: dark)";
  queries.get(darkQuery).matches = true;
  listeners.get(darkQuery)();
  assert.equal(root.dataset.idsResolvedAppearance, "dark");
  engine.dispose();
  assert.equal(listeners.size, 0);
});

test("component CSS contains no literal color values", async () => {
  const css = await readFile(new URL("../components/components.css", import.meta.url), "utf8");
  assert.doesNotMatch(css, /#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
});

test("every IDS CSS variable reference resolves", async () => {
  const files = [
    "../styles/base.css", "../typography/typography.css",
    "../layout/layout.css", "../motion/motion.css",
    "../accessibility/accessibility.css", "../components/components.css",
    "../showcase/showcase.css",
  ];
  const css = (await Promise.all(files.map((file) => readFile(
    new URL(file, import.meta.url), "utf8",
  )))).join("\n");
  const references = new Set(
    [...css.matchAll(/var\((--ids-[\w-]+)/g)].map((match) => match[1]),
  );
  const variables = resolveTokens().cssVariables;
  assert.deepEqual(
    [...references].filter((name) => !(name in variables)),
    [],
  );
});
