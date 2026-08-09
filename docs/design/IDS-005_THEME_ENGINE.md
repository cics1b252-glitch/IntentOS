# IDS-005 — Theme Engine

## 1. Purpose and boundary

The Theme Engine turns the normative IDS documents into deterministic,
framework-independent presentation state. It belongs exclusively to
`ui/ids`. It does not import or know the Kernel, Mission Engine, Constitution,
PKB, Providers or Core Apps, and it never changes application layout or product
behavior.

## 2. Architecture

```text
Explicit preference + operating-system media preferences
                         ↓
                   Theme Engine
                         ↓
Primitives → Semantic → Appearance → Ambient → Component → State
                         ↓
                 resolved --ids-* tokens
                         ↓
       generic components / host presentation adapter
```

The executable package is divided into:

- `tokens`: versioned primitive, semantic, component, data, motion,
  typography, spacing, radius, elevation, border, opacity and z-index values;
- `theme`: validation, normalization, deterministic resolution, persistence
  and application;
- `styles`, `typography`, `layout`, `motion`: platform-neutral CSS foundation;
- `components`: generic Web Components and component styling;
- `icons`: one local icon vocabulary with outlined and filled variants;
- `accessibility`: contrast and contract validation;
- `showcase`: internal validation surface, never product UI;
- `tests`: theme, token, accessibility and architectural tests.

## 3. Independent axes

| Axis | Values | Effect |
|---|---|---|
| Appearance | Light, Dark, System | surface and text luminosity |
| Ambient | Neutral, Lavender, Steel, Cream, Atlas | bounded atmosphere and identity accent |
| Density | Comfortable, Compact | control and panel spacing |
| Motion | Full, Reduced | duration and iteration, never layout |

Axes are validated independently. Invalid values fail explicitly. System
appearance resolves from `prefers-color-scheme`; an operating-system
`prefers-reduced-motion` request always reduces motion.

## 4. Token hierarchy and resolution

1. **Primitives** are immutable raw scales.
2. **Semantic** assigns meaning: surface, text, action, success, warning, error
   and information.
3. **Appearance** selects light or dark semantic surfaces.
4. **Ambient** selects one predefined atmosphere; it never generates colors.
5. **Component** maps semantic values to control dimensions and focus.
6. **State** resolves density, motion and system preferences.
7. **CSS Variables** are emitted with the stable `--ids-*` namespace.

Resolution is pure and deterministic: identical input and environment produce
identical frozen output. Components contain no literal color values.

## 5. Lifecycle

1. Construct `ThemeEngine` with optional root, storage and media-query
   adapters.
2. `load()` reads the stored preference, safely ignores malformed data and
   applies defaults.
3. The resolver evaluates system preferences.
4. CSS variables and descriptive `data-ids-*` attributes are applied to the
   presentation root.
5. `set()` merges one or more axes, validates, persists and reapplies.
6. Media-query listeners reapply tokens when operating-system appearance or
   reduced-motion preferences change; `dispose()` releases those listeners.

The engine changes tokens only. It never inserts, removes or reorders layout.

## 6. Persistence and fallback

- key: `intent.ids.theme.v1`;
- content: explicit axis preferences only;
- default: System / Neutral / Comfortable / Full;
- unavailable storage: the engine remains operational in memory;
- invalid JSON: ignored in favor of defaults;
- missing DOM: the resolver remains usable for server-side generation and
  native adapters.

No personal, mission or product data is stored with the theme.

## 7. Dynamic theme changes

Hosts call `set({ axis: value })`. The engine preserves every unspecified axis,
persists the preference and resolves once. Changes are gradual only when motion
is permitted. Appearance and atmosphere retain the same component semantics and
do not relocate controls.

## 8. Performance

- no runtime dependency or network request;
- immutable, small token maps;
- one pass to resolve values;
- one CSS property assignment per resolved token;
- no dynamic color generation;
- no layout measurement or forced reflow;
- components are registered once through the native Custom Elements registry.

## 9. Accessibility

- WCAG 2.2 AA contrast tests cover primary and semantic text pairs;
- native controls preserve keyboard and assistive-technology behavior;
- focus-visible and forced-colors rules are global;
- modal and drawer provide Escape handling and contained focus;
- Tabs implement arrow, Home and End navigation;
- statuses combine text/symbol with color;
- motion reduction is enforced both by media query and resolved theme state;
- icon-only controls require accessible names;
- disabled states remain programmatically exposed.

Automated validation does not replace manual screen-reader, zoom, touch-target,
high-contrast and visual-regression review on each host platform.

## 10. Platform adoption

Web and Desktop webviews can consume CSS and Web Components directly. Native
hosts can consume the resolver output and map the same stable token names to
native widgets. Future interfaces must depend on this presentation package or a
public adapter, never on the legacy `intent_kernel/ids` package.
