import express, { Request, Response, NextFunction } from 'express';
import path from 'path';
import { IntentGatewayAdapter } from './gateway/adapter.js';
import { transportFailureProductResponse } from './gateway/product-response.js';

const PORT = parseInt(process.env.PORT || '3000', 10);
const HOST = '0.0.0.0';

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

// POST /api/intent
app.post('/api/intent', async (req: Request, res: Response) => {
  try {
    const result = await gatewayAdapter.processIntent(req.body || {});
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

app.post('/api/v1/process', async (req: Request, res: Response) => {
  const result = await gatewayAdapter.processIntent(req.body || {});
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
