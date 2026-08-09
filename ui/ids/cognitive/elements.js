import { cognitiveCatalog } from "./renderers.js";

const HTMLElementBase = globalThis.HTMLElement ?? class {};

export function parsePresentationData(value) {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

export function toggleDisclosure(trigger) {
  const container = trigger?.nextElementSibling;
  if (!container) return false;
  const expanded = trigger.getAttribute("aria-expanded") === "true";
  trigger.setAttribute("aria-expanded", String(!expanded));
  container.hidden = expanded;
  return !expanded;
}

export function isActivationKey(key) {
  return key === "Enter" || key === " ";
}

class IDSCognitiveElement extends HTMLElementBase {
  #data = {};
  #onClick = (event) => {
    const disclosure = event.target.closest?.("[data-expand]");
    if (disclosure) toggleDisclosure(disclosure);
    const action = event.target.closest?.("[data-action]")?.dataset.action;
    if (action) this.dispatchEvent(new CustomEvent("ids-action", {
      bubbles: true, detail: { action, data: this.#data },
    }));
  };
  #onKeydown = (event) => {
    const contract = cognitiveCatalog[this.localName];
    if (!contract?.interactive || !isActivationKey(event.key)
      || event.target.closest?.("button, summary, a, input, select, textarea")) return;
    event.preventDefault();
    this.dispatchEvent(new CustomEvent("ids-select", {
      bubbles: true, detail: { data: this.#data },
    }));
  };

  connectedCallback() {
    if (this.hasAttribute("data-json")) {
      this.#data = parsePresentationData(this.getAttribute("data-json"));
    }
    this.addEventListener("click", this.#onClick);
    this.addEventListener("keydown", this.#onKeydown);
    this.render();
  }

  disconnectedCallback() {
    this.removeEventListener("click", this.#onClick);
    this.removeEventListener("keydown", this.#onKeydown);
  }

  set data(value) {
    this.#data = value && typeof value === "object" ? value : {};
    if (this.isConnected) this.render();
  }

  get data() {
    return this.#data;
  }

  render() {
    const contract = cognitiveCatalog[this.localName];
    this.innerHTML = contract ? contract.render(this.#data) : "";
  }
}

export function registerCognitiveComponents(registry = globalThis.customElements) {
  if (!registry) return [];
  const registered = [];
  for (const name of Object.keys(cognitiveCatalog)) {
    if (!registry.get(name)) registry.define(name, class extends IDSCognitiveElement {});
    registered.push(name);
  }
  return registered;
}

if (globalThis.customElements) registerCognitiveComponents();
