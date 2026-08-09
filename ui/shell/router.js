import { SHELL_ROUTES } from "./state.js";

export function normalizeRoute(value) {
  const route = String(value ?? "").replace(/^#\/?/, "");
  return SHELL_ROUTES.includes(route) ? route : "home";
}

export function createLocalRouter({ location = globalThis.location, eventTarget = globalThis } = {}) {
  const listeners = new Set();
  const onHashChange = () => {
    const current = normalizeRoute(location?.hash);
    for (const listener of listeners) listener(current);
  };
  eventTarget?.addEventListener?.("hashchange", onHashChange);
  return {
    current: () => normalizeRoute(location?.hash),
    navigate(value) {
      const next = normalizeRoute(value);
      if (location) location.hash = `#/${next}`;
      for (const listener of listeners) listener(next);
      return next;
    },
    subscribe(listener) {
      if (typeof listener !== "function") return () => {};
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    dispose() {
      listeners.clear();
      eventTarget?.removeEventListener?.("hashchange", onHashChange);
    },
  };
}
