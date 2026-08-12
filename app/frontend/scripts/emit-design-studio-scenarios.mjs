import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { rolldown } from "rolldown";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const entry = path.resolve(frontendRoot, "src", "design-studio", "scenarios", "index.ts");
const output = path.resolve(frontendRoot, "..", "frontend-dist", "design-studio-scenarios.json");

// Rolldown is already the Vite 8 production bundler. Use that exact installed transformer to
// evaluate the TypeScript production registry rather than maintaining a second scenario list.
const bundle = await rolldown({ input: entry });
const generated = await bundle.generate({ format: "esm" });
await bundle.close();
const chunk = generated.output.find((item) => item.type === "chunk" && item.isEntry);
if (!chunk) throw new Error("Design Studio scenario registry did not produce an entry chunk.");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(chunk.code).toString("base64")}`;
const registryModule = await import(moduleUrl);
const scenarioModule = registryModule;
const scenarios = registryModule.bootstrapScenarioRegistry.scenarios.map((scenario) => ({
  id: scenario.id,
  title: scenario.title,
  area: scenario.area,
  group: scenario.group,
  route: scenario.route,
  expectedTargets: [...scenario.expectedTargets],
}));

await mkdir(path.dirname(output), { recursive: true });
await writeFile(
  output,
  `${JSON.stringify({ schemaVersion: 1, scenarios }, null, 2)}\n`,
  "utf8",
);
console.log(`Design Studio browser registry: ${scenarios.length} scenarios -> ${output}`);
