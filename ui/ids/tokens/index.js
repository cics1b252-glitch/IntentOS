export const APPEARANCES = Object.freeze(["light", "dark", "system"]);
export const AMBIENTS = Object.freeze([
  "neutral", "lavender", "steel", "cream", "atlas",
]);
export const DENSITIES = Object.freeze(["comfortable", "compact"]);
export const MOTIONS = Object.freeze(["full", "reduced"]);

const freeze = (value) => Object.freeze(value);

export const primitives = freeze({
  colors: freeze({
    white: "#ffffff", ink950: "#14131a", ink900: "#201f28",
    ink700: "#4d4a59", ink500: "#716d7d", ink300: "#aaa6b4",
    ink200: "#cbc7d2", ink100: "#e8e5ec", ink50: "#f7f5f9",
    lavender700: "#51447f", lavender600: "#67569b",
    lavender200: "#d9d0f1", lavender100: "#eee9fa",
    steel700: "#3d566b", steel600: "#526f86",
    steel200: "#c9d8e3", steel100: "#e7eff4",
    cream700: "#765e3c", cream200: "#e8dcc5", cream100: "#f6f0e4",
    atlas700: "#344f5b", atlas600: "#466975",
    atlas200: "#c2d6d9", atlas100: "#e3eeee",
    blue700: "#275e91", blue100: "#e4f1fb",
    green700: "#28613d", green100: "#e5f4e9",
    amber800: "#765400", amber100: "#fff1c7",
    red700: "#9a3535", red100: "#fbe8e8",
    overlay: "rgb(20 19 26 / 0.62)",
    transparent: "transparent",
  }),
  spacing: freeze({
    0: "0", 1: "0.25rem", 2: "0.5rem", 3: "0.75rem",
    4: "1rem", 5: "1.25rem", 6: "1.5rem", 8: "2rem",
    10: "2.5rem", 12: "3rem", 16: "4rem",
  }),
  radius: freeze({
    none: "0", sm: "0.375rem", md: "0.625rem",
    lg: "0.875rem", pill: "999rem",
  }),
  border: freeze({ thin: "0.0625rem", strong: "0.125rem" }),
  opacity: freeze({ disabled: "0.48", muted: "0.68", overlay: "0.62" }),
  duration: freeze({ instant: "0ms", fast: "120ms", normal: "200ms", slow: "360ms" }),
  easing: freeze({
    standard: "cubic-bezier(0.2, 0, 0, 1)",
    enter: "cubic-bezier(0, 0, 0.2, 1)",
    exit: "cubic-bezier(0.4, 0, 1, 1)",
  }),
  zIndex: freeze({ base: "0", raised: "10", overlay: "100", modal: "200", toast: "300" }),
  typography: freeze({
    familyBody: '"Segoe UI Variable", "Segoe UI", system-ui, sans-serif',
    familyCode: '"Cascadia Code", "SFMono-Regular", Consolas, monospace',
    sizeCaption: "0.75rem", sizeLabel: "0.8125rem", sizeBody: "1rem",
    sizeTitle: "1.25rem", sizeHeading: "1.625rem",
    sizeDisplay: "clamp(2rem, 4vw, 3.25rem)",
    weightRegular: "400", weightMedium: "600", weightBold: "700",
    leadingTight: "1.2", leadingBody: "1.55", trackingLabel: "0.01em",
  }),
  elevation: freeze({
    soft: "0 0.0625rem 0.1875rem rgb(20 19 26 / 0.08)",
    raised: "0 0.75rem 2rem rgb(20 19 26 / 0.14)",
  }),
  layout: freeze({
    contentSm: "40rem", contentMd: "64rem", contentLg: "80rem",
    breakpointSm: "36rem", breakpointMd: "48rem", breakpointLg: "72rem",
    columns: "12", gutter: "1.5rem", touchTarget: "2.75rem",
  }),
});

export const appearanceTokens = freeze({
  light: freeze({
    background: primitives.colors.ink50,
    surface: primitives.colors.white,
    surfaceRaised: primitives.colors.white,
    text: primitives.colors.ink950,
    textMuted: primitives.colors.ink700,
    border: primitives.colors.ink200,
    borderStrong: primitives.colors.ink500,
  }),
  dark: freeze({
    background: primitives.colors.ink950,
    surface: primitives.colors.ink900,
    surfaceRaised: "#2b2934",
    text: primitives.colors.ink50,
    textMuted: primitives.colors.ink300,
    border: "#44414d",
    borderStrong: primitives.colors.ink300,
  }),
});

export const ambientTokens = freeze({
  neutral: freeze({ identity: primitives.colors.lavender600, ambient: primitives.colors.ink100 }),
  lavender: freeze({ identity: primitives.colors.lavender600, ambient: primitives.colors.lavender100 }),
  steel: freeze({ identity: primitives.colors.steel600, ambient: primitives.colors.steel100 }),
  cream: freeze({ identity: primitives.colors.cream700, ambient: primitives.colors.cream100 }),
  atlas: freeze({ identity: primitives.colors.atlas600, ambient: primitives.colors.atlas100 }),
});

export const semanticTokens = freeze({
  success: primitives.colors.green700,
  successSurface: primitives.colors.green100,
  warning: primitives.colors.amber800,
  warningSurface: primitives.colors.amber100,
  error: primitives.colors.red700,
  errorSurface: primitives.colors.red100,
  info: primitives.colors.blue700,
  infoSurface: primitives.colors.blue100,
});

export const componentTokens = freeze({
  controlHeightComfortable: "2.75rem",
  controlHeightCompact: "2.25rem",
  controlPaddingComfortable: primitives.spacing[4],
  controlPaddingCompact: primitives.spacing[3],
  panelPaddingComfortable: primitives.spacing[6],
  panelPaddingCompact: primitives.spacing[4],
  focusWidth: primitives.border.strong,
  focusOffset: primitives.spacing[1],
});

export const motionTokens = freeze({
  duration: primitives.duration,
  easing: primitives.easing,
});
export const typographyTokens = primitives.typography;
export const elevationTokens = primitives.elevation;
export const spacingTokens = primitives.spacing;
export const radiusTokens = primitives.radius;
export const borderTokens = primitives.border;
export const opacityTokens = primitives.opacity;
export const zIndexTokens = primitives.zIndex;
export const transitionTokens = freeze({
  hover: `${primitives.duration.fast} ${primitives.easing.standard}`,
  focus: `${primitives.duration.fast} ${primitives.easing.standard}`,
  expand: `${primitives.duration.normal} ${primitives.easing.enter}`,
  collapse: `${primitives.duration.fast} ${primitives.easing.exit}`,
  loading: `${primitives.duration.slow} ${primitives.easing.standard}`,
});

export const dataVisualizationTokens = freeze({
  series1: primitives.colors.lavender600,
  series2: primitives.colors.steel600,
  series3: primitives.colors.cream700,
  series4: primitives.colors.atlas600,
  series5: primitives.colors.blue700,
});

export const tokenCatalog = freeze({
  primitives, appearance: appearanceTokens, ambient: ambientTokens,
  semantic: semanticTokens, component: componentTokens,
  motion: motionTokens, typography: typographyTokens,
  elevation: elevationTokens, spacing: spacingTokens, radius: radiusTokens,
  borders: borderTokens, opacity: opacityTokens,
  transitions: transitionTokens, zIndex: zIndexTokens,
  dataVisualization: dataVisualizationTokens,
});
