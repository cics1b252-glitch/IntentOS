import assert from 'node:assert';
import test, { describe, it } from 'node:test';
import fs from 'fs';
import path from 'path';
import { IntentGatewayAdapter } from '../dist/gateway/adapter.js';
import { LocalProcessTransport } from '../dist/gateway/transport.js';
import {
  preserveCognitiveProductResponse,
  transportFailureProductResponse,
} from '../dist/gateway/product-response.js';

function canonicalProductResponse(overrides = {}) {
  const base = {
    product_contract_version: '1.0',
    text: 'canonical',
    status: 'UNKNOWN',
    execution_mode: 'UNKNOWN',
    epistemic_status: 'unknown',
    confidence: 1,
    response_origin: 'COGNITIVE_RUNTIME',
    provider: null,
    provider_called: false,
    resource_provenance: [],
    mission_id: null,
    verification_evidence: [],
    limitations: [],
    missing_capabilities: ['knowledge.lookup'],
    authorization_requirements: [],
    next_actions: [],
    ok: true,
    presentation: {
      visible_state: 'UNKNOWN',
      title: 'Informação desconhecida',
      tone: 'uncertain',
      response_origin: 'COGNITIVE_RUNTIME',
      show_provider_execution: false,
      show_mission: false,
      show_missing_capabilities: true,
      requires_authorization: false,
      requires_confirmation: false,
      suggested_actions: [],
      interactive_actions: [],
    },
    response_authority: 'CognitiveResponseAssembler',
    product_presentation_authority: 'CognitiveProductPresenter',
    compatibility_path_used: false,
    compatibility_traces: [],
  };
  return { ...base, ...overrides };
}

describe('Intent Gateway Adapter & Transport Tests', () => {
  it('should initialize LocalProcessTransport and complete handshake', async () => {
    const transport = new LocalProcessTransport('python3', 'product_bridge.py');
    await transport.start();
    const status = transport.getStatus();
    assert.strictEqual(status.ready, true);
    assert.strictEqual(status.mode, 'connected');
    await transport.stop();
  });

  it('should send request and receive JSON response', async () => {
    const transport = new LocalProcessTransport('python3', 'product_bridge.py');
    await transport.start();
    const response = await transport.sendRequest('status');
    assert.strictEqual(response.ok, true);
    assert.strictEqual(response.kernel, 'pronto');
    assert.ok(Array.isArray(response.providers));
    await transport.stop();
  });

  it('should preserve UTF-8 character encoding', async () => {
    const transport = new LocalProcessTransport('python3', 'product_bridge.py');
    await transport.start();
    const response = await transport.sendRequest('intent', { message: 'Acentuação Portuguesa: Ação, Configuração, Solução' });
    assert.strictEqual(typeof response.ok, 'boolean');
    await transport.stop();
  });

  it('should handle unavailable process / error gracefully', async () => {
    const transport = new LocalProcessTransport('python3', 'non_existent_script.py');
    await transport.start();
    const status = transport.getStatus();
    assert.strictEqual(status.ready, false);
    assert.strictEqual(status.mode, 'unavailable');

    const response = await transport.sendRequest('status');
    assert.strictEqual(response.ok, false);
    assert.strictEqual(response.mode, 'unavailable');
    assert.strictEqual(response.message, 'Kernel externo indisponível neste ambiente');
    await transport.stop();
  });

  it('should support Gateway Adapter discovery methods', async () => {
    const adapter = new IntentGatewayAdapter();
    await adapter.init();

    const status = await adapter.getStatus();
    assert.strictEqual(status.mode, 'connected');

    const providers = await adapter.getProviders();
    assert.strictEqual(providers.ok, true);
    assert.ok(Array.isArray(providers.available));

    const coreApps = await adapter.getCoreApps();
    assert.strictEqual(coreApps.ok, true);
    assert.ok(Array.isArray(coreApps.modules));

    const constitution = await adapter.getConstitution();
    assert.strictEqual(constitution.ok, true);
    assert.ok(constitution.version);

    const diagnostics = await adapter.getDiagnostics();
    assert.strictEqual(diagnostics.ok, true);
    assert.ok(diagnostics.trace);

    await adapter.stop();
  });

  it('should support Gateway Adapter IUE analysis method', async () => {
    const adapter = new IntentGatewayAdapter();
    await adapter.init();

    const iueResult = await adapter.understandIntent({ text: 'Quero investir 23.500' });
    assert.strictEqual(iueResult.ok, true);
    assert.ok(iueResult.structured_intent);
    assert.strictEqual(iueResult.structured_intent.domain, 'finance');
    assert.ok(iueResult.structured_intent.intent_quality_index);
    if (iueResult.current_state === 'WAITING_CONTEXT') {
      assert.strictEqual(iueResult.execution_plan, null);
    } else {
      assert.ok(iueResult.execution_plan);
    }

    const planResult = await adapter.createPlan({ text: 'Quero investir 23.500' });
    assert.strictEqual(planResult.ok, true);
    if (planResult.current_state === 'WAITING_CONTEXT') {
      assert.strictEqual(planResult.execution_plan, null);
    } else {
      assert.ok(planResult.execution_plan);
      assert.ok(Array.isArray(planResult.execution_plan.steps));
    }

    await adapter.stop();
  });

  it('structural check: server.ts must not contain cognitive business logic', () => {
    const serverContent = fs.readFileSync(path.join(process.cwd(), 'server.ts'), 'utf-8');
    
    // Server must not instantiate Gemini SDK, OpenAI SDK, or cognitive logic
    assert.doesNotMatch(serverContent, /new GoogleGenerativeAI/i);
    assert.doesNotMatch(serverContent, /new OpenAI/i);
    assert.doesNotMatch(serverContent, /class MissionEngine/i);
    assert.doesNotMatch(serverContent, /class ProviderManager/i);

    // Server must use Gateway endpoints and adapter
    assert.match(serverContent, /\/api\/status/);
    assert.match(serverContent, /\/api\/intent/);
    assert.match(serverContent, /\/api\/iue/);
    assert.match(serverContent, /\/api\/mission/);
    assert.match(serverContent, /\/api\/providers/);
    assert.match(serverContent, /\/api\/core-apps/);
    assert.match(serverContent, /\/api\/constitution/);
    assert.match(serverContent, /\/api\/diagnostics/);
    assert.match(serverContent, /gatewayAdapter/);
  });

  it('preserves canonical statuses instead of collapsing them into ok/error', () => {
    for (const status of [
      'COMPLETED', 'WAITING_CONTEXT', 'UNKNOWN', 'BLOCKED',
      'AUTHORIZATION_REQUIRED', 'EXTERNAL_RESOURCE_REQUIRED',
      'WAITING_CONFIRMATION', 'FAILED',
    ]) {
      const raw = canonicalProductResponse({
        status,
        execution_mode: status === 'COMPLETED' ? 'CONVERSATION' : status,
        ok: status !== 'FAILED',
        presentation: {
          ...canonicalProductResponse().presentation,
          visible_state: status,
          requires_authorization: status === 'AUTHORIZATION_REQUIRED',
          requires_confirmation: status === 'WAITING_CONFIRMATION',
        },
      });
      assert.strictEqual(preserveCognitiveProductResponse(raw).status, status);
    }
  });

  it('rejects fabricated provider and Mission evidence', () => {
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      provider: 'mock',
      resource_provenance: ['provider:mock'],
    })), /provider_evidence_fabricated/);

    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      status: 'COMPLETED',
      execution_mode: 'MISSION',
      mission_id: 'forged',
      presentation: {
        ...canonicalProductResponse().presentation,
        visible_state: 'COMPLETED',
        show_mission: true,
      },
    })), /unverified_mission_completion/);
  });

  it('keeps authorization and confirmation distinct', () => {
    const authorization = canonicalProductResponse({
      status: 'AUTHORIZATION_REQUIRED',
      execution_mode: 'AUTHORIZATION_REQUIRED',
      presentation: {
        ...canonicalProductResponse().presentation,
        visible_state: 'AUTHORIZATION_REQUIRED',
        requires_authorization: true,
      },
    });
    const confirmation = canonicalProductResponse({
      status: 'WAITING_CONFIRMATION',
      execution_mode: 'MISSION',
      presentation: {
        ...canonicalProductResponse().presentation,
        visible_state: 'WAITING_CONFIRMATION',
        requires_confirmation: true,
      },
    });
    assert.strictEqual(preserveCognitiveProductResponse(authorization).presentation.requires_confirmation, false);
    assert.strictEqual(preserveCognitiveProductResponse(confirmation).presentation.requires_authorization, false);
  });

  it('creates one explicit product contract for transport failures', () => {
    const response = transportFailureProductResponse('offline', 'gateway_unavailable');
    assert.strictEqual(response.status, 'FAILED');
    assert.strictEqual(response.execution_mode, 'FAILED');
    assert.strictEqual(response.provider_called, false);
    assert.strictEqual(response.mission_id, null);
    assert.strictEqual(response.transport_failure, true);
    assert.strictEqual(response.presentation.visible_state, 'FAILED');
  });

  it('frontend consumes presentation state and escapes visible response text', () => {
    const html = fs.readFileSync(
      path.join(process.cwd(), 'intent_os_desktop', 'static', 'index.html'),
      'utf-8',
    );
    assert.doesNotMatch(html, /if \(data\.ok && data\.text\)/);
    assert.match(html, /data\.presentation/);
    assert.match(html, /escapeProductText\(data\.text\)/);
    assert.match(html, /view\.show_provider_execution/);
    assert.match(html, /view\.requires_confirmation/);
  });
});
