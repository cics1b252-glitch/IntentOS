export const SHARED_STATES = Object.freeze({
  success: Object.freeze({ tone: "success", symbol: "✓", label: "Completed" }),
  completed: Object.freeze({ tone: "success", symbol: "✓", label: "Completed" }),
  warning: Object.freeze({ tone: "warning", symbol: "!", label: "Warning" }),
  waiting: Object.freeze({ tone: "info", symbol: "…", label: "Waiting" }),
  information: Object.freeze({ tone: "info", symbol: "i", label: "Information" }),
  error: Object.freeze({ tone: "error", symbol: "×", label: "Error" }),
  failed: Object.freeze({ tone: "error", symbol: "×", label: "Failed" }),
  restricted: Object.freeze({ tone: "warning", symbol: "!", label: "Restricted" }),
  unavailable: Object.freeze({ tone: "neutral", symbol: "–", label: "Unavailable" }),
  disabled: Object.freeze({ tone: "neutral", symbol: "–", label: "Disabled" }),
});

export const statePresentation = (state, fallbackLabel = "Status") => {
  const known = SHARED_STATES[state];
  return known ?? Object.freeze({
    tone: "neutral", symbol: "•", label: fallbackLabel,
  });
};

export const safeText = (value, fallback = "") => (
  typeof value === "string" && value.trim() ? value.trim() : fallback
);
export const safeOptionalText = (value) => safeText(value) || null;
export const safeBoolean = (value) => value === true;
export const safeArray = (value) => Array.isArray(value) ? value : [];
export const safeNumber = (value) => Number.isFinite(value) ? Number(value) : null;
export const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));
export const enumValue = (value, allowed, fallback) => allowed.includes(value) ? value : fallback;
export const isoTime = (value) => {
  if (!value) return null;
  const time = new Date(value);
  return Number.isNaN(time.valueOf()) ? null : time.toISOString();
};

export const escapeHTML = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

export const formatPublicTime = (value, locale = "pt-BR") => {
  const time = isoTime(value);
  if (!time) return "Not informed";
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium", timeStyle: "short",
  }).format(new Date(time));
};

export const toPlainObject = (value) => (
  value && typeof value === "object" && !Array.isArray(value) ? value : {}
);
