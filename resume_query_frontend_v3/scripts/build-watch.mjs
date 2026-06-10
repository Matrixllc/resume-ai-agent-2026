import { existsSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { spawn } from "node:child_process";

const root = process.cwd();
const buildDistDir = process.env.NEXT_DIST_DIR || ".next-build-watch";
const scanTargets = ["app", "components", "lib"].map((item) => join(root, item));
const configFiles = [
  "next.config.mjs",
  "tailwind.config.ts",
  "postcss.config.js",
  "tsconfig.json",
  "package.json",
].map((item) => join(root, item));

const ignoredNames = new Set([".next", "node_modules", ".git"]);
const knownMtimes = new Map();
let running = false;
let queuedReason = "";

function collectFiles(target) {
  if (!existsSync(target)) return [];
  const stat = statSync(target);
  if (stat.isFile()) return [target];
  if (!stat.isDirectory()) return [];
  const files = [];
  for (const entry of readdirSync(target, { withFileTypes: true })) {
    if (ignoredNames.has(entry.name)) continue;
    const fullPath = join(target, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectFiles(fullPath));
    } else if (entry.isFile() && /\.(css|js|jsx|mjs|ts|tsx|json)$/.test(entry.name)) {
      files.push(fullPath);
    }
  }
  return files;
}

function scanChangedFiles() {
  const files = [...scanTargets.flatMap(collectFiles), ...configFiles.filter(existsSync)];
  const seen = new Set(files);
  const changed = [];
  for (const file of files) {
    const mtime = statSync(file).mtimeMs;
    if (!knownMtimes.has(file)) {
      knownMtimes.set(file, mtime);
      continue;
    }
    if (knownMtimes.get(file) !== mtime) {
      knownMtimes.set(file, mtime);
      changed.push(relative(root, file));
    }
  }
  for (const file of [...knownMtimes.keys()]) {
    if (!seen.has(file)) {
      knownMtimes.delete(file);
      changed.push(relative(root, file));
    }
  }
  return changed;
}

function runBuild(reason) {
  if (running) {
    queuedReason = reason || queuedReason || "queued change";
    return;
  }
  running = true;
  queuedReason = "";
  console.log(`\n[build:watch] running npm run build (${reason})`);
  const child = spawn("npm", ["run", "build"], {
    cwd: root,
    env: { ...process.env, NEXT_DIST_DIR: buildDistDir },
    shell: true,
    stdio: "inherit",
  });
  child.on("close", (code) => {
    running = false;
    console.log(`[build:watch] build ${code === 0 ? "passed" : `failed with code ${code}`}`);
    if (queuedReason) {
      const reason = queuedReason;
      queuedReason = "";
      runBuild(reason);
    }
  });
}

scanChangedFiles();
console.log(`[build:watch] polling frontend files every 1.5s. Builds write to ${buildDistDir}. Press Ctrl+C to stop.`);
runBuild("initial build");

setInterval(() => {
  const changed = scanChangedFiles();
  if (changed.length) {
    runBuild(changed.slice(0, 3).join(", "));
  }
}, 1500);
