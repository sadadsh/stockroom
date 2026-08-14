# Stockroom Electrical Symbol Artwork

The SVG files under `iec/` are copied from the individual-symbol collection in
[ElectricalSymbolLibrary](https://github.com/basverdoes/ElectricalSymbolLibrary) at commit
`ed1c2a3a910969b6de2483249515cce10cfd0a07`.

The upstream project describes these individual symbols as public-domain IEC/ANSI circuit artwork
under the [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/) license. Stockroom
uses the IEC variants. The source paths are `src/symbols/analog-iec/**` except `nullor.svg`, which is
from `src/symbols/other/`.

Additional circuit and device icons come from `@tabler/icons` 3.46.0 under the MIT license.
The category resolver and rendering component live in `lib/electricalSymbolLibrary.tsx`.
