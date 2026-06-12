import crypto from 'node:crypto';
import { execFile } from 'node:child_process';
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..');
const publicDir = path.join(__dirname, 'public');
const execFileAsync = promisify(execFile);

const HOST = process.env.CT_DASHBOARD_HOST || '127.0.0.1';
const PORT = Number(process.env.CT_DASHBOARD_PORT || 8788);
const MAX_JSON_BODY_BYTES = Math.max(1024, Number(process.env.CT_DASHBOARD_MAX_JSON_BODY_BYTES || 20_000));
const SESSION_TTL_MS = Math.max(10 * 60_000, Number(process.env.CT_DASHBOARD_SESSION_TTL_MS || 4 * 60 * 60_000));
const MAX_RING_DETAIL_BYTES = Number(process.env.CT_DASHBOARD_MAX_RING_DETAIL_BYTES || 512_000);
const MAX_BLOB_PREVIEW_BYTES = Number(process.env.CT_DASHBOARD_MAX_BLOB_PREVIEW_BYTES || 128_000);
const DOMAIN_BLOB_TEXT_LIMIT = Number(process.env.CT_DASHBOARD_DOMAIN_BLOB_TEXT_LIMIT || 64_000);
const BRIDGE_TOKEN_TTL_MS = Math.max(10 * 60_000, Number(process.env.CT_DASHBOARD_BRIDGE_TOKEN_TTL_MS || 24 * 60 * 60_000));
const PUBLIC_ORIGINS = new Set(
  (process.env.CT_DASHBOARD_PUBLIC_ORIGINS || 'https://cyphertempre.ai,https://www.cyphertempre.ai')
    .split(',')
    .map((origin) => origin.trim().replace(/\/$/, ''))
    .filter(Boolean),
);
const LOCAL_ORIGIN_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);
const BRIDGE_PAIR_CODE = createPairingCode(process.env.CT_DASHBOARD_PAIR_CODE || crypto.randomBytes(5).toString('hex'));

const sessions = new Map();
const bridgeTokens = new Map();
let timechainRoot = null;

function lower(value) {
  return String(value || '').toLowerCase();
}

function sha256Hex(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

function normalizePairingCode(value) {
  return String(value || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
}

function createPairingCode(value) {
  const code = normalizePairingCode(value);
  if (code.length < 8) {
    throw new Error('CT_DASHBOARD_PAIR_CODE must contain at least 8 letters or digits.');
  }
  return code;
}

function displayPairingCode(value) {
  return normalizePairingCode(value).replace(/(.{4})(?=.)/g, '$1-');
}

function timingDigest(value) {
  return crypto.createHash('sha256').update(String(value), 'utf8').digest();
}

function pairingCodeMatches(value) {
  return crypto.timingSafeEqual(timingDigest(normalizePairingCode(value)), timingDigest(BRIDGE_PAIR_CODE));
}

function createSession() {
  const id = crypto.randomBytes(32).toString('hex');
  const nonce = crypto.randomBytes(24).toString('hex');
  const now = Date.now();
  sessions.set(id, {
    id,
    nonce,
    createdAt: now,
    expiresAt: now + SESSION_TTL_MS,
  });
  return sessions.get(id);
}

function bridgeRecord(req) {
  const token = String(req.headers['x-ct-bridge-token'] || '').trim();
  if (!token) return null;
  const record = bridgeTokens.get(token);
  if (!record || record.expiresAt < Date.now()) {
    bridgeTokens.delete(token);
    return null;
  }
  return record;
}

function getSession(req, res) {
  const record = bridgeRecord(req);
  if (record) {
    let session = record.sessionId ? sessions.get(record.sessionId) : null;
    if (!session || session.expiresAt < Date.now()) {
      session = createSession();
      record.sessionId = session.id;
    }
    record.expiresAt = Date.now() + BRIDGE_TOKEN_TTL_MS;
    session.expiresAt = Date.now() + SESSION_TTL_MS;
    return session;
  }

  const cookies = parseCookies(req.headers.cookie || '');
  let session = cookies.ctdash ? sessions.get(cookies.ctdash) : null;
  if (!session || session.expiresAt < Date.now()) {
    session = createSession();
    res.setHeader('Set-Cookie', `ctdash=${session.id}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${Math.floor(SESSION_TTL_MS / 1000)}`);
  }
  return session;
}

function parseCookies(header) {
  const out = {};
  for (const part of header.split(';')) {
    const [key, ...rest] = part.trim().split('=');
    if (key) out[key] = rest.join('=');
  }
  return out;
}

function allowedOrigin(req) {
  const origin = req.headers.origin;
  if (!origin) return isTrustedLocalDirectRequest(req);
  try {
    const url = new URL(origin);
    if (LOCAL_ORIGIN_HOSTS.has(url.hostname)) return true;
    return PUBLIC_ORIGINS.has(url.origin);
  } catch {
    return false;
  }
}

function isRemoteOrigin(req) {
  const origin = req.headers.origin;
  if (!origin) return !isTrustedLocalDirectRequest(req);
  try {
    return !LOCAL_ORIGIN_HOSTS.has(new URL(origin).hostname);
  } catch {
    return true;
  }
}

function requestHostName(req) {
  const host = String(req.headers.host || '').trim();
  if (!host) return '';
  try {
    return new URL(`http://${host}`).hostname;
  } catch {
    return host.replace(/:\d+$/, '');
  }
}

function isLoopbackRemoteAddress(value) {
  const address = String(value || '');
  return address === '127.0.0.1'
    || address === '::1'
    || address === '::ffff:127.0.0.1'
    || address.startsWith('::ffff:127.');
}

function isTrustedLocalDirectRequest(req) {
  const host = requestHostName(req);
  return LOCAL_ORIGIN_HOSTS.has(host) && isLoopbackRemoteAddress(req.socket?.remoteAddress);
}

function applyCorsHeaders(req, res) {
  const origin = req.headers.origin;
  if (!origin || !allowedOrigin(req)) return;
  res.setHeader('Access-Control-Allow-Origin', origin);
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'content-type, x-ct-bridge-token');
  res.setHeader('Access-Control-Max-Age', '600');
  res.setHeader('Vary', 'Origin, Access-Control-Request-Headers, Access-Control-Request-Method');
  if (req.headers['access-control-request-private-network']) {
    res.setHeader('Access-Control-Allow-Private-Network', 'true');
  }
}

function requireBridgePairing(req) {
  if (!isRemoteOrigin(req)) return;
  if (bridgeRecord(req)) return;
  const error = new Error('Pair this browser with the local Cypher Tempre bridge first.');
  error.status = 401;
  throw error;
}

function securityHeaders() {
  return {
    'Content-Security-Policy': [
      "default-src 'self'",
      "script-src 'self'",
      "style-src 'self' 'unsafe-inline'",
      "connect-src 'self'",
      "img-src 'self' data: blob: https:",
      "font-src 'self'",
      "object-src 'none'",
      "base-uri 'none'",
      "form-action 'none'",
      "frame-ancestors 'none'",
    ].join('; '),
    'Cross-Origin-Opener-Policy': 'same-origin',
    'Cross-Origin-Resource-Policy': 'same-origin',
    'Referrer-Policy': 'no-referrer',
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
  };
}

function httpError(message, status = 400) {
  const error = new Error(message);
  error.status = status;
  return error;
}

async function discoverTimechainRoot() {
  const explicit = process.env.CT_DASHBOARD_ROOT || process.env.CT_TIMECHAIN_ROOT;
  const candidates = [
    explicit,
    path.join(os.homedir(), '.codex', 'skills', 'cypher-tempre-self-model'),
    path.join(os.homedir(), '.claude', 'skills', 'cypher-tempre-self-model'),
    path.join(os.homedir(), '.openclaw', 'workspace', 'skills', 'cypher-tempre-self-model'),
    path.join(repoRoot, 'skills', 'codex', 'cypher-tempre-self-model'),
  ].filter(Boolean);
  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    if (await isSkillRoot(resolved)) return await fs.realpath(resolved);
  }
  throw new Error('No Cypher Tempre skill root found. Set CT_DASHBOARD_ROOT to a local cypher-tempre-self-model directory.');
}

async function isSkillRoot(root) {
  const required = ['SKILL.md', 'timechain.py', 'registry/modalities.json', 'registry/senses.json'];
  for (const rel of required) {
    if (!fsSync.existsSync(path.join(root, rel))) return false;
  }
  return true;
}

function ensureInsideRoot(target) {
  const resolved = path.resolve(target);
  const prefix = `${timechainRoot}${path.sep}`;
  if (resolved !== timechainRoot && !resolved.startsWith(prefix)) {
    throw new Error('Path escapes configured Timechain root.');
  }
  return resolved;
}

async function readJsonSafe(file, fallback) {
  try {
    return JSON.parse(await fs.readFile(file, 'utf8'));
  } catch {
    return fallback;
  }
}

async function loadRings() {
  const ringsPath = ensureInsideRoot(path.join(timechainRoot, 'chain', 'rings.jsonl'));
  if (!fsSync.existsSync(ringsPath)) return [];
  const text = await fs.readFile(ringsPath, 'utf8');
  return text.split(/\r?\n/).filter(Boolean).map((line, lineIndex) => {
    try {
      return JSON.parse(line);
    } catch (error) {
      return { index: lineIndex, ring_type: 'parse-error', payload: { error: error.message }, ring_hash: null };
    }
  });
}

async function loadRegistries() {
  const modalitiesPath = ensureInsideRoot(path.join(timechainRoot, 'registry', 'modalities.json'));
  const sensesPath = ensureInsideRoot(path.join(timechainRoot, 'registry', 'senses.json'));
  const emergentPath = ensureInsideRoot(path.join(timechainRoot, 'registry', 'emergent.json'));
  const modalities = (await readJsonSafe(modalitiesPath, { modalities: [] })).modalities || [];
  const senses = (await readJsonSafe(sensesPath, { senses: [] })).senses || [];
  const emergentRaw = await readJsonSafe(emergentPath, {});
  const emergent = Array.isArray(emergentRaw) ? emergentRaw : Object.values(emergentRaw).flat().filter(Boolean);
  return { modalities, senses, emergent };
}

async function loadBlockspace() {
  const indexPath = ensureInsideRoot(path.join(timechainRoot, 'chain', 'blockspace', 'index.json'));
  const blobsDir = ensureInsideRoot(path.join(timechainRoot, 'chain', 'blockspace', 'blobs'));
  const index = await readJsonSafe(indexPath, {});
  const entries = Object.entries(index).map(([hash, meta]) => ({
    hash,
    size: Number(meta.size || 0),
    filename: meta.filename || '',
    mime: meta.mime || '',
    added_at: meta.added_at || '',
  }));
  let blobFiles = [];
  try {
    blobFiles = await fs.readdir(blobsDir);
  } catch {
    blobFiles = [];
  }
  return {
    entries,
    blobFiles,
    totalBytes: entries.reduce((sum, entry) => sum + entry.size, 0),
  };
}

async function verifyChainWithPython() {
  const script = `
import json, hashlib, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
rings_path = root / "chain" / "rings.jsonl"
genesis_prev = "0" * 64
def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
def h(data):
    return hashlib.sha256(data).hexdigest()
def ring_hash(ring):
    return h(canonical({k: v for k, v in ring.items() if k != "ring_hash"}))
ok = True
report = []
rings = []
if rings_path.exists():
    for line in rings_path.read_text().splitlines():
        line = line.strip()
        if line:
            rings.append(json.loads(line))
if not rings:
    print(json.dumps({"ok": True, "report": ["empty chain"], "rings": 0}))
    raise SystemExit
prev = genesis_prev
for i, ring in enumerate(rings):
    if ring.get("index") != i:
        ok = False
        report.append(f"ring {i}: index mismatch (got {ring.get('index')})")
    if ring.get("prev_hash") != prev:
        ok = False
        report.append(f"ring {i}: prev_hash broken")
    recomputed = ring_hash(ring)
    if recomputed != ring.get("ring_hash"):
        ok = False
        report.append(f"ring {i}: ring_hash mismatch")
    for ref in ring.get("blockspace_refs", []):
        bh = ref.get("hash")
        blob = root / "chain" / "blockspace" / "blobs" / str(bh)
        if not blob.exists():
            ok = False
            report.append(f"ring {i}: blockspace blob missing ({ref.get('role')})")
        elif h(blob.read_bytes()) != bh:
            ok = False
            report.append(f"ring {i}: blockspace blob corrupted ({ref.get('role')})")
    prev = ring.get("ring_hash")
if ok:
    report.append(f"verified {len(rings)} rings -> chain intact, all hashes link, blockspace consistent")
print(json.dumps({"ok": ok, "report": report, "rings": len(rings)}))
`;
  try {
    const { stdout } = await execFileAsync('python3', ['-c', script, timechainRoot], {
      timeout: 20_000,
      maxBuffer: 1024 * 1024,
    });
    return JSON.parse(stdout);
  } catch (error) {
    return {
      ok: null,
      report: [`python verifier unavailable: ${error.message}`],
      rings: null,
    };
  }
}


// --------------------------------------------------------------------------- //
// P1 — the learning membrane, audited. Everything below is a read-only view of
// files the bridge already trusts: rings.jsonl (operators, dreams, digests),
// telemetry.jsonl (economics), replay.json (the antecedent ledger), and the
// consensus directory (witness quorum). No skill code runs; no data leaves.
// --------------------------------------------------------------------------- //

async function consensusStatus(rings) {
  const cfgPath = path.join(timechainRoot, 'chain', 'consensus', 'config.json');
  if (!fsSync.existsSync(cfgPath)) return { configured: false, ok: null };
  try {
    const cfg = JSON.parse(await fs.readFile(cfgPath, 'utf8'));
    const witnesses = cfg.witnesses || [];
    const quorum = Number(cfg.quorum ?? cfg.k ?? Math.ceil((witnesses.length * 2) / 3));
    const head = rings.at(-1);
    if (!head) return { configured: true, ok: null, detail: 'empty chain', quorum, witnesses: witnesses.length };
    const attPath = path.join(timechainRoot, 'chain', 'consensus', 'attestations.jsonl');
    const byWitness = new Map();
    if (fsSync.existsSync(attPath)) {
      for (const line of (await fs.readFile(attPath, 'utf8')).split(/\r?\n/)) {
        if (!line.trim()) continue;
        let att;
        try { att = JSON.parse(line); } catch { continue; }
        if (att.height === head.index && att.ring_hash === head.ring_hash) byWitness.set(att.witness, att.mac);
      }
    }
    const msg = `${head.index}:${head.ring_hash}`;
    let valid = 0;
    for (const w of witnesses) {
      const mac = crypto.createHmac('sha256', Buffer.from(String(w.key), 'hex')).update(msg).digest('hex');
      if (byWitness.get(w.id) === mac) valid += 1;
    }
    return { configured: true, ok: valid >= quorum, validWitnesses: valid,
             witnesses: witnesses.length, quorum, head: head.index };
  } catch (error) {
    return { configured: true, ok: null, detail: error.message };
  }
}

async function telemetryDigestStatus(rings) {
  const telPath = path.join(timechainRoot, 'chain', 'telemetry.jsonl');
  const digests = rings
    .filter((r) => r.payload?.telemetry_digest)
    .map((r) => ({ ring: r.index, ...r.payload.telemetry_digest }));
  if (!fsSync.existsSync(telPath)) {
    return { present: false, digests: digests.length, ok: digests.length ? false : null, notarized: 0, bytes: 0 };
  }
  const raw = await fs.readFile(telPath);
  let ok = digests.length ? true : null;
  const report = [];
  for (const d of digests) {
    const seg = raw.subarray(d.from_offset, d.to_offset);
    const good = crypto.createHash('sha256').update(seg).digest('hex') === d.segment_sha256;
    if (!good) ok = false;
    report.push({ ring: d.ring, from: d.from_offset, to: d.to_offset, ok: good });
  }
  return { present: true, ok, digests: digests.length, bytes: raw.length,
           notarized: digests.at(-1)?.to_offset || 0, report };
}

async function telemetryOverview() {
  const telPath = path.join(timechainRoot, 'chain', 'telemetry.jsonl');
  const counts = {};
  let total = 0;
  let lastTs = null;
  let tokensCum = 0;
  const tokensSavedSeries = [];
  if (fsSync.existsSync(telPath)) {
    for (const line of (await fs.readFile(telPath, 'utf8')).split(/\r?\n/)) {
      if (!line.trim()) continue;
      let e;
      try { e = JSON.parse(line); } catch { continue; }
      counts[e.event] = (counts[e.event] || 0) + 1;
      total += 1;
      lastTs = e.ts || lastTs;
      if (e.event === 'replay-accept') {
        tokensCum += Number(e.data?.tokens_saved || 0);
        tokensSavedSeries.push({ x: total, y: tokensCum, ts: e.ts });
      }
    }
  }
  const routed = counts['route'] || 0;
  return { total, counts, lastTs, tokensSavedTotal: tokensCum, tokensSavedSeries,
           missedPositives: counts['missed-positive'] || 0, routeEvents: routed };
}

function operatorsTimeline(rings) {
  return rings
    .filter((r) => r.ring_type === 'operator')
    .map((r) => {
      const p = r.payload || {};
      return {
        index: r.index,
        ts: r.timestamp,
        operator: p.operator || null,
        action: p.action || null,
        version: p.scorer?.scorer_version || p.lens_version || p.labeler_version || null,
        eval: p.scorer?.eval || p.eval || null,
        revertedTo: p.reverted_to || null,
        summary: p.summary || '',
      };
    });
}

function dreamsTimeline(rings) {
  return rings
    .filter((r) => r.ring_type === 'dream')
    .map((r) => {
      const d = r.payload?.dream || {};
      const training = {};
      for (const [k, v] of Object.entries(d.training || {})) {
        if (!v || typeof v !== 'object') continue;
        training[k] = v.error ? 'error' : v.adopted ? `adopted ${v.version || ''}`.trim() : 'held';
      }
      return {
        index: r.index,
        ts: r.timestamp,
        summary: r.payload?.summary || '',
        verify: d.verify || null,
        missedPositives: d.missed_positives?.mined ?? null,
        training,
        growthProposals: (d.growth?.proposals || []).length,
        salienceRings: d.salience?.rings ?? null,
        durationS: d.duration_s ?? null,
      };
    });
}

function qualitySeries(rings) {
  const brightness = [];
  const spanGrounding = [];
  for (const r of rings) {
    if (typeof r.poq?.brightness === 'number') brightness.push({ x: r.index, y: r.poq.brightness });
    const sg = r.payload?.poq_verdict?.span_grounding?.span_grounding;
    if (typeof sg === 'number') spanGrounding.push({ x: r.index, y: sg });
  }
  return { brightness, spanGrounding };
}

async function replayOverview() {
  const ledgerPath = path.join(timechainRoot, 'chain', 'replay.json');
  if (!fsSync.existsSync(ledgerPath)) return { present: false, rings: 0, accepts: 0, rederiveDue: 0 };
  try {
    const ledger = JSON.parse(await fs.readFile(ledgerPath, 'utf8'));
    const entries = Object.entries(ledger).filter(([, v]) => v && typeof v === 'object');
    return {
      present: true,
      rings: entries.length,
      accepts: entries.reduce((sum, [, v]) => sum + Number(v.accepts || 0), 0),
      rederiveDue: entries.filter(([, v]) => v.rederive_due).length,
    };
  } catch (error) {
    return { present: true, error: error.message };
  }
}

async function buildLearningOverview() {
  const rings = await loadRings();
  const [verification, consensus, digests, telemetry, replay] = await Promise.all([
    verifyChainWithPython(),
    consensusStatus(rings),
    telemetryDigestStatus(rings),
    telemetryOverview(),
    replayOverview(),
  ]);
  return {
    generatedAt: new Date().toISOString(),
    integrity: { chain: verification, consensus, digests },
    operators: operatorsTimeline(rings),
    dreams: dreamsTimeline(rings),
    telemetry,
    replay,
    quality: qualitySeries(rings),
  };
}

function countBy(items, getKey) {
  const counts = new Map();
  for (const item of items) {
    const key = getKey(item) || 'unknown';
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ name, count }));
}

function compactRing(ring) {
  const payload = ring.payload || {};
  const labels = payload.labels || {};
  const summary = payload.summary || payload.synthesis || payload.context || payload.event || payload.task || ring.ring_type;
  return {
    index: ring.index,
    type: ring.ring_type,
    timestamp: ring.timestamp,
    hash: ring.ring_hash,
    prevHash: ring.prev_hash,
    brightness: ring.poq?.brightness ?? null,
    blockspaceRefs: ring.blockspace_refs || [],
    summary: truncate(String(summary || ''), 360),
    keywords: labels.keywords || [],
    entities: labels.entities || [],
    modalities: (labels.modalities || []).map((x) => x.name || x.id).slice(0, 8),
    senses: (labels.senses || []).map((x) => x.name || x.id).slice(0, 8),
  };
}

function truncate(value, limit) {
  return value.length > limit ? `${value.slice(0, limit - 1)}…` : value;
}

function ringText(ring) {
  return JSON.stringify(ring.payload || {}) + ' ' + (ring.ring_type || '') + ' ' + JSON.stringify(ring.blockspace_refs || []);
}

function estimateTokens(text) {
  return Math.ceil((text || '').split(/\s+/).filter(Boolean).length * 1.25);
}

const DOMAIN_RULES = [
  ['Timechain & Self-Model', ['timechain', 'ring', 'poq', 'modality', 'modalities', 'sense', 'senses', 'continuum', 'chronosynaptic', 'cambium', 'immune', 'self-model', 'recursive', 'genesis']],
  ['Code & Software', ['code', 'repo', 'repository', 'function', 'class', 'python', 'javascript', 'typescript', 'test', 'commit', 'git', 'source', 'linux', 'bitcoin', 'kubernetes']],
  ['Security & Audit', ['audit', 'vulnerability', 'exploit', 'tamper', 'risk', 'verify', 'verification', 'consensus', 'policy', 'rollback', 'compliance']],
  ['Finance & Markets', ['nasdaq', 'market', 'trading', 'trade', 'drawdown', 'price', 'volume', 'return', 'cagr', 'token', 'wallet', 'payment']],
  ['Blockchain & Web3', ['ethereum', 'base', 'erc20', 'wallet', 'transaction', 'contract', 'bitcoin', 'chain', 'block', 'hash', 'token', 'onchain']],
  ['Biology & Genomics', ['genome', 'dna', 'chromosome', 'sequence', 'entropy', 'gene', 'genomic', 'basepair', 'grch']],
  ['Data Science & Statistics', ['data', 'dataset', 'json', 'csv', 'statistics', 'quantile', 'distribution', 'outlier', 'regression', 'model']],
  ['Documents & Writing', ['document', 'report', 'readme', 'markdown', 'summary', 'poster', 'writing', 'changelog']],
  ['Design & Frontend', ['dashboard', 'frontend', 'ui', 'browser', 'react', 'css', 'layout', 'visual']],
  ['Operations & Packaging', ['release', 'package', 'zip', 'install', 'deploy', 'ci', 'selftest', 'version']],
  ['Law & Governance', ['legal', 'regulation', 'fiduciary', 'sec', 'finra', 'governance', 'compliance']],
  ['Research & Knowledge', ['research', 'paper', 'finding', 'evidence', 'hypothesis', 'analysis', 'source']],
];

async function buildDomains(rings, blockspace) {
  const domains = new Map();
  const add = (name, score, ring, term, tokens) => {
    if (!domains.has(name)) {
      domains.set(name, { name, score: 0, rings: new Set(), terms: new Map(), approxTokens: 0 });
    }
    const d = domains.get(name);
    d.score += score;
    d.approxTokens += tokens;
    if (ring != null) d.rings.add(ring);
    d.terms.set(term, (d.terms.get(term) || 0) + 1);
  };

  for (const ring of rings) {
    const text = ringText(ring).toLowerCase();
    const tokens = estimateTokens(text);
    for (const [domain, terms] of DOMAIN_RULES) {
      for (const term of terms) {
        const hits = text.split(term).length - 1;
        if (hits > 0) add(domain, hits, ring.index, term, tokens);
      }
    }
    const labels = ring.payload?.labels || {};
    for (const keyword of labels.keywords || []) {
      add(`Keyword: ${String(keyword).slice(0, 36)}`, 0.25, ring.index, keyword, Math.max(1, Math.round(tokens / 12)));
    }
    const data = ring.payload?.data || {};
    if (data.language) add(`Language: ${data.language}`, 2, ring.index, data.language, tokens);
    if (data.top_dir) add(`Top Dir: ${data.top_dir}`, 1, ring.index, data.top_dir, tokens);
    if (data.path_role) add(`Role: ${data.path_role}`, 1, ring.index, data.path_role, tokens);
  }

  for (const entry of blockspace.entries) {
    const textBits = [entry.filename, entry.mime].join(' ').toLowerCase();
    for (const [domain, terms] of DOMAIN_RULES) {
      for (const term of terms) {
        const hits = textBits.split(term).length - 1;
        if (hits > 0) add(domain, hits, null, term, estimateTokens(textBits));
      }
    }
    if (entry.size && entry.size <= DOMAIN_BLOB_TEXT_LIMIT && /^[0-9a-f]{64}$/i.test(entry.hash)) {
      try {
        const blobPath = ensureInsideRoot(path.join(timechainRoot, 'chain', 'blockspace', 'blobs', entry.hash));
        const buffer = await fs.readFile(blobPath);
        if (looksText(buffer)) {
          const text = buffer.toString('utf8').toLowerCase();
          for (const [domain, terms] of DOMAIN_RULES) {
            for (const term of terms) {
              const hits = text.split(term).length - 1;
              if (hits > 0) add(domain, Math.min(hits, 20), null, term, estimateTokens(text));
            }
          }
        }
      } catch {
        // Blob disappeared or is unreadable; integrity status will surface elsewhere.
      }
    }
  }

  return [...domains.values()]
    .filter((d) => d.score >= 1)
    .sort((a, b) => b.score - a.score)
    .slice(0, 10)
    .map((d) => ({
      name: d.name,
      score: Number(d.score.toFixed(2)),
      ringCount: d.rings.size,
      approxTokens: d.approxTokens,
      evidenceTerms: [...d.terms.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([term, count]) => ({ term, count })),
      sampleRings: [...d.rings].slice(0, 8),
    }));
}

function looksText(buffer) {
  if (!buffer.length) return true;
  const sample = buffer.subarray(0, Math.min(buffer.length, 4096));
  let suspicious = 0;
  for (const byte of sample) {
    if (byte === 0 || (byte < 7) || (byte > 14 && byte < 32)) suspicious += 1;
  }
  return suspicious / sample.length < 0.02;
}

async function buildSummary() {
  const [rings, registries, blockspace] = await Promise.all([loadRings(), loadRegistries(), loadBlockspace()]);
  const verification = await verifyChainWithPython();
  const latest = rings.at(-1) || null;
  const poqScores = rings.map((ring) => ring.poq?.brightness).filter((n) => typeof n === 'number');
  const continuumRings = rings.filter((ring) => ring.ring_type === 'continuum');
  const maxContinuumTokens = Math.max(0, ...continuumRings.map((ring) => ring.payload?.state?.metrics?.approx_tokens_ingested || 0));
  const domains = await buildDomains(rings, blockspace);

  return {
    root: timechainRoot,
    generatedAt: new Date().toISOString(),
    verification,
    stats: {
      rings: rings.length,
      modalities: registries.modalities.length,
      senses: registries.senses.length,
      emergent: registries.emergent.length,
      blockspaceEntries: blockspace.entries.length,
      blockspaceFiles: blockspace.blobFiles.length,
      blockspaceBytes: blockspace.totalBytes,
      blockspaceRefs: rings.reduce((sum, ring) => sum + (ring.blockspace_refs || []).length, 0),
      continuumBlocks: continuumRings.length,
      approxContinuumTokens: maxContinuumTokens,
      averageBrightness: poqScores.length ? poqScores.reduce((a, b) => a + b, 0) / poqScores.length : null,
    },
    latest: latest ? compactRing(latest) : null,
    ringTypes: countBy(rings, (ring) => ring.ring_type),
    modalityCategories: countBy(registries.modalities, (item) => item.category),
    senseCategories: countBy(registries.senses, (item) => item.category),
    domains,
  };
}

async function ringDetail(index) {
  const rings = await loadRings();
  const ring = rings.find((item) => Number(item.index) === Number(index));
  if (!ring) return null;
  const raw = JSON.stringify(ring);
  if (Buffer.byteLength(raw, 'utf8') > MAX_RING_DETAIL_BYTES) {
    return { ...compactRing(ring), payload: { notice: `Ring payload is larger than ${MAX_RING_DETAIL_BYTES} bytes; compact view only.` } };
  }
  return ring;
}

async function listRings(url) {
  const rings = await loadRings();
  const query = (url.searchParams.get('q') || '').toLowerCase();
  const type = url.searchParams.get('type') || '';
  const filtered = rings.filter((ring) => {
    if (type && ring.ring_type !== type) return false;
    if (!query) return true;
    return ringText(ring).toLowerCase().includes(query);
  });
  return {
    total: filtered.length,
    rings: filtered.map(compactRing).reverse(),
  };
}

async function listBlockspace() {
  const blockspace = await loadBlockspace();
  return {
    total: blockspace.entries.length,
    totalBytes: blockspace.totalBytes,
    entries: blockspace.entries.sort((a, b) => b.size - a.size),
  };
}

async function blobPreview(hash) {
  if (!/^[0-9a-f]{64}$/i.test(hash || '')) throw new Error('Invalid blockspace hash.');
  const blobPath = ensureInsideRoot(path.join(timechainRoot, 'chain', 'blockspace', 'blobs', hash));
  const stat = await fs.stat(blobPath);
  const buffer = await fs.readFile(blobPath);
  const actual = sha256Hex(buffer);
  const text = looksText(buffer);
  return {
    hash,
    size: stat.size,
    verified: actual === lower(hash),
    text,
    preview: text ? buffer.subarray(0, MAX_BLOB_PREVIEW_BYTES).toString('utf8') : '',
    truncated: text && buffer.length > MAX_BLOB_PREVIEW_BYTES,
  };
}

async function jsonBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_JSON_BODY_BYTES) {
      throw httpError('Request body too large.', 413);
    }
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString('utf8');
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    throw httpError('Invalid JSON request body.');
  }
}

function bridgeStatus(req) {
  const paired = Boolean(bridgeRecord(req));
  return {
    ok: true,
    bridge: 'cypher-tempre-local',
    host: HOST,
    port: PORT,
    paired,
    remoteOrigin: isRemoteOrigin(req),
    rootDetected: Boolean(timechainRoot),
    publicOrigins: [...PUBLIC_ORIGINS],
  };
}

function createBridgeToken() {
  const token = crypto.randomBytes(32).toString('hex');
  const now = Date.now();
  bridgeTokens.set(token, {
    token,
    createdAt: now,
    expiresAt: now + BRIDGE_TOKEN_TTL_MS,
    sessionId: null,
  });
  return token;
}

function sendJson(res, status, body) {
  res.writeHead(status, {
    ...securityHeaders(),
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  });
  res.end(JSON.stringify(body, null, 2));
}

async function serveStatic(req, res, url) {
  const rel = url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname.slice(1));
  const target = path.resolve(publicDir, rel);
  if (target !== publicDir && !target.startsWith(`${publicDir}${path.sep}`)) {
    sendJson(res, 403, { error: 'Forbidden' });
    return;
  }
  const file = fsSync.existsSync(target) && fsSync.statSync(target).isFile() ? target : path.join(publicDir, 'index.html');
  const ext = path.extname(file);
  const types = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.svg': 'image/svg+xml',
  };
  res.writeHead(200, {
    ...securityHeaders(),
    'content-type': types[ext] || 'application/octet-stream',
    'cache-control': 'no-store',
  });
  fsSync.createReadStream(file).pipe(res);
}

async function handle(req, res) {
  if (!allowedOrigin(req)) {
    sendJson(res, 403, { error: 'Cross-origin access denied.' });
    return;
  }
  applyCorsHeaders(req, res);
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      ...securityHeaders(),
      'cache-control': 'no-store',
    });
    res.end();
    return;
  }
  const url = new URL(req.url, `http://${req.headers.host || `${HOST}:${PORT}`}`);
  try {
    if (url.pathname === '/api/bridge/status') {
      sendJson(res, 200, bridgeStatus(req));
      return;
    }
    if (url.pathname === '/api/bridge/pair' && req.method === 'POST') {
      const body = await jsonBody(req);
      if (!pairingCodeMatches(body.code)) {
        const error = new Error('Pairing code did not match this local bridge.');
        error.status = 401;
        throw error;
      }
      const bridgeToken = createBridgeToken();
      sendJson(res, 200, {
        ok: true,
        paired: true,
        bridgeToken,
        expiresInSeconds: Math.floor(BRIDGE_TOKEN_TTL_MS / 1000),
      });
      return;
    }
    requireBridgePairing(req);
    const session = getSession(req, res);
    if (url.pathname === '/api/timechain/summary') {
      sendJson(res, 200, await buildSummary());
      return;
    }
    if (url.pathname === '/api/learning/overview') {
      sendJson(res, 200, await buildLearningOverview());
      return;
    }
    if (url.pathname === '/api/timechain/rings') {
      sendJson(res, 200, await listRings(url));
      return;
    }
    const ringMatch = url.pathname.match(/^\/api\/timechain\/rings\/(\d+)$/);
    if (ringMatch) {
      const ring = await ringDetail(ringMatch[1]);
      if (!ring) sendJson(res, 404, { error: 'Ring not found.' });
      else sendJson(res, 200, ring);
      return;
    }
    if (url.pathname === '/api/blockspace') {
      sendJson(res, 200, await listBlockspace());
      return;
    }
    const blobMatch = url.pathname.match(/^\/api\/blockspace\/([0-9a-fA-F]{64})$/);
    if (blobMatch) {
      sendJson(res, 200, await blobPreview(blobMatch[1]));
      return;
    }
    if (url.pathname.startsWith('/api/')) {
      sendJson(res, 404, { error: 'Not found.' });
      return;
    }
    await serveStatic(req, res, url);
  } catch (error) {
    sendJson(res, error.status || 500, { error: error.message || 'Unexpected error.' });
  }
}

timechainRoot = await discoverTimechainRoot();
const server = http.createServer((req, res) => {
  handle(req, res).catch((error) => sendJson(res, 500, { error: error.message || 'Unexpected error.' }));
});

server.on('error', (error) => {
  console.error(`Dashboard server failed to listen on ${HOST}:${PORT}: ${error.message}`);
  process.exitCode = 1;
});

server.listen(PORT, HOST, () => {
  console.log(`Cypher Tempre Dashboard listening on http://${HOST}:${PORT}`);
  console.log(`Timechain root: ${timechainRoot}`);
  console.log('Audit is free, local, and private: no payment gate, no accounts, no outbound network calls.');
  console.log(`Public origins: ${[...PUBLIC_ORIGINS].join(', ')}`);
  console.log(`Bridge pairing code: ${displayPairingCode(BRIDGE_PAIR_CODE)}`);
  console.log('Enter that pairing code on cyphertempre.ai to connect this local bridge.');
});
