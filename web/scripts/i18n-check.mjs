// Revisa que cada texto de la interfaz tenga traducción al inglés y al francés en lib/messages/.
// Busca t("…"), translate("…") y msg("…") con texto fijo. Uso: npm run i18n:check  (con --list imprime los que faltan)
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const files = [];
(function walk(dir) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === ".next" || name === "messages") continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p);
    else if (/\.(tsx?|mjs)$/.test(name) && !p.includes("/scripts/")) files.push(p);
  }
})(root);

const used = new Map();
const call = /\b(?:t|tr|translate|msg)\(\s*"((?:[^"\\]|\\.)*)"/g;
for (const f of files) {
  const src = readFileSync(f, "utf8");
  for (const m of src.matchAll(call)) {
    const key = JSON.parse(`"${m[1]}"`);
    if (!used.has(key)) used.set(key, f.slice(root.length));
  }
}

// Los catálogos son archivos propios del repositorio con un objeto { "español": ["English", "Français"] }; se
// evalúan quitando lo que es solo de TypeScript.
const catalog = {};
for (const name of readdirSync(join(root, "lib/messages"))) {
  const src = readFileSync(join(root, "lib/messages", name), "utf8")
    .replace(/^export /gm, "").replace(/: Record<string, \[string, string\]>/g, "");
  const exported = /const (\w+) =\s*\{/.exec(src.slice(src.lastIndexOf("\nconst ") + 1))?.[1];
  Object.assign(catalog, Function(`${src}; return ${exported};`)());
}

// El cuestionario llega del servidor (data/surveys.json); cada texto que se muestra debe tener traducción.
const surveys = JSON.parse(readFileSync(join(root, "../data/surveys.json"), "utf8")).surveys;
for (const s of surveys.filter((x) => x.id === "RASurvey")) {
  for (const sec of s.sections) {
    for (const text of [sec.name, sec.description]) if (text && !used.has(text)) used.set(text, "data/surveys.json");
    for (const q of sec.questions) {
      for (const text of [q.text, q.subtext, ...q.options.map((o) => o.label)]) {
        if (text && !used.has(text)) used.set(text, "data/surveys.json");
      }
    }
  }
}

const missing = [...used].filter(([k]) => !catalog[k]);
const broken = Object.entries(catalog).filter(([k, v]) => {
  if (!Array.isArray(v) || v.length !== 2 || v.some((x) => typeof x !== "string" || !x)) return true;
  const vars = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");
  return v.some((x) => vars(x) !== vars(k));
});
for (const [k, f] of missing) console.log(`Falta traducción (${f}): ${JSON.stringify(k)}`);
for (const [k] of broken) console.log(`Traducción mal formada o con {variables} distintas: ${JSON.stringify(k)}`);
console.log(`${used.size} textos en el código, ${Object.keys(catalog).length} en los catálogos.`);
if (missing.length || broken.length) process.exit(1);
