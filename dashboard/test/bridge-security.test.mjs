import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dashboardRoot = path.resolve(__dirname, '..');

// The post-paywall security contract: local audit is FREE and FRICTIONLESS,
// while the privacy boundary stays hard — remote origins must pair, hostile
// origins are refused, the static handler cannot escape its directory, and
// the bridge serves only the configured local root.
async function createSkillRoot() {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'ctdash-free-'));
  await fs.mkdir(path.join(root, 'registry'), { recursive: true });
  await fs.mkdir(path.join(root, 'chain', 'blockspace', 'blobs'), { recursive: true });
  await fs.writeFile(path.join(root, 'SKILL.md'), '# Test Skill\n');
  await fs.writeFile(path.join(root, 'timechain.py'), '# test placeholder\n');
  await fs.writeFile(path.join(root, 'registry', 'modalities.json'), JSON.stringify({ modalities: [] }));
  await fs.writeFile(path.join(root, 'registry', 'senses.json'), JSON.stringify({ senses: [] }));
  await fs.writeFile(path.join(root, 'chain', 'blockspace', 'index.json'), '{}');
  await fs.writeFile(path.join(root, 'chain', 'rings.jsonl'),
    JSON.stringify({ index: 0, ring_type: 'genesis', prev_hash: '0'.repeat(64), payload: { name: 'fixture' }, blockspace_refs: [], poq: {}, ring_hash: 'a'.repeat(64) }) + '\n');
  return root;
}

function request(port, pathname, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: '127.0.0.1', port, path: pathname, headers }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, raw: Buffer.concat(chunks).toString('utf8') }));
    });
    req.on('error', reject);
  });
}

async function startServer(root) {
  const port = 8867 + Math.floor(Math.random() * 500);
  const child = spawn(process.execPath, [path.join(dashboardRoot, 'server.mjs')], {
    env: { ...process.env, CT_DASHBOARD_ROOT: root, CT_DASHBOARD_PORT: String(port) },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  for (let i = 0; i < 80; i += 1) {
    try {
      await request(port, '/api/bridge/status');
      return { child, port };
    } catch {
      await new Promise((r) => setTimeout(r, 125));
    }
  }
  child.kill();
  throw new Error('server did not start');
}

test('local audit is free: data endpoints respond without any unlock step', async (t) => {
  const root = await createSkillRoot();
  const { child, port } = await startServer(root);
  t.after(() => child.kill());
  for (const pathname of ['/api/timechain/summary', '/api/timechain/rings', '/api/blockspace', '/api/learning/overview']) {
    const { status } = await request(port, pathname);
    assert.equal(status, 200, `${pathname} should be open locally`);
  }
});

test('hostile origins are refused; allowed remote origins must pair first', async (t) => {
  const root = await createSkillRoot();
  const { child, port } = await startServer(root);
  t.after(() => child.kill());
  const hostile = await request(port, '/api/timechain/summary', { origin: 'https://evil.example' });
  assert.equal(hostile.status, 403);
  const unpaired = await request(port, '/api/timechain/summary', { origin: 'https://cyphertempre.ai' });
  assert.equal(unpaired.status, 401);
});

test('static handler cannot escape the public directory', async (t) => {
  const root = await createSkillRoot();
  const { child, port } = await startServer(root);
  t.after(() => child.kill());
  // %2e%2e is normalized away by URL parsing before the handler (also safe);
  // an ENCODED slash survives parsing and must hit the resolve+prefix guard.
  const { status } = await request(port, '/..%2Fserver.mjs');
  assert.equal(status, 403);
  const normalized = await request(port, '/%2e%2e/server.mjs');
  assert.notEqual(normalized.raw.includes('verifyMessage'), true);
});

test('no payment endpoints remain', async (t) => {
  const root = await createSkillRoot();
  const { child, port } = await startServer(root);
  t.after(() => child.kill());
  for (const pathname of ['/api/gate/config', '/api/gate/verify']) {
    const { status } = await request(port, pathname);
    assert.equal(status, 404, `${pathname} should be gone`);
  }
});
