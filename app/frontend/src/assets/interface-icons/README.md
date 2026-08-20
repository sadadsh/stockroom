# Interface Icon Source

Shipped Stockroom interface and component-category defaults use Tabler Outline from the pinned
`@tabler/icons` 3.46.0 package under the MIT license. Every default has a `0 0 24 24` view box,
2 px stroke, and round caps and joins. `lib/tablerIconSources.ts` is the exact semantic-ID-to-source
map; `lib/iconRegistry.ts` is the runtime registry. Raw SVG imports are compiled into the application,
so Stockroom never fetches icon artwork at runtime.

The only shipped-family exceptions are Stockroom technical CAD artwork (`art.*`) and the LinkedIn and
GitHub brand marks. Selection and strong-status fills are runtime treatments, not alternate default
assets.

Design Studio's offline icon catalogue remains deliberately broader. It may preview and save an
explicit override from the installed Font Awesome, Lucide, Material Symbols, Phosphor, Simple Icons,
or Tabler catalogues without changing the curated shipped defaults.

Upstream Tabler terms: <https://github.com/tabler/tabler-icons/blob/master/LICENSE>
