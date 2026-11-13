// Pruebas del acomodo de la nube de palabras. Uso: npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { fontSize, layoutCloud, type CloudInput } from "./wordcloud.ts";

const measure = (text: string, size: number) => text.length * size * 0.6;
const words = (n: number): CloudInput[] => Array.from({ length: n }, (_, i) => ({ key: `w${i}`, text: `palabra${i}`, weight: n - i }));

test("la más mencionada queda al centro y con la letra más grande", () => {
  const placed = layoutCloud(words(20), 600, 300, { minSize: 12, maxSize: 40, measure });
  const top = placed.find((p) => p.key === "w0")!;
  assert.ok(Math.abs(top.x - 300) < 30 && Math.abs(top.y - 150) < 30);
  assert.equal(top.size, Math.max(...placed.map((p) => p.size)));
});

test("ninguna palabra se encima ni se sale del recuadro", () => {
  for (const [w, h] of [[600, 300], [340, 280]]) {
    const placed = layoutCloud(words(60), w, h, { minSize: 11, maxSize: 36, measure });
    assert.ok(placed.length >= 30, `solo cupieron ${placed.length}`);
    for (const p of placed) {
      assert.ok(p.x - p.width / 2 >= 0 && p.x + p.width / 2 <= w && p.y - p.height / 2 >= 0 && p.y + p.height / 2 <= h);
    }
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        const a = placed[i], b = placed[j];
        const overlap = Math.abs(a.x - b.x) < (a.width + b.width) / 2 && Math.abs(a.y - b.y) < (a.height + b.height) / 2;
        assert.ok(!overlap, `${a.text} y ${b.text} se enciman`);
      }
    }
  }
});

test("el tamaño de letra crece con la raíz del peso", () => {
  assert.equal(fontSize(1, 1, 101, 10, 50), 10);
  assert.equal(fontSize(101, 1, 101, 10, 50), 50);
  assert.equal(fontSize(26, 1, 101, 10, 50), 30);
  assert.equal(fontSize(5, 5, 5, 10, 50), 30);
});

test("sin palabras o sin espacio no hay nube", () => {
  assert.deepEqual(layoutCloud([], 600, 300, { minSize: 12, maxSize: 40, measure }), []);
  assert.deepEqual(layoutCloud(words(3), 0, 300, { minSize: 12, maxSize: 40, measure }), []);
});
