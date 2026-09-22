import express, { Request, Response, NextFunction } from 'express';
import path from 'path';
import crypto from 'crypto';
import { IntentGatewayAdapter } from './gateway/adapter.js';
import { transportFailureProductResponse } from './gateway/product-response.js';

const PORT = parseInt(process.env.PORT || '3000', 10);
const HOST = '0.0.0.0';

// ---------------------------------------------------------------------------
// M33.2C — Hardened ingress authentication (parity with FastAPI boundary)
// ---------------------------------------------------------------------------

const RESERVED_CONTEXT_KEYS = new Set([
  '_authenticated_caller', 'caller', 'authorization', 'bearer',
  'token', 'api_key', 'apikey', 'credential', 'secret',
]);

function sanitizeContextForGateway(context: any): any {
  if (!context || typeof context !== 'object' || Array.isArray(context)) return context;
  const lowerReserved = new Set([...RESERVED_CONTEXT_KEYS].map(k => k.toLowerCase()));
  const clean: Record<string, any> = {};
  for (const [k, v] of Object.entries(context)) {
    if (!lowerReserved.has(k.toLowerCase())) clean[k] = v;
  }
  return clean;
}

function credentialReferenceFor(rawKey: string): string {
  return `api_key:${crypto.createHash('sha256').update(rawKey, 'utf8').digest('hex').slice(0, 16)}`;
}

function authenticateRequest(req: Request): { callerId: string; reference: string } | null {
  const expected = process.env.INTENT_OS_API_KEY;
  const allowAnonymous =
    (process.env.INTENT_OS_ALLOW_ANONYMOUS || '').trim().toLowerCase() === 'true';
  const hasKey = !!expected && expected.trim() !== '';

  if (!hasKey) {
    if (allowAnonymous) return { callerId: 'anonymous', reference: 'anonymous' };
    return null; // fail-closed: no key configured and anonymous not allowed
  }

  const auth = req.headers.authorization;
  if (!auth || typeof auth !== 'string' || !auth.startsWith('Bearer ')) return null;
  const token = auth.slice(7);
  if (!token || token !== token.trim() || token.includes(' ') || token.includes('\t') || token.includes('\n')) return null;
  if (token.startsWith('Bearer ')) return null;
  // Constant-time compare (length check first to avoid timing oracle on length, then timingSafeEqual on padded buffers is not needed — compare_digest handles length mismatch in constant time via Node's timingSafeEqual on equal-length buffers; we do length-guarded compare).
  const a = Buffer.from(token, 'utf8');
  const b = Buffer.from(expected, 'utf8');
  if (a.length !== b.length) return null;
  if (!crypto.timingSafeEqual(a, b)) return null;
  const ref = credentialReferenceFor(expected);
  return { callerId: ref, reference: ref };
}

function requireAuth(req: Request, res: Response, next: NextFunction) {
  const expected = process.env.INTENT_OS_API_KEY;
  const hasKey = !!expected && expected.trim() !== '';
  const allowAnonymous =
    (process.env.INTENT_OS_ALLOW_ANONYMOUS || '').trim().toLowerCase() === 'true';
  if (!hasKey && !allowAnonymous) {
    return res.status(503).json({ ok: false, error: 'Authentication is not configured: set INTENT_OS_API_KEY or explicitly enable anonymous access with INTENT_OS_ALLOW_ANONYMOUS=true for development.' });
  }
  if (!hasKey && allowAnonymous) {
    (req as any)._authenticatedCaller = {
      caller_id: 'anonymous', credential_class: 'anonymous',
      validation_result: 'anonymous', credential_reference: 'anonymous',
      authenticated_at: new Date().toISOString(),
    };
    return next();
  }
  const result = authenticateRequest(req);
  if (!result) {
    const auth = req.headers.authorization;
    if (!auth) return res.status(401).json({ ok: false, error: 'Authorization header required' });
    return res.status(401).json({ ok: false, error: 'Invalid API key' });
  }
  (req as any)._authenticatedCaller = {
    caller_id: result.callerId, credential_class: 'api_key',
    validation_result: 'valid', credential_reference: result.reference,
    authenticated_at: new Date().toISOString(),
  };
  next();
}

const app = express();

// Instantiate Intent Gateway Adapter (Transport: LocalProcessTransport -> product_bridge.py)
const gatewayAdapter = new IntentGatewayAdapter();

// Initialize Gateway Transport
gatewayAdapter.init().then(() => {
  console.log('🧠 Intent Gateway Adapter initialized');
}).catch((err) => {
  console.error('❌ Failed to initialize Intent Gateway Adapter:', err);
});

// Skip AI Studio internal control plane paths
app.use((req: Request, res: Response, next: NextFunction) => {
  if (req.path.startsWith('/__aistudio')) {
    return next('route');
  }
  next();
});

// JSON Body Parser for API requests
app.use('/api', express.json());

// --- INTENT GATEWAY ENDPOINTS (RFC-0006) ---

// GET /api/status
app.get('/api/status', async (req: Request, res: Response) => {
  try {
    const status = await gatewayAdapter.getStatus();
    res.json(status);
  } catch (err: any) {
    res.status(500).json({ ok: false, mode: 'unavailable', error: err.message });
  }
});

// POST /api/intent — effect-capable, authenticated (M33.2C)
app.post('/api/intent', requireAuth, async (req: Request, res: Response) => {
  try {
    const body = req.body || {};
    const cleanContext = sanitizeContextForGateway(body.context);
    const result = await gatewayAdapter.processIntent({
      ...body,
      context: cleanContext,
      _authenticated_caller: (req as any)._authenticatedCaller,
    });
    res.json(result);
  } catch (err: any) {
    res.status(500).json(transportFailureProductResponse(
      'Falha ao transportar a resposta cognitiva.',
      'intent_gateway_exception',
    ));
  }
});

// POST /api/iue (Intent Understanding Engine - RFC-0007)
app.post('/api/iue', async (req: Request, res: Response) => {
  try {
    const result = await gatewayAdapter.understandIntent(req.body || {});
    res.json(result);
  } catch (err: any) {
    res.status(500).json({ ok: false, mode: 'unavailable', error: err.message });
  }
});

// POST /api/cdm (Cognitive Dialogue Manager - RFC-0008)
app.post('/api/cdm', async (req: Request, res: Response) => {
  try {
    const result = await gatewayAdapter.evaluateDialogue(req.body || {});
    res.json(result);
  } catch (err: any) {
    res.status(500).json({ ok: false, mode: 'unavailable', error: err.message });
  }
});

// POST /api/plan (Cognitive Planning Engine - RFC-0009)
app.post('/api/plan', async (req: Request, res: Response) => {
  try {
    const result = await gatewayAdapter.createPlan(req.body || {});
    res.json(result);
  } catch (err: any) {
    res.status(500).json({ ok: false, mode: 'unavailable', error: err.message });
  }
});

// POST /api/orchestrate (Capability Orchestrator - RFC-0010)
app.post('/api/orchestrate', async (req: Request, res: Response) => {
  try {
    const result = await gatewayAdapter.orchestrate(req.body || {});
    res.json(result);
  } catch (err: any) {
    res.status(500).json({ ok: false, mode: 'unavailable', error: err.message });
  }
});

app.post('/api/cor', async (req: Request, res: Response) => {
  try {
    const result = await gatewayAdapter.orchestrate(req.body || {});
    res.json(result);
  } catch (err: any) {
    res.status(500).json({ ok: false, mode: 'unavailable', error: err.message });
  }
});

// POST /api/ecc (Executive Cognitive Controller - RFC-0011)
app.post('/api/ecc', async (req: Request, res: Response) => {
  try {
    const result = await gatewayAdapter.executePipeline(req.body || {});
    res.json(result);
  } catch (err: any) {
    res.status(500).json({ ok: false, mode: 'unavailable', error: err.message });
  }
});

app.post('/api/executive', async (req: Request, res: Response) => {
  try {
    const result = await gatewayAdapter.executePipeline(req.body || {});
    res.json(result);
  } catch (err: any) {
    res.status(500).json({ ok: false, mode: 'unavailable', error: err.message });
  }
});

// POST /api/mission
app.post('/api/mission', async (req: Request, res: Response) => {
  try {
    const result = await gatewayAdapter.manageMission(req.body || {});
    res.json(result);
  } catch (err: any) {
    res.status(500).json({ ok: false, mode: 'unavailable', error: err.message });
  }
});

// GET /api/providers
app.get('/api/providers', async (req: Request, res: Response) => {
  try {
    const result = await gatewayAdapter.getProviders();
    res.json(result);
  } catch (err: any) {
    res.status(500).json({ ok: false, mode: 'unavailable', error: err.message });
  }
});

// GET /api/core-apps
app.get('/api/core-apps', async (req: Request, res: Response) => {
  try {
    const result = await gatewayAdapter.getCoreApps();
    res.json(result);
  } catch (err: any) {
    res.status(500).json({ ok: false, mode: 'unavailable', error: err.message });
  }
});

// GET /api/constitution
app.get('/api/constitution', async (req: Request, res: Response) => {
  try {
    const result = await gatewayAdapter.getConstitution();
    res.json(result);
  } catch (err: any) {
    res.status(500).json({ ok: false, mode: 'unavailable', error: err.message });
  }
});

// GET /api/diagnostics
app.get('/api/diagnostics', async (req: Request, res: Response) => {
  try {
    const result = await gatewayAdapter.getDiagnostics();
    res.json(result);
  } catch (err: any) {
    res.status(500).json({ ok: false, mode: 'unavailable', error: err.message });
  }
});

// --- LEGACY BACKWARDS COMPATIBILITY ALIASES ---

app.get('/api/v1/status', async (req: Request, res: Response) => {
  const status = await gatewayAdapter.getStatus();
  res.json(status);
});

app.post('/api/v1/process', requireAuth, async (req: Request, res: Response) => {
  const body = req.body || {};
  const cleanContext = sanitizeContextForGateway(body.context);
  const result = await gatewayAdapter.processIntent({
    ...body,
    context: cleanContext,
    _authenticated_caller: (req as any)._authenticatedCaller,
  });
  res.json(result);
});

// --- STATIC ASSETS ---
app.use(express.static(path.join(process.cwd(), 'intent_os_desktop', 'static')));
app.use('/ui/shell', express.static(path.join(process.cwd(), 'ui', 'shell')));
app.use('/ui/ids', express.static(path.join(process.cwd(), 'ui', 'ids')));

// Fallback to static index.html for UI navigation
app.get('*', (req: Request, res: Response) => {
  res.sendFile(path.join(process.cwd(), 'intent_os_desktop', 'static', 'index.html'));
});

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('SIGTERM received, stopping Gateway Adapter...');
  await gatewayAdapter.stop();
  process.exit(0);
});

process.on('SIGINT', async () => {
  console.log('SIGINT received, stopping Gateway Adapter...');
  await gatewayAdapter.stop();
  process.exit(0);
});

// Start Express Server
app.listen(PORT, HOST, () => {
  console.log(`🧠 Intent OS Gateway Server running on http://${HOST}:${PORT}`);
});
