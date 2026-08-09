export const iconCatalog = Object.freeze({
  check: '<path d="m5 12 4 4L19 6"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m16 16 4 4"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  warning: '<path d="M12 3 2.5 20h19L12 3Z"/><path d="M12 9v5M12 17h.01"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  chevronDown: '<path d="m7 10 5 5 5-5"/>',
  arrowRight: '<path d="M5 12h14M14 7l5 5-5 5"/>',
});

export const ICON_SIZES = Object.freeze({ small: 16, medium: 20, large: 24 });

export function renderIcon(name, {
  variant = "outlined", size = "medium", label = "",
} = {}) {
  if (!(name in iconCatalog)) throw new TypeError(`Unknown icon: ${name}`);
  if (!(size in ICON_SIZES)) throw new TypeError(`Unknown icon size: ${size}`);
  if (!["outlined", "filled"].includes(variant)) throw new TypeError(`Unknown icon variant: ${variant}`);
  const pixels = ICON_SIZES[size];
  const accessible = label
    ? `role="img" aria-label="${escapeAttribute(label)}"`
    : 'aria-hidden="true"';
  const paint = variant === "filled"
    ? 'fill="currentColor" stroke="none"'
    : 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
  return `<svg ${accessible} width="${pixels}" height="${pixels}" viewBox="0 0 24 24" ${paint}>${iconCatalog[name]}</svg>`;
}

const escapeAttribute = (value) => String(value)
  .replaceAll("&", "&amp;").replaceAll('"', "&quot;")
  .replaceAll("<", "&lt;").replaceAll(">", "&gt;");
