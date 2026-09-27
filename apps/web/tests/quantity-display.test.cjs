const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const file = path.resolve(__dirname, '../lib/quantity-display.ts');
const compiled = new Module(file, module);
compiled._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, file);
const { displayQuantity } = compiled.exports;
test('readable balance quantities retain unknown and distinguish rounded values', () => {
  for (const [input, expected] of [[null,'Unknown'],[undefined,'Unknown'],['17.000','17.000'],['0E-9','0.000'],['23.359999870','≈ 23.360'],['1.640000130','≈ 1.640'],['1.234500','≈ 1.235'],['-1.234500','≈ -1.235'],['999999999999999999.000','999999999999999999.000'],['1e-9','≈ 0.000'],['-0','0.000'],['1e2','100.000'],['invalid','invalid']]) assert.equal(displayQuantity(input).text, expected);
  assert.equal(displayQuantity('1.230000').rounded, false);
  assert.equal(displayQuantity('1.230001').rounded, true);
});
