# legacy/ - reference source to port, not shippable code

These modules were copied from the old Hardware app (the public `Hardware` repo, `tools/`,
on 2026-07-12) as the **reference source for the reuse-by-extraction plan** in the perfected
direction spec (`docs/superpowers/specs/2026-07-12-perfected-rewrite-direction.md`, section 2.1).

No em dashes anywhere (standing owner rule).

## Rules

- **Reference only. Never imported by the backend and never shipped.** The backend package
  (`app/backend/stockroom/`) imports **zero PyQt** (hard constraint, enforced by a CI gate).
- `LibraryManager.py` and `fp_render.py` import PyQt5. Reuse means **extraction**: lift the pure
  functions into new Qt-free backend modules, verified against the old behavior. Do not import
  these files.
- **Excluded on purpose:** `config.json` (holds real DigiKey OAuth creds; the stockroom repo is
  public), `app_secrets.py` (old secret model; the rewrite uses per-machine config outside the
  repo), and the whole PyQt UI (`tools/ui/`, which the rewrite replaces).

## Port map (what to extract, for which milestone)

| Milestone | Extract from | What |
|---|---|---|
| M4 enrichment | `LibraryManager.py` | `enrich_library`, `enrich_plan`, `enrich_symbol`, the Mouser client (`_mouser_post`/`_mouser_request`/`_parse_mouser_part`, `make_mouser_lookup`, `mouser_lookup_from_config`), rate-limit handling (`note_mouser_rate_limited`, `mouser_reset_seconds_remaining`, `_next_mouser_reset`, `resolve_mouser_key`). Mouser is a **supplement**; the scraper-first path (spec 6.1) is new. |
| M4 BOM | `LibraryManager.py` | the BOM subsystem (~20 functions: `bom_cost_summary`, `bom_from_project`, `bom_from_kicad_schematic`, `consolidated_bom`, `bom_diff`, `bom_procurement_summary`, `bom_lead_time`, `bom_sourcing_risks`, `bom_csv`, `bom_xlsx`, and so on). |
| M7 Projects | the `nd_*` modules (already Qt-free) | `nd_project_health`, `nd_netclass_manager`, `nd_board_setup`, `nd_fab_presets`, `nd_design_presets`, `nd_pcb_profiles`, `nd_project_settings_manager`, `nd_object_conform`, `nd_kicad_checks`, `nd_library_fill`, `nd_git`. Re-point their `import LibraryManager` at the extracted Qt-free modules; route KiCad writes through the M1 span layer. |
| Replace, do not reuse | `fp_render.py` | rendering is replaced by `kicad-cli` SVG plus three.js/GLB; `parse_sexpr` is replaced by the M1 s-expression layer. |
| Later (STM32 bench) | `stm32_authority.py`, `stm32_db.py`, `stm32_pins_tab.py` | out of the Components plus Projects near-term scope. |

`pcb_profiles.json` is the fab/design-preset data the Projects milestone (M7) reads.
