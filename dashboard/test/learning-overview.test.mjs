import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dashboardRoot = path.resolve(__dirname, '..');

// Fixture: a chain carrying every learning-membrane artifact the overview
// renders — an operator adoption, a dream cycle, a telemetry digest that
// REALLY notarizes the fixture telemetry bytes, and a witness quorum whose
// HMACs REALLY verify over the head ring. The hash-chain layer is left
// deliberately unverifiable (fake ring hashes) to prove the three integrity
// layers are independent.
async function createLearningRoot() {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'ctdash-learning-'));
  await fs.mkdir(path.join(root, 'registry'), { recursive: true });
  await fs.mkdir(path.join(root, 'chain', 'blockspace', 'blobs'), { recursive: true });
  await fs.mkdir(path.join(root, 'chain', 'consensus'), { recursive: true });
  // isSkillRoot markers — without these the server falls back to a real install
  await fs.writeFile(path.join(root, 'SKILL.md'), '# Test Skill\n');
  await fs.writeFile(path.join(root, 'timechain.py'), '# test placeholder\n');
  await fs.writeFile(path.join(root, 'registry', 'modalities.json'), JSON.stringify({ modalities: [] }));
  await fs.writeFile(path.join(root, 'registry', 'senses.json'), JSON.stringify({ senses: [] }));
  await fs.writeFile(path.join(root, 'chain', 'blockspace', 'index.json'), '{}');

  const telemetryLines = [
    JSON.stringify({ schema: 1, event: 'offer', ts: '2026-06-10T00:00:00+00:00', data: { query_hash: 'q1', candidates: [{ i: 1 }] } }),
    JSON.stringify({ schema: 1, event: 'replay-accept', ts: '2026-06-10T00:01:00+00:00', data: { query_hash: 'q1', ring_index: 1, tokens_saved: 400 } }),
  ];
  const telemetryRaw = Buffer.from(telemetryLines.join('\n') + '\n', 'utf8');
  await fs.writeFile(path.join(root, 'chain', 'telemetry.jsonl'), telemetryRaw);
  const segmentSha = crypto.createHash('sha256').update(telemetryRaw).digest('hex');

  const rings = [
    { index: 0, ring_type: 'genesis', timestamp: 't0', prev_hash: '0'.repeat(64), payload: { name: 'fixture' }, blockspace_refs: [], poq: { brightness: null }, ring_hash: 'f'.repeat(64) },
    { index: 1, ring_type: 'operator', timestamp: 't1', prev_hash: 'f'.repeat(64), payload: { summary: 'scorer adopted', operator: 'scorer', action: 'adopt', scorer: { scorer_version: 'trained-v1', eval: { trained_mrr: 0.8, hand_mrr: 0.5 } } }, blockspace_refs: [], poq: { brightness: 200 }, ring_hash: 'a'.repeat(64) },
    { index: 2, ring_type: 'dream', timestamp: 't2', prev_hash: 'a'.repeat(64), payload: { summary: 'dream cycle', dream: { verify: { chain: 'PASS' }, missed_positives: { mined: 3 }, training: { scorer: { adopted: false, reasons: ['guard held'] }, lens: { adopted: true, version: 'lens-v1' } }, growth: { proposals: [{ action: 'born' }] }, salience: { rings: 2 }, duration_s: 1.2 } }, blockspace_refs: [], poq: { brightness: 210 }, ring_hash: 'b'.repeat(64) },
    { index: 3, ring_type: 'telemetry-digest', timestamp: 't3', prev_hash: 'b'.repeat(64), payload: { summary: 'digest', telemetry_digest: { schema: 1, segment_sha256: segmentSha, from_offset: 0, to_offset: telemetryRaw.length, event_counts: { offer: 1, 'replay-accept': 1 } } }, blockspace_refs: [], poq: { brightness: null }, ring_hash: 'c'.repeat(64) },
  ];
  await fs.writeFile(path.join(root, 'chain', 'rings.jsonl'), rings.map((r) => JSON.stringify(r)).join('\n') + '\n');

  const witnesses = [1, 2, 3].map((n) => ({ id: `w${n}`, key: crypto.randomBytes(32).toString('hex') }));
  await fs.writeFile(path.join(root, 'chain', 'consensus', 'config.json'), JSON.stringify({ witnesses, quorum: 2 }));
  const head = rings.at(-1);
  const msg = `${head.index}:${head.ring_hash}`;
  const attestations = witnesses.map((w) => JSON.stringify({
    height: head.index,
    ring_hash: head.ring_hash,
    witness: w.id,
    mac: crypto.createHmac('sha256', Buffer.from(w.key, 'hex')).update(msg).digest('hex'),
  }));
  await fs.writeFile(path.join(root, 'chain', 'consensus', 'attestations.jsonl'), attestations.join('\n') + '\n');

  await fs.writeFile(path.join(root, 'chain', 'replay.json'), JSON.stringify({
    1: { accepts: 2, rederive_due: true },
    2: { accepts: 1, rederive_due: false },
  }));
  return root;
}

function getJson(port, pathname) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: '127.0.0.1', port, path: pathname }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, body: JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}') }));
    });
    req.on('error', reject);
  });
}

async function startServer(root) {
  const port = 8917 + Math.floor(Math.random() * 500);
  const child = spawn(process.execPath, [path.join(dashboardRoot, 'server.mjs')], {
    env: { ...process.env, CT_DASHBOARD_ROOT: root, CT_DASHBOARD_PORT: String(port) },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  for (let i = 0; i < 80; i += 1) {
    try {
      await getJson(port, '/api/bridge/status');
      return { child, port };
    } catch {
      await new Promise((r) => setTimeout(r, 125));
    }
  }
  child.kill();
  throw new Error('server did not start');
}

test('learning overview renders the membrane from a fixture chain', async (t) => {
  const root = await createLearningRoot();
  const { child, port } = await startServer(root);
  t.after(() => child.kill());

  const { status, body } = await getJson(port, '/api/learning/overview');
  assert.equal(status, 200);

  // integrity layers are independent: quorum + digests verify even though the
  // fixture's hash chain is deliberately fake
  assert.equal(body.integrity.consensus.configured, true);
  assert.equal(body.integrity.consensus.ok, true);
  assert.equal(body.integrity.consensus.validWitnesses, 3);
  assert.equal(body.integrity.digests.ok, true);
  assert.equal(body.integrity.digests.digests, 1);

  // operators timeline
  assert.equal(body.operators.length, 1);
  assert.equal(body.operators[0].operator, 'scorer');
  assert.equal(body.operators[0].version, 'trained-v1');
  assert.equal(body.operators[0].eval.trained_mrr, 0.8);

  // dreams
  assert.equal(body.dreams.length, 1);
  assert.equal(body.dreams[0].missedPositives, 3);
  assert.equal(body.dreams[0].training.lens, 'adopted lens-v1');
  assert.equal(body.dreams[0].training.scorer, 'held');
  assert.equal(body.dreams[0].growthProposals, 1);

  // economics
  assert.equal(body.telemetry.tokensSavedTotal, 400);
  assert.equal(body.telemetry.counts['replay-accept'], 1);
  assert.equal(body.replay.accepts, 3);
  assert.equal(body.replay.rederiveDue, 1);

  // quality series carries the sealed brightness points
  assert.equal(body.quality.brightness.length, 2);
});

test('learning overview refuses hostile origins', async (t) => {
  const root = await createLearningRoot();
  const { child, port } = await startServer(root);
  t.after(() => child.kill());
  const status = await new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port, path: '/api/learning/overview',
               headers: { origin: 'https://evil.example' } },
      (res) => { res.resume(); resolve(res.statusCode); }).on('error', reject);
  });
  assert.equal(status, 403);
});
