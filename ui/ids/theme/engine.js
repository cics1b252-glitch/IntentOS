import { normalizeTheme, resolveTokens } from "./resolver.js";

export const THEME_STORAGE_KEY = "intent.ids.theme.v1";

export class ThemeEngine {
  constructor({ root, storage, matchMedia } = {}) {
    this.root = root ?? globalThis.document?.documentElement ?? null;
    this.storage = storage ?? globalThis.localStorage ?? null;
    this.matchMedia = matchMedia ?? globalThis.matchMedia?.bind(globalThis) ?? (() => ({ matches: false }));
    this.preference = {};
    this.appearanceMedia = this.matchMedia("(prefers-color-scheme: dark)");
    this.motionMedia = this.matchMedia("(prefers-reduced-motion: reduce)");
    this.mediaListener = () => this.apply();
    this.watching = false;
  }

  load() {
    let stored = {};
    try {
      stored = JSON.parse(this.storage?.getItem(THEME_STORAGE_KEY) ?? "{}");
    } catch {
      stored = {};
    }
    this.preference = stored;
    this.watch();
    return this.apply(stored);
  }

  set(patch) {
    const environment = this.environment();
    const next = normalizeTheme({ ...this.preference, ...patch }, environment);
    this.preference = {
      appearance: next.appearance,
      ambient: next.ambient,
      density: next.density,
      motion: patch.motion ?? this.preference.motion ?? "full",
    };
    this.storage?.setItem(THEME_STORAGE_KEY, JSON.stringify(this.preference));
    return this.apply(this.preference);
  }

  environment() {
    return {
      dark: this.appearanceMedia.matches,
      reducedMotion: this.motionMedia.matches,
    };
  }

  watch() {
    if (this.watching) return;
    this.appearanceMedia.addEventListener?.("change", this.mediaListener);
    this.motionMedia.addEventListener?.("change", this.mediaListener);
    this.watching = true;
  }

  dispose() {
    if (!this.watching) return;
    this.appearanceMedia.removeEventListener?.("change", this.mediaListener);
    this.motionMedia.removeEventListener?.("change", this.mediaListener);
    this.watching = false;
  }

  apply(preference = this.preference) {
    const resolved = resolveTokens(preference, this.environment());
    if (!this.root) return resolved;
    for (const [name, value] of Object.entries(resolved.cssVariables)) {
      this.root.style.setProperty(name, value);
    }
    for (const [axis, value] of Object.entries(resolved.theme)) {
      this.root.dataset[`ids${axis[0].toUpperCase()}${axis.slice(1)}`] = value;
    }
    this.root.style.colorScheme = resolved.theme.resolvedAppearance;
    return resolved;
  }
}
