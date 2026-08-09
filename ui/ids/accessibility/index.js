export function relativeLuminance(hex) {
  const channels = hex.match(/[a-f\d]{2}/gi);
  if (!channels || channels.length !== 3) throw new TypeError(`Invalid color: ${hex}`);
  const linear = channels.map((part) => {
    const value = Number.parseInt(part, 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

export function contrastRatio(foreground, background) {
  const lighter = Math.max(relativeLuminance(foreground), relativeLuminance(background));
  const darker = Math.min(relativeLuminance(foreground), relativeLuminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

export function validateContrast(foreground, background, {
  largeText = false, nonText = false,
} = {}) {
  const ratio = contrastRatio(foreground, background);
  const required = nonText || largeText ? 3 : 4.5;
  return Object.freeze({ ratio, required, passes: ratio >= required });
}

export function validateComponentContract(name, contract) {
  const issues = [];
  if (!name.startsWith("ids-")) issues.push("Component name must use ids- prefix");
  if (contract.accessibleName && contract.role === "presentation") {
    issues.push("Presentational component cannot require an accessible name");
  }
  return issues;
}
