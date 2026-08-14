# Interface Icon Sources

Stockroom keeps stable semantic icon IDs while using selected artwork from the pinned offline Design Studio catalog. The SVG bodies are embedded in `lib/iconRegistry.ts`; no network fetch occurs at runtime.

| Stockroom ID | Source icon | Bundled source | Upstream artwork version | License |
|---|---|---|---|---|
| `action.external` | `circle-arrow-up-right-filled` | `@iconify-json/tabler` 1.2.38 | Tabler Icons 3.45.0 | MIT |
| `brand.wordmark` | `box-open` | `@fortawesome/free-solid-svg-icons` 7.3.1 | Font Awesome Free 7.3.1 | CC BY 4.0 |
| `nav.about` | `info-rounded` | `@iconify-json/material-symbols` 1.2.88 | Material Symbols | Apache-2.0 |
| `nav.board` | `box` | `@fortawesome/free-solid-svg-icons` 7.3.1 | Font Awesome Free 7.3.1 | CC BY 4.0 |
| `nav.collapse-rail` | `square-rounded-chevron-right-filled` | `@iconify-json/tabler` 1.2.38 | Tabler Icons 3.45.0 | MIT |
| `nav.components` | `book-2-rounded` | `@iconify-json/material-symbols` 1.2.88 | Material Symbols | Apache-2.0 |
| `nav.settings` | `gear-six-fill` | `@iconify-json/ph` 1.2.2 | Phosphor 2.1.1 | MIT |
| `nav.stm` | `microchip` | `@fortawesome/free-solid-svg-icons` 7.3.1 | Font Awesome Free 7.3.1 | CC BY 4.0 |
| `nav.theme` | `moon-fill` | `@iconify-json/ph` 1.2.2 | Phosphor 2.1.1 | MIT |
| `nav.update` | `arrow-big-down-line-filled` | `@iconify-json/tabler` 1.2.38 | Tabler Icons 3.45.0 | MIT |
| `status.cad-missing` | `circle-question` | `@fortawesome/free-solid-svg-icons` 7.3.1 | Font Awesome Free 7.3.1 | CC BY 4.0 |

The exact source packages are pinned by `package-lock.json`. Packaged release bundles also carry `Support/Third Party Notices.txt`, the official Font Awesome Free notice, and a complete Apache-2.0 text. Upstream terms:

- Font Awesome Free: <https://fontawesome.com/license/free>
- Tabler Icons: <https://github.com/tabler/tabler-icons/blob/master/LICENSE>
- Material Symbols: <https://github.com/google/material-design-icons/blob/master/LICENSE>
- Phosphor Icons: <https://github.com/phosphor-icons/core/blob/main/LICENSE>
