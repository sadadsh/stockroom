import { transformAsync, types as t } from "@babel/core";
import path from "node:path";

const SOURCE_MARKER = "/src/";
const GENERATED_ID = /^auto\.[a-z0-9-]+\.[a-z0-9]{7}$/;

function normalized(value) {
  return value.replaceAll("\\", "/");
}

function sourceRelative(filename) {
  const value = normalized(filename.split("?", 1)[0]);
  const marker = value.lastIndexOf(SOURCE_MARKER);
  return marker < 0 ? value : value.slice(marker + SOURCE_MARKER.length);
}

function slug(value) {
  const result = value
    .replace(/([a-z0-9])([A-Z])/g, "$1-$2")
    .replace(/[^A-Za-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase();
  return result || "element";
}

function fnv1a(value) {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(36).padStart(7, "0").slice(-7);
}

export function generatedDesignId(relativeFile, component, tag, line, column) {
  const owner = slug(component);
  const key = `${normalized(relativeFile)}|${component}|${tag}|${line}|${column}`;
  return `auto.${owner}.${fnv1a(key)}`;
}

function componentName(filename) {
  return path.basename(filename).replace(/\.[^.]+$/, "");
}

function attributeNamed(opening, name) {
  return opening.attributes.some(
    (attribute) => t.isJSXAttribute(attribute)
      && t.isJSXIdentifier(attribute.name)
      && attribute.name.name === name,
  );
}

function attributeNode(opening, name) {
  return opening.attributes.find(
    (attribute) => t.isJSXAttribute(attribute)
      && t.isJSXIdentifier(attribute.name)
      && attribute.name.name === name,
  );
}

function insideTechnicalContent(openingPath) {
  if (attributeNamed(openingPath.node, "data-design-technical-content")) return true;
  return Boolean(openingPath.findParent((parent) => (
    parent.isJSXElement()
      && attributeNamed(parent.node.openingElement, "data-design-technical-content")
  )));
}

function insideSvg(openingPath) {
  return Boolean(openingPath.parentPath?.findParent((parent) => (
    parent.isJSXElement()
      && t.isJSXIdentifier(parent.node.openingElement.name)
      && parent.node.openingElement.name.name === "svg"
  )));
}

function shouldTransform(filename) {
  const value = normalized(filename.split("?", 1)[0]);
  return (
    /\.[jt]sx$/.test(value)
    && value.includes(SOURCE_MARKER)
    && !/\.(?:test|spec)\.[jt]sx$/.test(value)
    && !value.includes("/components/design-mode/")
    && !value.endsWith("/components/DevInspector.tsx")
  );
}

export async function transformStockroomJsx(code, filename) {
  if (!shouldTransform(filename)) return null;
  const relativeFile = sourceRelative(filename);
  const owner = componentName(filename);
  let changed = false;
  const result = await transformAsync(code, {
    ast: false,
    babelrc: false,
    code: true,
    configFile: false,
    filename,
    parserOpts: {
      plugins: ["typescript", "jsx"],
      sourceType: "module",
    },
    plugins: [
      () => ({
        visitor: {
          JSXOpeningElement(openingPath) {
            const opening = openingPath.node;
            if (
              !t.isJSXIdentifier(opening.name)
              || opening.name.name === "Fragment"
              || insideTechnicalContent(openingPath)
              || insideSvg(openingPath)
              || !opening.loc
            ) {
              return;
            }
            const key = attributeNode(opening, "key");
            if (key && !attributeNamed(opening, "data-design-key")) {
              opening.attributes.push(t.jsxAttribute(
                t.jsxIdentifier("data-design-key"),
                t.cloneNode(key.value, true),
              ));
              changed = true;
            }
            if (attributeNamed(opening, "data-dev-id") || attributeNamed(opening, "data-design-id")) {
              return;
            }
            const id = generatedDesignId(
              relativeFile,
              owner,
              opening.name.name,
              opening.loc.start.line,
              opening.loc.start.column,
            );
            const identity = t.jsxAttribute(t.jsxIdentifier("data-design-id"), t.stringLiteral(id));
            const firstSpread = opening.attributes.findIndex((attribute) => t.isJSXSpreadAttribute(attribute));
            // A reusable primitive's own generated identity is only its fallback. Put it before
            // forwarded props so the generated identity from the exact call site remains the host
            // element's authority after the primitive spreads those props.
            if (firstSpread === -1) opening.attributes.push(identity);
            else opening.attributes.splice(firstSpread, 0, identity);
            changed = true;
          },
        },
      }),
    ],
    sourceMaps: false,
  });
  if (!changed || !result?.code) return null;
  return result.code;
}

export function stockroomDesignIdentityPlugin() {
  return {
    name: "stockroom-design-identity",
    enforce: "pre",
    async transform(code, id) {
      const transformed = await transformStockroomJsx(code, id);
      return transformed === null ? null : { code: transformed, map: null };
    },
  };
}

export function isGeneratedDesignId(value) {
  return GENERATED_ID.test(value);
}
