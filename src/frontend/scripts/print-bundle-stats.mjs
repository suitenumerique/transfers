#!/usr/bin/env node
// Reads bundle-stats.json (produced by `vite build` with ANALYZE=1) and prints
// a human-readable per-chunk breakdown grouped by npm package / source dir.

import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const statsPath = path.resolve(__dirname, "..", "bundle-stats.json");

if (!existsSync(statsPath)) {
  console.error(`bundle-stats.json not found at ${statsPath}`);
  console.error("Run `npm run analyze` (which sets ANALYZE=1) first.");
  process.exit(1);
}

const data = JSON.parse(readFileSync(statsPath, "utf8"));
const { nodeMetas, nodeParts } = data;

const bucketize = (id) => {
  if (!id) return "<unknown>";
  if (id.startsWith(" ")) return "<bundler runtime>";
  const nmIdx = id.indexOf("/node_modules/");
  if (nmIdx >= 0) {
    const rest = id.slice(nmIdx + "/node_modules/".length).split("/");
    return rest[0].startsWith("@") ? `${rest[0]}/${rest[1]}` : rest[0];
  }
  const srcIdx = id.indexOf("/src/frontend/src/");
  if (srcIdx >= 0) {
    const rest = id.slice(srcIdx + "/src/frontend/src/".length).split("/");
    return "src/" + (rest.length >= 2 ? `${rest[0]}/${rest[1]}` : rest[0]);
  }
  return id;
};

const byChunk = new Map();
for (const meta of Object.values(nodeMetas)) {
  for (const [chunkPath, partId] of Object.entries(meta.moduleParts ?? {})) {
    const part = nodeParts[partId];
    if (!part) continue;
    const list = byChunk.get(chunkPath) ?? [];
    list.push({ id: meta.id, raw: part.renderedLength, gz: part.gzipLength });
    byChunk.set(chunkPath, list);
  }
}

const chunks = [...byChunk.entries()]
  .filter(([k]) => k.endsWith(".js"))
  .map(([chunk, mods]) => ({
    chunk,
    mods,
    raw: mods.reduce((s, m) => s + m.raw, 0),
    gz: mods.reduce((s, m) => s + m.gz, 0),
  }))
  .sort((a, b) => b.gz - a.gz);

const fmt = (n) => {
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
  return n + " B";
};

const totalRaw = chunks.reduce((s, c) => s + c.raw, 0);
const totalGz = chunks.reduce((s, c) => s + c.gz, 0);
const totalMods = chunks.reduce((s, c) => s + c.mods.length, 0);

const bar = "─".repeat(78);
console.log("\nFRONTEND BUNDLE ANALYSIS");
console.log(bar);
console.log(`  Total: ${fmt(totalRaw)} raw / ${fmt(totalGz)} gz across ${chunks.length} chunks (${totalMods} modules)`);
console.log("  Sizes from rollup-plugin-visualizer: raw = post tree-shaking, pre-minify.");
console.log("  Gzipped column reflects what hits the wire.");
console.log();
console.log("CHUNKS (ranked by gzipped size)");
console.log(bar);
console.log(`  ${"RAW".padStart(9)}  ${"GZ".padStart(8)}  ${"MODS".padStart(5)}  CHUNK`);
for (const c of chunks) {
  console.log(`  ${fmt(c.raw).padStart(9)}  ${fmt(c.gz).padStart(8)}  ${String(c.mods.length).padStart(5)}  ${path.basename(c.chunk)}`);
}

const TOP_N = Number(process.env.ANALYZE_TOP_N ?? 10);
const TOP_BUCKETS = Number(process.env.ANALYZE_TOP_BUCKETS ?? 8);

console.log(`\nTOP ${TOP_N} CHUNKS BY GZ — top ${TOP_BUCKETS} contributors each`);
console.log(bar);
for (const c of chunks.slice(0, TOP_N)) {
  const buckets = new Map();
  for (const m of c.mods) {
    const b = bucketize(m.id);
    const cur = buckets.get(b) ?? { raw: 0, gz: 0, n: 0 };
    cur.raw += m.raw;
    cur.gz += m.gz;
    cur.n += 1;
    buckets.set(b, cur);
  }
  const sorted = [...buckets.entries()].sort((a, b) => b[1].gz - a[1].gz);
  const shown = sorted.slice(0, TOP_BUCKETS);
  const hiddenCount = sorted.length - shown.length;
  const hiddenGz = sorted.slice(TOP_BUCKETS).reduce((s, [, v]) => s + v.gz, 0);

  console.log(`\n  ${path.basename(c.chunk)}  (${fmt(c.raw)} raw / ${fmt(c.gz)} gz)`);
  for (const [name, v] of shown) {
    const pct = c.gz > 0 ? ((v.gz / c.gz) * 100).toFixed(0).padStart(2) : "--";
    console.log(`    ${fmt(v.gz).padStart(8)} gz (${pct}%)  ${fmt(v.raw).padStart(9)} raw  ${String(v.n).padStart(3)} mod  ${name}`);
  }
  if (hiddenCount > 0) {
    console.log(`    ${fmt(hiddenGz).padStart(8)} gz       (rest)              ${String(hiddenCount).padStart(3)} mod  …${hiddenCount} more bucket${hiddenCount === 1 ? "" : "s"}`);
  }
}
console.log();
