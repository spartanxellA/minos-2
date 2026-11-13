// Acomodo de una nube de palabras: la más mencionada al centro y las demás en espiral alrededor, sin encimarse.
// No depende del navegador (la medida del texto llega como función), así se prueba con `npm test`.

export interface CloudInput {
  key: string;
  text: string;
  weight: number;
}

export interface PlacedWord extends CloudInput {
  /** Centro del texto. */
  x: number;
  y: number;
  width: number;
  height: number;
  size: number;
}

export interface CloudOptions {
  minSize: number;
  maxSize: number;
  /** Ancho del texto en píxeles para un tamaño de letra. */
  measure: (text: string, size: number) => number;
  padding?: number;
}

/** Tamaño de letra por peso: raíz cuadrada, para que una palabra muy repetida no deje diminutas a las demás. */
export function fontSize(weight: number, min: number, max: number, minSize: number, maxSize: number): number {
  if (max <= min) return Math.round((minSize + maxSize) / 2);
  return Math.round(minSize + (maxSize - minSize) * Math.sqrt((weight - min) / (max - min)));
}

function place(words: CloudInput[], width: number, height: number, opts: CloudOptions, scale: number): PlacedWord[] {
  const pad = opts.padding ?? 3;
  const weights = words.map((w) => w.weight);
  const lo = Math.min(...weights);
  const hi = Math.max(...weights);
  const cx = width / 2;
  const cy = height / 2;
  // La espiral se estira con la forma del recuadro: más ancha que alta en una tarjeta apaisada.
  const aspect = width / height;
  const reach = Math.hypot(width, height) / 2;
  const placed: PlacedWord[] = [];

  for (const word of [...words].sort((a, b) => b.weight - a.weight)) {
    const size = Math.max(9, Math.round(fontSize(word.weight, lo, hi, opts.minSize, opts.maxSize) * scale));
    const w = opts.measure(word.text, size) + pad * 2;
    const h = size * 1.15 + pad;
    if (w > width || h > height) continue;
    // Pasos de unos 4 px sobre la espiral, cerca o lejos del centro.
    for (let t = 0, r = 0; ; t += Math.min(0.5, 4 / (r + 1))) {
      r = 1.6 * t;
      if (r > reach) break;
      const x = cx + r * Math.cos(t) * Math.max(1, aspect);
      const y = cy + r * Math.sin(t) / Math.min(1, aspect);
      const left = x - w / 2;
      const top = y - h / 2;
      if (left < 0 || top < 0 || left + w > width || top + h > height) continue;
      const hit = placed.some((p) =>
        left < p.x + p.width / 2 && left + w > p.x - p.width / 2 && top < p.y + p.height / 2 && top + h > p.y - p.height / 2);
      if (!hit) {
        placed.push({ ...word, x, y, width: w, height: h, size });
        break;
      }
    }
  }
  return placed;
}

/** Acomoda las palabras en un recuadro de `width` × `height`. Si no caben casi todas, reduce las letras y reintenta. */
export function layoutCloud(words: CloudInput[], width: number, height: number, opts: CloudOptions): PlacedWord[] {
  if (!words.length || width <= 0 || height <= 0) return [];
  let best: PlacedWord[] = [];
  for (const scale of [1, 0.85, 0.72, 0.6, 0.5]) {
    const placed = place(words, width, height, opts, scale);
    if (placed.length > best.length) best = placed;
    if (placed.length >= words.length * 0.9) break;
  }
  return best;
}
