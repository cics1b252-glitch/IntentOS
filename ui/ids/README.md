# Intent Design System — Executable Foundation

Framework-independent presentation infrastructure for Intent OS interfaces.
It contains no Kernel, mission, provider, PKB or Core App dependency.

## Use

```html
<link rel="stylesheet" href="/ui/ids/styles/base.css">
<script type="module">
  import { ThemeEngine, registerIDSComponents } from "/ui/ids/index.js";
  registerIDSComponents();
  new ThemeEngine().load();
</script>
```

Theme axes are independent:

- appearance: `light`, `dark`, `system`;
- ambient: `neutral`, `lavender`, `steel`, `cream`, `atlas`;
- density: `comfortable`, `compact`;
- motion: `full`, `reduced`.

The resolver emits deterministic `--ids-*` CSS variables. Components consume
semantic or component variables and never domain services.

## Cognitive presentation

`cognitive/` contains ten framework-free components for public observable
states. Import `registerCognitiveComponents` from `ui/ids/index.js` and assign
plain serializable data through each element's `data` property. Contracts
provide safe fallbacks and never import application or domain models. See
`docs/design/IDS-006_COGNITIVE_INTERACTION.md` and
`docs/design/IDS-007_COGNITIVE_COMPONENTS.md`.

## Cognitive Shell host

The first product presentation host is available separately in `ui/shell`.
It composes the IDS foundation and cognitive components with local,
serializable demonstration fixtures. The Showcase remains the component
catalog; the Shell is the executable product demonstration. See
`docs/design/IDS-008_COGNITIVE_SHELL.md`.

## Validation

```powershell
node --test ui/ids/tests/*.test.js
node --experimental-test-coverage --test ui/ids/tests/*.test.js
python -m pytest tests/test_ids_executable_foundation.py
```

Open `showcase/index.html` through any static HTTP server to review all
foundation states. The showcase is a validation tool, not product UI.
