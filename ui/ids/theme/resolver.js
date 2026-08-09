import {
  AMBIENTS, APPEARANCES, DENSITIES, MOTIONS, ambientTokens,
  appearanceTokens, componentTokens, dataVisualizationTokens,
  primitives, semanticTokens,
} from "../tokens/index.js";

const ensure = (value, allowed, axis) => {
  if (!allowed.includes(value)) throw new TypeError(`Invalid ${axis}: ${value}`);
  return value;
};
const cssName = (name) => `--ids-${name
  .replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)
  .replace(/([a-z])(\d+)/g, "$1-$2")}`;

export function normalizeTheme(input = {}, environment = {}) {
  const appearance = ensure(input.appearance ?? "system", APPEARANCES, "appearance");
  return Object.freeze({
    appearance,
    resolvedAppearance: appearance === "system"
      ? (environment.dark ? "dark" : "light")
      : appearance,
    ambient: ensure(input.ambient ?? "neutral", AMBIENTS, "ambient"),
    density: ensure(input.density ?? "comfortable", DENSITIES, "density"),
    motion: environment.reducedMotion
      ? "reduced"
      : ensure(input.motion ?? "full", MOTIONS, "motion"),
  });
}

export function resolveTokens(input = {}, environment = {}) {
  const theme = normalizeTheme(input, environment);
  const appearance = appearanceTokens[theme.resolvedAppearance];
  const ambient = ambientTokens[theme.ambient];
  const compact = theme.density === "compact";
  const reduced = theme.motion === "reduced";
  const resolved = {
    colorBackground: appearance.background,
    colorSurface: appearance.surface,
    colorSurfaceRaised: appearance.surfaceRaised,
    colorText: appearance.text,
    colorTextMuted: appearance.textMuted,
    colorBorder: appearance.border,
    colorBorderStrong: appearance.borderStrong,
    colorOverlay: primitives.colors.overlay,
    colorTransparent: primitives.colors.transparent,
    colorIdentity: ambient.identity,
    colorAmbient: theme.resolvedAppearance === "dark" ? appearance.surface : ambient.ambient,
    colorAction: ambient.identity,
    colorFocus: ambient.identity,
    colorSuccess: semanticTokens.success,
    colorSuccessSurface: semanticTokens.successSurface,
    colorWarning: semanticTokens.warning,
    colorWarningSurface: semanticTokens.warningSurface,
    colorError: semanticTokens.error,
    colorErrorSurface: semanticTokens.errorSurface,
    colorInfo: semanticTokens.info,
    colorInfoSurface: semanticTokens.infoSurface,
    colorData1: dataVisualizationTokens.series1,
    colorData2: dataVisualizationTokens.series2,
    colorData3: dataVisualizationTokens.series3,
    colorData4: dataVisualizationTokens.series4,
    colorData5: dataVisualizationTokens.series5,
    space0: primitives.spacing[0],
    space1: primitives.spacing[1], space2: primitives.spacing[2],
    space3: primitives.spacing[3], space4: primitives.spacing[4],
    space5: primitives.spacing[5], space6: primitives.spacing[6],
    space8: primitives.spacing[8], space12: primitives.spacing[12],
    radiusSm: primitives.radius.sm, radiusMd: primitives.radius.md,
    radiusLg: primitives.radius.lg, radiusPill: primitives.radius.pill,
    radiusNone: primitives.radius.none,
    borderThin: primitives.border.thin, borderStrong: primitives.border.strong,
    opacityDisabled: primitives.opacity.disabled, opacityMuted: primitives.opacity.muted,
    shadowSoft: primitives.elevation.soft, shadowRaised: primitives.elevation.raised,
    fontBody: primitives.typography.familyBody, fontCode: primitives.typography.familyCode,
    fontSizeCaption: primitives.typography.sizeCaption,
    fontSizeLabel: primitives.typography.sizeLabel,
    fontSizeBody: primitives.typography.sizeBody,
    fontSizeTitle: primitives.typography.sizeTitle,
    fontSizeHeading: primitives.typography.sizeHeading,
    fontSizeDisplay: primitives.typography.sizeDisplay,
    fontWeightRegular: primitives.typography.weightRegular,
    fontWeightMedium: primitives.typography.weightMedium,
    fontWeightBold: primitives.typography.weightBold,
    lineHeightTight: primitives.typography.leadingTight,
    lineHeightBody: primitives.typography.leadingBody,
    letterSpacingLabel: primitives.typography.trackingLabel,
    controlHeight: compact ? componentTokens.controlHeightCompact : componentTokens.controlHeightComfortable,
    controlPadding: compact ? componentTokens.controlPaddingCompact : componentTokens.controlPaddingComfortable,
    panelPadding: compact ? componentTokens.panelPaddingCompact : componentTokens.panelPaddingComfortable,
    focusWidth: componentTokens.focusWidth, focusOffset: componentTokens.focusOffset,
    motionFast: reduced ? primitives.duration.instant : primitives.duration.fast,
    motionNormal: reduced ? primitives.duration.instant : primitives.duration.normal,
    motionSlow: reduced ? primitives.duration.instant : primitives.duration.slow,
    easingStandard: primitives.easing.standard,
    zRaised: primitives.zIndex.raised, zOverlay: primitives.zIndex.overlay,
    zModal: primitives.zIndex.modal, zToast: primitives.zIndex.toast,
    contentSm: primitives.layout.contentSm, contentMd: primitives.layout.contentMd,
    contentLg: primitives.layout.contentLg, gridColumns: primitives.layout.columns,
    gridGutter: primitives.layout.gutter, touchTarget: primitives.layout.touchTarget,
  };
  return Object.freeze({
    theme,
    values: Object.freeze(resolved),
    cssVariables: Object.freeze(Object.fromEntries(
      Object.entries(resolved).map(([key, value]) => [cssName(key), value]),
    )),
  });
}

export function serializeCssVariables(variables) {
  return Object.entries(variables)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([name, value]) => `${name}: ${value};`)
    .join("\n");
}
