import { describe, expect, it } from "vitest";
import ts from "typescript";
import { ICON_BY_ID } from "./iconRegistry";

const MIGRATED_INTERFACE_FILES = [
  "/src/components/CaptureStatusPill.tsx", "/src/components/ProductPhoto.tsx",
  "/src/components/Finder.tsx", "/src/components/HandoffBand.tsx",
  "/src/components/PartsList.tsx", "/src/components/RescanSection.tsx",
  "/src/components/typographyRoles.tsx", "/src/components/component-workspace/AssetOptions.tsx",
  "/src/components/component-workspace/ProviderBrowserFrame.tsx",
  "/src/components/component-workspace/DatasheetViewer.tsx",
  "/src/components/component-workspace/SpecificationRow.tsx",
  "/src/components/component-workspace/ProviderList.tsx",
  "/src/lib/electricalSymbolLibrary.tsx", "/src/components/stm/FamilyPicker.tsx",
  "/src/components/stm/BenchStepper.tsx", "/src/components/stm/CompatibilityWorkbench.tsx",
  "/src/lib/toast.tsx",
] as const;

const RAW = import.meta.glob("/src/**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const CSS_RAW = import.meta.glob("/src/**/*.css", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

// Approval belongs to the exact renderer/technical component, not every SVG in its file.
const RAW_SVG_BOUNDARIES = new Map<string, number>([
  ["/src/components/DevPanel.tsx:IconTab", 1],
  ["/src/components/Icon.tsx:Icon", 2],
  ["/src/components/component-workspace/FootprintPreview.tsx:FootprintPreview", 1],
  ["/src/components/component-workspace/SymbolPreview.tsx:SymbolPreview", 1],
  ["/src/components/design-mode/IconBrowser.tsx:IconBrowser", 1],
  ["/src/components/projects/ProjectPlacementStage.tsx:PlacementBoardDiagram", 1],
  ["/src/components/stm/CompatUnionMap.tsx:CompatUnionMap", 1],
  ["/src/components/stm/PinoutMap.tsx:PinoutMapView", 1],
  ["/src/components/stm/TargetPackageMap.tsx:TargetPackageMap", 1],
  ["/src/pages/StmViewerPage.tsx:GhostSpecimen", 1],
  ["/src/themes/neutral/icons.tsx:themeIcon", 1],
]);
const ICON_LIKE_CHARACTER = /[\p{So}\p{Sm}\u2190-\u21ff\u2300-\u23ff\u2500-\u25ff\u2700-\u28ff]/u;
const DOCUMENT_MONOGRAM = /^(SCH|PRJ)$/u;

function sourceFile(file: string, contents: string): ts.SourceFile {
  return ts.createSourceFile(file, contents, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
}
function visit(node: ts.Node, callback: (candidate: ts.Node) => void): void {
  callback(node);
  node.forEachChild((child) => visit(child, callback));
}
function enclosingAttribute(node: ts.Node): ts.JsxAttribute | undefined {
  let current: ts.Node | undefined = node.parent;
  while (current) {
    if (ts.isJsxAttribute(current)) return current;
    if (ts.isJsxElement(current) || ts.isJsxSelfClosingElement(current)) return undefined;
    current = current.parent;
  }
  return undefined;
}
function enclosingFunctionName(node: ts.Node): string | undefined {
  let current: ts.Node | undefined = node.parent;
  while (current) {
    if (ts.isFunctionDeclaration(current) && current.name) return current.name.text;
    if ((ts.isArrowFunction(current) || ts.isFunctionExpression(current)) && current.parent &&
        ts.isVariableDeclaration(current.parent) && ts.isIdentifier(current.parent.name)) return current.parent.name.text;
    current = current.parent;
  }
  return undefined;
}
function isRenderedJsxLiteral(node: ts.Node): boolean {
  if (ts.isJsxText(node)) return true;
  let current: ts.Node | undefined = node.parent;
  while (current) {
    if (ts.isJsxAttribute(current) || ts.isJsxExpression(current)) return true;
    if (ts.isSourceFile(current) || ts.isFunctionDeclaration(current)) return false;
    current = current.parent;
  }
  return false;
}

function isKeyboardHint(node: ts.Node): boolean {
  const attribute = enclosingAttribute(node)?.name.getText();
  if (attribute === "keys" || attribute === "aria-keyshortcuts") return true;
  let current: ts.Node | undefined = node.parent;
  while (current) {
    if (ts.isJsxElement(current)) {
      const tag = current.openingElement.tagName.getText();
      if (tag === "kbd" || tag.endsWith("Kbd") || tag.endsWith("KeyHint")) return true;
    }
    current = current.parent;
  }
  return false;
}

function isStandaloneIconLike(value: string): boolean {
  const compact = value.replace(/\s/gu, "");
  if (!compact) return false;
  if (DOCUMENT_MONOGRAM.test(compact)) return true;
  const characters = [...compact];
  return characters.some((character) => character.codePointAt(0)! > 127) &&
    characters.every((character) => ICON_LIKE_CHARACTER.test(character));
}

function rawSvgBoundaryCounts(sources: Record<string, string>): Map<string, number> {
  const counts = new Map<string, number>();
  for (const [file, contents] of Object.entries(sources)) {
    if (file.includes(".test.") || file.includes("/__dom-parity__/")) continue;
    visit(sourceFile(file, contents), (node) => {
      if (!((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && node.tagName.getText() === "svg")) return;
      const boundary = `${file}:${enclosingFunctionName(node) ?? "<module>"}`;
      counts.set(boundary, (counts.get(boundary) ?? 0) + 1);
    });
  }
  return counts;
}

function renderedGlyphOffences(sources: Record<string, string>): string[] {
  const offences: string[] = [];
  for (const [file, contents] of Object.entries(sources)) {
    if (file.includes(".test.")) continue;
    visit(sourceFile(file, contents), (node) => {
      const value = ts.isJsxText(node) ? node.getText().trim() :
        ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) ? node.text.trim() : "";
      if (!isStandaloneIconLike(value) || !isRenderedJsxLiteral(node) || isKeyboardHint(node)) return;
      offences.push(`${file}:${value}`);
    });
  }
  return offences;
}

function cssPseudoIconOffences(sources: Record<string, string>): string[] {
  return Object.entries(sources).flatMap(([file, contents]) =>
    [...contents.matchAll(/content\s*:\s*(["'])(.*?)\1/giu)]
      .filter((match) => isStandaloneIconLike(match[2]))
      .map((match) => `${file}:${match[2]}`));
}

function cssSvgAssetOffences(sources: Record<string, string>): string[] {
  return Object.entries(sources).flatMap(([file, contents]) =>
    [...contents.matchAll(/url\([^)]*(?:\.svg|data:image\/svg\+xml)[^)]*\)/giu)]
      .map((match) => `${file}:${match[0]}`));
}

function containsSvgAssetLiteral(node: ts.Node): boolean {
  let found = false;
  visit(node, (candidate) => {
    if ((ts.isStringLiteral(candidate) || ts.isNoSubstitutionTemplateLiteral(candidate)) &&
        /(?:\.svg(?:\?|$)|data:image\/svg\+xml)/i.test(candidate.text)) found = true;
  });
  return found;
}

function forwardsCallerClassName(node: ts.JsxAttribute): boolean {
  return Boolean(
    node.initializer &&
      ts.isJsxExpression(node.initializer) &&
      node.initializer.expression &&
      ts.isIdentifier(node.initializer.expression) &&
      node.initializer.expression.text === "className",
  );
}

function declaresBoundedIconSize(node: ts.JsxAttribute): boolean {
  if (!node.initializer) return false;
  const source = node.initializer.getText();
  const hasSquareSize = /(?:^|[\s"'`])size-(?:\[[^\]]+\]|[^\s"'`{}]+)/u.test(source);
  const hasHeight = /(?:^|[\s"'`])h-(?:\[[^\]]+\]|[^\s"'`{}]+)/u.test(source);
  const hasWidth = /(?:^|[\s"'`])w-(?:\[[^\]]+\]|[^\s"'`{}]+)/u.test(source);
  return hasSquareSize || (hasHeight && hasWidth);
}

function iconSizingOffences(sources: Record<string, string>): string[] {
  const offences: string[] = [];
  for (const [file, contents] of Object.entries(sources)) {
    if (file.includes(".test.")) continue;
    const parsed = sourceFile(file, contents);
    const iconComponents = new Set(["Icon"]);

    // Named compatibility wrappers are still <Icon> call sites: their caller owns the size when
    // it supplies className. Discover the imported names instead of maintaining a second list.
    visit(parsed, (node) => {
      if (!ts.isImportDeclaration(node) || !ts.isStringLiteral(node.moduleSpecifier)) return;
      if (!/(?:^|\/)icons$/u.test(node.moduleSpecifier.text)) return;
      const bindings = node.importClause?.namedBindings;
      if (!bindings || !ts.isNamedImports(bindings)) return;
      for (const element of bindings.elements) iconComponents.add(element.name.text);
    });

    // A few files keep a tiny local pass-through wrapper. Audit its callers, not the forwarding
    // line, because the shared renderer intentionally lets a caller replace its className.
    visit(parsed, (node) => {
      if (!((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && node.tagName.getText() === "Icon")) return;
      const className = node.attributes.properties.find((property): property is ts.JsxAttribute =>
        ts.isJsxAttribute(property) && property.name.getText() === "className");
      if (!className || !forwardsCallerClassName(className)) return;
      const wrapper = enclosingFunctionName(node);
      if (wrapper) iconComponents.add(wrapper);
    });

    visit(parsed, (node) => {
      if (!(ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node))) return;
      const tag = node.tagName.getText();
      if (!iconComponents.has(tag)) return;
      const className = node.attributes.properties.find((property): property is ts.JsxAttribute =>
        ts.isJsxAttribute(property) && property.name.getText() === "className");
      if (!className || forwardsCallerClassName(className) || declaresBoundedIconSize(className)) return;
      const line = parsed.getLineAndCharacterOfPosition(node.getStart(parsed)).line + 1;
      offences.push(`${file}:${line}:${tag}`);
    });
  }
  return offences;
}

describe("canonical product icon adoption", () => {
  it("keeps every caller-styled interface icon in a bounded box", () => {
    expect(iconSizingOffences({
      "/src/fixture.tsx": `
        import { SearchIcon } from "./components/icons";
        const Local = ({ className }: { className?: string }) => <Icon id="action.add" className={className} />;
        export const Fixture = () => <><Icon id="action.add" className="h-4 w-4 text-t2" /><SearchIcon className="size-4" /><Local className="h-full w-full" /></>;
      `,
    })).toEqual([]);
    expect(iconSizingOffences({
      "/src/fixture.tsx": `
        import { SearchIcon } from "./components/icons";
        export const Fixture = () => <SearchIcon className="flex-none text-t3" />;
      `,
    })).toEqual(["/src/fixture.tsx:3:SearchIcon"]);
    expect(iconSizingOffences(RAW)).toEqual([]);
  });

  it("recognizes unlisted standalone Unicode icon glyphs without policing prose", () => {
    expect(isStandaloneIconLike("◆")).toBe(true);
    expect(isStandaloneIconLike("☰")).toBe(true);
    expect(isStandaloneIconLike("12 × 14 mm")).toBe(false);
    expect(isStandaloneIconLike("Press ← to go back")).toBe(false);
    expect(renderedGlyphOffences({
      "/src/fixture.tsx": "export function Fixture(){return <><span>◆</span><p>12 × 14 mm</p><kbd>⌘</kbd><Thing keys={['⌥']} /></>}",
    })).toEqual(["/src/fixture.tsx:◆"]);
    expect(cssPseudoIconOffences({
      "/src/fixture.css": "a::before{content:'◆'} q::before{content:'“'}",
    })).toEqual(["/src/fixture.css:◆"]);
    expect(cssSvgAssetOffences({
      "/src/fixture.css": ".icon{mask-image:url('./hidden.svg')} .safe{background:url('./photo.png')}",
    })).toEqual(["/src/fixture.css:url('./hidden.svg')"]);
  });

  it("tracks SVG approval by exact node count, not boundary presence", () => {
    expect(rawSvgBoundaryCounts({
      "/src/fixture.tsx": "export function Fixture(){return <><svg/><svg/></>}",
    })).toEqual(new Map([["/src/fixture.tsx:Fixture", 2]]));
  });

  it("keeps raw SVG at exact central-renderer or technical-art nodes", () => {
    expect([...rawSvgBoundaryCounts(RAW)].sort()).toEqual([...RAW_SVG_BOUNDARIES].sort());
  });

  it("keeps rendered font glyphs and document monograms out of production JSX", () => {
    expect(renderedGlyphOffences(RAW)).toEqual([]);
  });

  it("keeps icon glyphs out of CSS pseudo-elements", () => {
    expect(cssPseudoIconOffences(CSS_RAW)).toEqual([]);
    expect(cssSvgAssetOffences(CSS_RAW)).toEqual([]);
  });

  it("centralizes imported and constructed SVG interface assets", () => {
    const offences: string[] = [];
    for (const [file, contents] of Object.entries(RAW)) {
      if (file.includes(".test.")) continue;
      const parsed = sourceFile(file, contents);
      const svgBindings = new Set<string>();
      visit(parsed, (node) => {
        if (ts.isImportDeclaration(node) && /\.svg(?:\?raw)?$/i.test(node.moduleSpecifier.getText().slice(1, -1))) {
          const clause = node.importClause;
          if (clause?.name) svgBindings.add(clause.name.text);
          if (clause?.namedBindings && ts.isNamespaceImport(clause.namedBindings)) svgBindings.add(clause.namedBindings.name.text);
          if (clause?.namedBindings && ts.isNamedImports(clause.namedBindings)) {
            for (const element of clause.namedBindings.elements) svgBindings.add(element.name.text);
          }
        }
        if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer &&
            containsSvgAssetLiteral(node.initializer)) svgBindings.add(node.name.text);
      });
      visit(parsed, (node) => {
        if (ts.isImportDeclaration(node) && /\.svg(?:\?raw)?$/i.test(node.moduleSpecifier.getText().slice(1, -1)) &&
            file !== "/src/lib/tablerIconSources.ts") offences.push(`${file}:svg-import`);
        if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && node.tagName.getText() === "img") {
          const src = node.attributes.properties.find((property): property is ts.JsxAttribute =>
            ts.isJsxAttribute(property) && property.name.getText() === "src");
          if (src?.initializer && ts.isStringLiteral(src.initializer) && /\.svg(?:\?|$)/i.test(src.initializer.text)) {
            offences.push(`${file}:svg-image`);
          } else if (src?.initializer && ts.isJsxExpression(src.initializer) && src.initializer.expression &&
              (containsSvgAssetLiteral(src.initializer.expression) ||
                (ts.isIdentifier(src.initializer.expression) && svgBindings.has(src.initializer.expression.text)))) {
            offences.push(`${file}:svg-image-expression`);
          }
        }
        if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) &&
            ["createElement", "createElementNS"].includes(node.expression.name.text) &&
            node.arguments.some((argument) => ts.isStringLiteral(argument) && argument.text === "svg")) {
          const boundary = `${file}:${enclosingFunctionName(node) ?? "<module>"}`;
          if (boundary !== "/src/lib/applyIconOverrides.ts:syncInsertedIcons") offences.push(`${boundary}:constructed-svg`);
        }
      });
    }
    expect(offences).toEqual([]);
  });

  it("rejects expression-backed SVG images instead of trusting JSX indirection", () => {
    const fixture = sourceFile("/src/fixture.tsx", "const asset = './icon.svg'; export const Fixture=()=> <img src={asset} />");
    const svgBindings = new Set<string>();
    visit(fixture, (node) => {
      if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer &&
          containsSvgAssetLiteral(node.initializer)) svgBindings.add(node.name.text);
    });
    let rejected = false;
    visit(fixture, (node) => {
      if (!(ts.isJsxSelfClosingElement(node) && node.tagName.getText() === "img")) return;
      const src = node.attributes.properties.find((property): property is ts.JsxAttribute =>
        ts.isJsxAttribute(property) && property.name.getText() === "src");
      rejected = Boolean(src?.initializer && ts.isJsxExpression(src.initializer) &&
        src.initializer.expression && ts.isIdentifier(src.initializer.expression) &&
        svgBindings.has(src.initializer.expression.text));
    });
    expect(rejected).toBe(true);
  });

  it("resolves every literal Icon id and audits every dynamic id site", () => {
    const unresolved: string[] = [];
    const dynamicSites: string[] = [];
    for (const [file, contents] of Object.entries(RAW)) {
      if (file.includes(".test.")) continue;
      visit(sourceFile(file, contents), (node) => {
        if (!ts.isJsxSelfClosingElement(node) || node.tagName.getText() !== "Icon") return;
        const id = node.attributes.properties.find((property): property is ts.JsxAttribute =>
          ts.isJsxAttribute(property) && property.name.getText() === "id");
        if (!id?.initializer) return;
        if (ts.isStringLiteral(id.initializer)) {
          if (!ICON_BY_ID.has(id.initializer.text)) unresolved.push(`${file}:${id.initializer.text}`);
        } else if (ts.isJsxExpression(id.initializer) && id.initializer.expression) {
          if (ts.isStringLiteral(id.initializer.expression)) {
            if (!ICON_BY_ID.has(id.initializer.expression.text)) unresolved.push(`${file}:${id.initializer.expression.text}`);
          } else dynamicSites.push(`${file}:${id.initializer.expression.getText()}`);
        }
      });
    }
    expect(unresolved).toEqual([]);
    expect(dynamicSites.sort()).toEqual([
      "/src/components/DevPanel.tsx:open ? \"design.disclosure-open\" : \"design.disclosure-closed\"",
      "/src/components/DevPanel.tsx:pid", "/src/components/Glb3DViewControls.tsx:icon",
      "/src/components/Glb3DViewControls.tsx:item.icon", "/src/components/Glb3DViewControls.tsx:v.icon",
      "/src/components/SearchOverlay.tsx:sort.dir === \"asc\" ? \"action.sort-asc\" : \"action.sort-desc\"",
      "/src/components/component-workspace/ProviderCaptureGuide.tsx:iconId",
      "/src/components/component-workspace/SourcingParts.tsx:icon",
      "/src/components/component-workspace/SourcingSheet.tsx:icon",
      "/src/components/design-mode/ArrangePanel.tsx:open ? \"design.disclosure-open\" : \"design.disclosure-closed\"",
      "/src/components/design-mode/InspectorPanel.tsx:openFacets.includes(item.id) ? \"navigation.chevron-down\" : \"overlay.chevron\"",
      "/src/components/design-mode/IssuesPanel.tsx:open ? \"design.disclosure-open\" : \"design.disclosure-closed\"",
      "/src/components/design-mode/inspectors/IconInspector.tsx:iconId",
      "/src/components/projects/ProjectDesignWorkbench.tsx:`document.${kind}`",
      "/src/lib/electricalSymbolLibrary.tsx:`category.${kind}`", "/src/pages/SettingsPage.tsx:iconId",
    ].sort());
  });

  it("keeps formerly-colliding semantics on distinct registry assets", () => {
    const ids = ["nav.back", "nav.forward", "nav.projects", "nav.cad-assets", "action.external",
      "action.show-provider", "action.download", "action.import-files", "nav.about", "status.info",
      "nav.up-to-date", "status.success", "overlay.close", "status.error"];
    const sources = ids.map((id) => ICON_BY_ID.get(id)?.sourceIcon);
    expect(sources.every(Boolean)).toBe(true);
    expect(new Set(sources).size).toBe(sources.length);
  });

  it("uses a procurement semantic for offer surfaces, not an enrich action", () => {
    for (const file of [
      "/src/components/component-workspace/OffersSection.tsx",
      "/src/components/component-workspace/SourcingSheet.tsx",
    ]) {
      expect(RAW[file]).toContain('"detail.offers"');
      expect(RAW[file]).not.toContain('"action.enrich"');
    }
  });

  for (const file of MIGRATED_INTERFACE_FILES) {
    it(`${file} does not reintroduce raw interface SVG or font control glyphs`, () => {
      const contents = RAW[file];
      expect(contents, `${file} was not included by the source glob`).toBeTypeOf("string");
      expect(contents, `${file} contains a raw svg`).not.toContain("<svg");
      expect(contents, `${file} contains a font-dependent control glyph`).not.toMatch(/[←↻×✓]/u);
    });
  }

  it("reserves the double-check glyph for the explicit theme adapter slot", () => {
    const uses = Object.entries(RAW).filter(([file, contents]) =>
      file !== "/src/lib/iconSystemUniformity.test.ts" && contents.includes('"modal.check"')).map(([file]) => file);
    expect(uses).toEqual(["/src/lib/iconRegistry.ts", "/src/lib/tablerIconSources.ts", "/src/themes/neutral/icons.tsx"]);
  });
});
