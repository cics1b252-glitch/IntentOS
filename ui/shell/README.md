# Intent OS Cognitive Shell

The first executable product presentation host for Intent OS. It is a local,
framework-free demonstration composed from the canonical Intent Design System.

## Run

Serve the repository root with a static HTTP server and open:

`/ui/shell/index.html`

The host contains only local fixtures. It does not connect to the Kernel,
Mission Engine, Providers, PKB or Core Apps and performs no external action.

## Structure

- `state.js`: serializable Shell presentation contract;
- `router.js`: local hash router;
- `fixtures/`: explicitly labelled demonstration data;
- `navigation/`, `mission-rail/`, `workspace/`, `context-panel/`,
  `activity-layer/`, `system-status/`: focused render modules;
- `layout/`: Shell composition and responsive CSS;
- `bootstrap.js`: lifecycle, local interaction and Theme Engine integration.

Home and Missions are complete demonstrations. Knowledge, Atlas and OEM Studio
remain accessible future-workspace placeholders. Settings controls the existing
Theme Engine and its existing persistence.
