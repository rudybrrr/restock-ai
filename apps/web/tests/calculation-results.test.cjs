const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const file = path.resolve(__dirname, '../lib/calculation-results.ts');
const compiled = new Module(file, module);
compiled._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, file);
const { readCalculationResult } = compiled.exports;
// Captured disposable PostgreSQL example is a contract fixture, not live UI data.
const example = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../..', 'docs/examples/manager-calculation-results.json'), 'utf8'));
const fixture = () => structuredClone(example);
test('exact artifact preserves strings, baseline and projection bases', () => {
  const result = readCalculationResult(fixture(), example.run_id);
  assert.equal(result.artifact.outputs.dishes[0].baseline.expected_portions, '80');
  assert.equal(typeof result.artifact.outputs.existing_commitments_projection.buckets[0].ingredients[0].required, 'string');
  assert.notDeepEqual(result.artifact.outputs.existing_commitments_projection, result.artifact.outputs.with_recommendation_projection);
});
test('wrong run, schema, or ambiguous freshness cannot render', () => {
  assert.throws(() => readCalculationResult(fixture(), 'different-run'));
  for (const change of [r => r.artifact.outputs.schema_version = 'OTHER', r => r.stale = !r.stale, r => delete r.artifact.outputs.dishes[0].baseline.eligible_days]) {
    const r = fixture(); change(r); assert.throws(() => readCalculationResult(r, r.run_id));
  }
});
test('missing dish, numeric quantities and malformed intervals are rejected', () => {
  for (const change of [r => delete r.artifact.outputs.forecast.buckets[0].expected_portions['chicken-rice'], r => r.artifact.outputs.dishes[0].baseline.expected_portions = 0, r => r.artifact.outputs.forecast.buckets[0].end = r.artifact.outputs.forecast.buckets[0].start]) {
    const r = fixture(); change(r); assert.throws(() => readCalculationResult(r, r.run_id));
  }
});
test('null forecast and incomplete projection remain unknown rather than zero', () => {
  const r = fixture(); r.artifact.outputs.dishes[0].baseline.expected_portions = null;
  const p = r.artifact.outputs.existing_commitments_projection; p.complete = false; p.buckets = null; p.first_shortages = null;
  const got = readCalculationResult(r, r.run_id);
  assert.equal(got.artifact.outputs.dishes[0].baseline.expected_portions, null);
  assert.equal(got.artifact.outputs.existing_commitments_projection.buckets, null);
});
test('historical stale output is readable without mutation', () => {
  const r = fixture(); r.current_state_revision = 'later'; r.stale = true;
  assert.deepEqual(readCalculationResult(r, r.run_id), r);
});
test('unrecorded is not an empty calculation', () => {
  const r = { run_id: 'queued', status: 'NOT_RECORDED', current_state_revision: '1', stale: null, plan_version_id: null, artifact: null };
  assert.deepEqual(readCalculationResult(r, 'queued'), r);
  assert.throws(() => readCalculationResult({ ...r, stale: false }, 'queued'));
});
