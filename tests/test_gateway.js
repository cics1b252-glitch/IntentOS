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
  const status = overrides.status || 'UNKNOWN';
  const presentationByStatus = {
    COMPLETED: ['Resposta', 'neutral'],
    WAITING_CONTEXT: ['Contexto necessário', 'attention'],
    UNKNOWN: ['Informação desconhecida', 'uncertain'],
    BLOCKED: ['Solicitação bloqueada', 'blocked'],
    AUTHORIZATION_REQUIRED: ['Autorização necessária', 'authorization'],
    EXTERNAL_RESOURCE_REQUIRED: ['Recurso externo necessário', 'resource'],
    WAITING_CONFIRMATION: ['Confirmação necessária', 'confirmation'],
    FAILED: ['Falha de execução', 'error'],
  };
  const expectedOkByStatus = {
    COMPLETED: true,
    WAITING_CONTEXT: false,
    UNKNOWN: false,
    BLOCKED: false,
    AUTHORIZATION_REQUIRED: false,
    EXTERNAL_RESOURCE_REQUIRED: false,
    WAITING_CONFIRMATION: false,
    FAILED: false,
  };
  const missingCapabilities = overrides.missing_capabilities || ['knowledge.lookup'];
  const nextActions = overrides.next_actions || [];
  const base = {
    product_contract_version: '1.0',
    text: 'canonical',
    status,
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
    missing_capabilities: missingCapabilities,
    authorization_requirements: [],
    next_actions: nextActions,
    ok: expectedOkByStatus[status],
    presentation: {
      visible_state: status,
      title: presentationByStatus[status][0],
      tone: presentationByStatus[status][1],
      response_origin: 'COGNITIVE_RUNTIME',
      show_provider_execution: false,
      show_mission: false,
      show_missing_capabilities: missingCapabilities.length > 0,
      requires_authorization: status === 'AUTHORIZATION_REQUIRED',
      requires_confirmation: status === 'WAITING_CONFIRMATION',
      suggested_actions: nextActions,
      interactive_actions: [],
    },
    response_authority: 'CognitiveResponseAssembler',
    product_presentation_authority: 'CognitiveProductPresenter',
    compatibility_path_used: false,
    compatibility_traces: [],
  };
  return {
    ...base,
    ...overrides,
    presentation: {...base.presentation, ...(overrides.presentation || {})},
  };
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
      const executionMode = {
        COMPLETED: 'CONVERSATION',
        WAITING_CONTEXT: 'CONVERSATION',
        UNKNOWN: 'UNKNOWN',
        BLOCKED: 'BLOCKED',
        AUTHORIZATION_REQUIRED: 'AUTHORIZATION_REQUIRED',
        EXTERNAL_RESOURCE_REQUIRED: 'EXTERNAL_REASONING_REQUIRED',
        WAITING_CONFIRMATION: 'MISSION',
        FAILED: 'FAILED',
      }[status];
      const raw = canonicalProductResponse({
        status,
        execution_mode: executionMode,
        ok: status === 'COMPLETED',
        mission_id: status === 'WAITING_CONFIRMATION' ? 'mission-matrix' : null,
        presentation: status === 'WAITING_CONFIRMATION' ? {show_mission: true} : {},
      });
      assert.strictEqual(preserveCognitiveProductResponse(raw).status, status);
    }
  });

  it('enforces the complete canonical successful-fulfillment ok matrix', () => {
    const modes = {
      COMPLETED: 'CONVERSATION',
      WAITING_CONTEXT: 'CONVERSATION',
      UNKNOWN: 'UNKNOWN',
      BLOCKED: 'BLOCKED',
      AUTHORIZATION_REQUIRED: 'AUTHORIZATION_REQUIRED',
      EXTERNAL_RESOURCE_REQUIRED: 'EXTERNAL_REASONING_REQUIRED',
      WAITING_CONFIRMATION: 'MISSION',
      FAILED: 'FAILED',
    };
    for (const status of Object.keys(modes)) {
      const expectedOk = status === 'COMPLETED';
      const valid = canonicalProductResponse({
        status,
        execution_mode: modes[status],
        ok: expectedOk,
        mission_id: status === 'WAITING_CONFIRMATION' ? 'mission-ok-matrix' : null,
        presentation: status === 'WAITING_CONFIRMATION' ? {show_mission: true} : {},
      });
      assert.strictEqual(preserveCognitiveProductResponse(valid).ok, expectedOk);
      assert.throws(
        () => preserveCognitiveProductResponse({...valid, ok: !expectedOk}),
        /ok_status_mismatch/,
      );
    }
  });

  it('rejects fabricated provider and Mission evidence', () => {
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      provider: 'mock',
    })), /provider_selection_presented_as_invocation/);

    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      provider: 'mock',
      resource_provenance: ['provider:mock'],
    })), /provider_evidence_fabricated/);

    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      status: 'COMPLETED',
      execution_mode: 'MISSION',
      mission_id: 'forged',
      presentation: {show_mission: true},
    })), /unverified_mission_completion/);
  });

  it('keeps authorization and confirmation distinct', () => {
    const authorization = canonicalProductResponse({
      status: 'AUTHORIZATION_REQUIRED',
      execution_mode: 'AUTHORIZATION_REQUIRED',
      presentation: {requires_authorization: true},
    });
    const confirmation = canonicalProductResponse({
      status: 'WAITING_CONFIRMATION',
      execution_mode: 'MISSION',
      mission_id: 'mission-confirmation',
      presentation: {show_mission: true, requires_confirmation: true},
    });
    assert.strictEqual(preserveCognitiveProductResponse(authorization).presentation.requires_confirmation, false);
    assert.strictEqual(preserveCognitiveProductResponse(confirmation).presentation.requires_authorization, false);
  });

  it('rejects hidden authorization and success presentation for authorization-required', () => {
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      status: 'AUTHORIZATION_REQUIRED',
      execution_mode: 'AUTHORIZATION_REQUIRED',
      authorization_requirements: ['tool.email'],
      presentation: {requires_authorization: false},
    })), /authorization_presentation_mismatch/);
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      status: 'AUTHORIZATION_REQUIRED',
      execution_mode: 'AUTHORIZATION_REQUIRED',
      authorization_requirements: ['tool.email'],
      presentation: {title: 'Concluído'},
    })), /presentation_title_mismatch/);
  });

  it('rejects invented interactive and suggested actions', () => {
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      status: 'AUTHORIZATION_REQUIRED',
      execution_mode: 'AUTHORIZATION_REQUIRED',
      authorization_requirements: ['tool.email'],
      next_actions: [],
      presentation: {interactive_actions: ['execute']},
    })), /unsupported_interactive_actions/);
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      status: 'BLOCKED',
      execution_mode: 'BLOCKED',
      missing_capabilities: [],
      next_actions: [],
      presentation: {suggested_actions: ['Executar agora']},
    })), /suggested_actions_mismatch/);
  });

  it('rejects hidden missing capabilities', () => {
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      status: 'EXTERNAL_RESOURCE_REQUIRED',
      execution_mode: 'EXTERNAL_REASONING_REQUIRED',
      missing_capabilities: ['external.reasoning'],
      presentation: {show_missing_capabilities: false},
    })), /missing_capabilities_presentation_mismatch/);
  });

  it('rejects success titles and status-mode-ok contradictions', () => {
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      presentation: {title: 'Concluído'},
    })), /presentation_title_mismatch/);
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      status: 'FAILED', execution_mode: 'FAILED', missing_capabilities: [], ok: true,
    })), /ok_status_mismatch/);
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      status: 'FAILED', execution_mode: 'CONVERSATION', missing_capabilities: [],
    })), /execution_mode_status_mismatch/);
  });

  it('rejects unknown and external-resource execution fabrication', () => {
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      provider: 'mock', provider_called: true, resource_provenance: ['provider:mock'],
      presentation: {show_provider_execution: true},
    })), /unknown_semantic_override/);
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      mission_id: 'forged', presentation: {show_mission: true},
    })), /unknown_semantic_override/);
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      status: 'EXTERNAL_RESOURCE_REQUIRED', execution_mode: 'EXTERNAL_REASONING_REQUIRED',
      provider: 'mock', provider_called: true, resource_provenance: ['provider:mock'],
      presentation: {show_provider_execution: true},
    })), /external_resource_provider_override/);
  });

  it('requires confirmation to remain Mission-bound and distinct', () => {
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      status: 'WAITING_CONFIRMATION', execution_mode: 'MISSION', missing_capabilities: [],
    })), /confirmation_without_mission/);
    const valid = canonicalProductResponse({
      status: 'WAITING_CONFIRMATION', execution_mode: 'MISSION', missing_capabilities: [],
      mission_id: 'mission-1', presentation: {show_mission: true},
    });
    assert.strictEqual(preserveCognitiveProductResponse(valid).presentation.requires_confirmation, true);
    assert.strictEqual(preserveCognitiveProductResponse(valid).presentation.requires_authorization, false);
  });

  it('requires compatibility participation evidence to agree', () => {
    assert.throws(() => preserveCognitiveProductResponse(canonicalProductResponse({
      compatibility_path_used: true, compatibility_traces: [],
    })), /compatibility_trace_mismatch/);
    const trace = {compatibility_component: 'ModuleRouter', reason: 'executed'};
    const valid = canonicalProductResponse({
      compatibility_path_used: true, compatibility_traces: [trace],
    });
    assert.deepStrictEqual(preserveCognitiveProductResponse(valid).compatibility_traces, [trace]);
  });

  it('fails closed through the adapter on contradictory presentation', async () => {
    const contradictory = canonicalProductResponse({
      status: 'AUTHORIZATION_REQUIRED',
      execution_mode: 'AUTHORIZATION_REQUIRED',
      authorization_requirements: ['tool.email'],
      next_actions: [],
      presentation: {
        title: 'Concluído', tone: 'neutral', requires_authorization: false,
        show_missing_capabilities: false, suggested_actions: ['Executar agora'],
        interactive_actions: ['execute'],
      },
    });
    const transport = {
      start: async () => {}, stop: async () => {},
      getStatus: () => ({ready: true, mode: 'connected'}),
      sendRequest: async () => contradictory,
    };
    const result = await new IntentGatewayAdapter(transport).processIntent({message: 'x'});
    assert.strictEqual(result.status, 'FAILED');
    assert.strictEqual(result.presentation.visible_state, 'FAILED');
    assert.strictEqual(result.presentation.requires_authorization, false);
    assert.deepStrictEqual(result.presentation.suggested_actions, []);
    assert.deepStrictEqual(result.presentation.interactive_actions, []);
    assert.match(result.error_code, /^product_contract_violation:/);
  });

  it('accepts a valid canonical product presentation unchanged', () => {
    const canonical = canonicalProductResponse({
      status: 'AUTHORIZATION_REQUIRED',
      execution_mode: 'AUTHORIZATION_REQUIRED',
      authorization_requirements: ['tool.email'],
      next_actions: ['Solicitar autorização'],
    });
    assert.strictEqual(preserveCognitiveProductResponse(canonical), canonical);
  });

  it('ignores context-like metadata without shadowing reserved fields', () => {
    const canonical = canonicalProductResponse({
      context: {
        status: 'COMPLETED', title: 'Concluído',
        presentation: {interactive_actions: ['execute']},
      },
    });
    const result = preserveCognitiveProductResponse(canonical);
    assert.strictEqual(result.status, 'UNKNOWN');
    assert.strictEqual(result.presentation.title, 'Informação desconhecida');
    assert.deepStrictEqual(result.presentation.interactive_actions, []);
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
