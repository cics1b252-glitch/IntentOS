# Domain Migration Matrix

This matrix is the Sprint 8 source of truth for domain ownership. “Canonical”
means that the official Composition Root resolves the request through a
canonical capability and owner. Compatibility classes may remain loaded, but
they must not be the authority for a migrated route.

| Domain | Canonical capability | Official owner | State | Legacy equivalent | Compatibility path | Evidence |
|---|---|---|---|---|---|---|
| Finance | `finance.intent` | Atlas | migrated | FIN / `FinanceModule` | Atlas delegates internally to FIN to preserve response parity | finance parity and no-fallback tests |
| Research | `knowledge.intent` | Logos | migrated | `CoreModule` provider route | `ModuleRouter` remains only for explicit compatibility calls | visible-output parity and canonical-owner tests |
| Writing | `knowledge.intent` | Logos | migrated | `CoreModule` provider route | same as Research | visible-output parity and canonical-owner tests |
| Planning | `knowledge.intent` | Logos | migrated | `CoreModule` provider route | same as Research | visible-output parity and canonical-owner tests |
| Education | `knowledge.intent` | Logos | migrated | `CoreModule` provider route | same as Research | visible-output parity and canonical-owner tests |
| Engineering | `engineering.intent` | OEM Studio | migrated | `CoreModule` provider route | `ModuleRouter` remains only for explicit compatibility calls | visible-output parity and canonical-owner tests |
| Programming | `engineering.intent` | OEM Studio | partial | `CoreModule` provider route | classifier keyword precedence may classify some programming prompts as Education | owner, provider-failure and unavailable-capability tests |
| Business | — | legacy fallback | legacy active | `CoreModule` | `ModuleRouter` | characterized baseline |
| Marketing | — | legacy fallback | legacy active | `CoreModule` | `ModuleRouter` | characterized baseline |
| Data | — | legacy fallback | legacy active | `CoreModule` | `ModuleRouter` | characterized baseline |
| Creativity | — | legacy fallback | legacy active | `CoreModule` | `ModuleRouter` | characterized baseline |
| Legal | — | legacy fallback | legacy active | `CoreModule` | `ModuleRouter` | characterized baseline |
| Life | — | legacy fallback | legacy active | `CoreModule` | `ModuleRouter` | characterized baseline |
| Other | — | legacy fallback | legacy active | `CoreModule` | `ModuleRouter` | characterized baseline |

## Ownership rules

1. Finance is owned by Atlas.
2. Knowledge-oriented intent is owned by Logos.
3. Engineering and programming intent is owned by OEM Studio.
4. A migrated domain must not execute through `ModuleRouter`.
5. A missing canonical capability or provider returns an explicit canonical
   failure; it must not silently cross into the legacy route.
6. Historical routers, registries and orchestrators remain available only for
   characterized consumers and rollback.

## Current quantitative view

- 7 of 14 domain declarations have a canonical owner (50%).
- 6 are fully reached through the current classifier.
- Programming is canonically owned but remains partially migrated because of
  existing classifier keyword precedence. Sprint 8 deliberately preserves that
  imperfect behavior.
- 7 domains remain explicitly on the legacy fallback.

