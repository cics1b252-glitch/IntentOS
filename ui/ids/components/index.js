const HTMLElementBase = globalThis.HTMLElement ?? class {};

export const componentCatalog = Object.freeze({
  "ids-button": { role: null, keyboard: true },
  "ids-icon-button": { role: null, keyboard: true, accessibleName: true },
  "ids-card": { role: "group" },
  "ids-panel": { role: "region", accessibleName: true },
  "ids-divider": { role: "separator" },
  "ids-badge": { role: "status" },
  "ids-chip": { role: "status" },
  "ids-tag": { role: "status" },
  "ids-progress": { role: null, accessibleName: true },
  "ids-status-indicator": { role: "status" },
  "ids-toolbar": { role: "toolbar", accessibleName: true },
  "ids-search-field": { role: "search" },
  "ids-text-field": { role: null },
  "ids-select": { role: null },
  "ids-checkbox": { role: null },
  "ids-radio": { role: null },
  "ids-switch": { role: null },
  "ids-tooltip": { role: null },
  "ids-modal": { role: null, focusTrap: true },
  "ids-drawer": { role: null, focusTrap: true },
  "ids-accordion": { role: null, keyboard: true },
  "ids-tabs": { role: null, keyboard: true },
  "ids-toast": { role: "status" },
  "ids-spinner": { role: "status", accessibleName: true },
  "ids-metric-card": { role: "group", accessibleName: true },
  "ids-empty-state": { role: "status" },
  "ids-skeleton": { role: "status", accessibleName: true },
});

const setIfMissing = (element, name, value) => {
  if (!element.hasAttribute(name)) element.setAttribute(name, value);
};

export function tabDestination(current, key, count) {
  if (count < 1) return -1;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  if (key === "ArrowRight") return (current + 1) % count;
  if (key === "ArrowLeft") return (current - 1 + count) % count;
  return current;
}

export function focusWrapTarget(active, first, last, shiftKey) {
  if (shiftKey && active === first) return last;
  if (!shiftKey && active === last) return first;
  return null;
}

class IDSBaseElement extends HTMLElementBase {
  connectedCallback() {
    const contract = componentCatalog[this.localName];
    if (contract?.role) setIfMissing(this, "role", contract.role);
    if (contract?.accessibleName && !this.getAttribute("aria-label")
      && !this.getAttribute("aria-labelledby")) {
      this.setAttribute("aria-label", this.getAttribute("label") ?? this.localName.replace("ids-", ""));
    }
  }
}

class IDSButton extends IDSBaseElement {
  connectedCallback() {
    super.connectedCallback();
    if (!this.querySelector("button")) {
      const button = document.createElement("button");
      button.type = this.getAttribute("type") ?? "button";
      while (this.firstChild) button.append(this.firstChild);
      this.append(button);
    }
  }
}

class IDSIconButton extends IDSButton {
  connectedCallback() {
    super.connectedCallback();
    const button = this.querySelector("button");
    setIfMissing(button, "aria-label", this.getAttribute("label") ?? "Action");
  }
}

class IDSProgress extends IDSBaseElement {
  connectedCallback() {
    super.connectedCallback();
    if (!this.querySelector("progress")) {
      const progress = document.createElement("progress");
      progress.max = Number(this.getAttribute("max") ?? 100);
      progress.value = Number(this.getAttribute("value") ?? 0);
      progress.setAttribute("aria-label", this.getAttribute("label") ?? "Progress");
      this.append(progress);
    }
  }
}

class IDSField extends IDSBaseElement {
  connectedCallback() {
    super.connectedCallback();
    const control = this.querySelector("input, select, textarea");
    if (!control || control.closest("label")) return;
    const label = document.createElement("label");
    const text = document.createElement("span");
    const labelText = this.getAttribute("label") ?? "Field";
    text.textContent = labelText;
    setIfMissing(control, "aria-label", labelText);
    control.before(label);
    label.append(text, control);
  }
}

class IDSOverlay extends IDSBaseElement {
  connectedCallback() {
    super.connectedCallback();
    const dialog = this.querySelector('[role="dialog"]');
    if (dialog) {
      setIfMissing(dialog, "aria-modal", "true");
      if (!dialog.hasAttribute("aria-label") && !dialog.hasAttribute("aria-labelledby")) {
        dialog.setAttribute("aria-label", this.getAttribute("label") ?? "Dialog");
      }
    }
    this.addEventListener("keydown", (event) => {
      if (event.key === "Escape") this.close();
      if (event.key === "Tab") this.#containFocus(event);
    });
  }
  open() {
    this.hidden = false;
    this.querySelector("button, input, select, textarea, [tabindex]")?.focus();
  }
  close() { this.hidden = true; }
  #containFocus(event) {
    const items = [...this.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )];
    if (items.length === 0) return;
    const first = items[0];
    const last = items.at(-1);
    const target = focusWrapTarget(
      document.activeElement, first, last, event.shiftKey,
    );
    if (target) { event.preventDefault(); target.focus(); }
  }
}

class IDSTabs extends IDSBaseElement {
  connectedCallback() {
    super.connectedCallback();
    const tabs = [...this.querySelectorAll('[role="tab"]')];
    tabs.forEach((tab, index) => {
      tab.tabIndex = tab.getAttribute("aria-selected") === "true" ? 0 : -1;
      tab.addEventListener("click", () => this.select(index));
      tab.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const next = tabDestination(index, event.key, tabs.length);
        this.select(next); tabs[next].focus();
      });
    });
  }
  select(index) {
    const tabs = [...this.querySelectorAll('[role="tab"]')];
    tabs.forEach((tab, current) => {
      const selected = current === index;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      const panel = this.querySelector(`#${tab.getAttribute("aria-controls")}`);
      if (panel) panel.hidden = !selected;
    });
  }
}

const simple = class extends IDSBaseElement {};
const definitions = {
  "ids-button": IDSButton, "ids-icon-button": IDSIconButton,
  "ids-progress": IDSProgress, "ids-search-field": IDSField,
  "ids-text-field": IDSField, "ids-select": IDSField,
  "ids-modal": IDSOverlay, "ids-drawer": IDSOverlay, "ids-tabs": IDSTabs,
};

export function registerIDSComponents(registry = globalThis.customElements) {
  if (!registry) return [];
  const registered = [];
  for (const name of Object.keys(componentCatalog)) {
    if (!registry.get(name)) {
      const Base = definitions[name] ?? simple;
      registry.define(name, class extends Base {});
    }
    registered.push(name);
  }
  return registered;
}

if (globalThis.customElements) registerIDSComponents();
