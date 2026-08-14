export type CognitiveResponseStatus =
  | 'COMPLETED'
  | 'WAITING_CONTEXT'
  | 'UNKNOWN'
  | 'BLOCKED'
  | 'AUTHORIZATION_REQUIRED'
  | 'EXTERNAL_RESOURCE_REQUIRED'
  | 'WAITING_CONFIRMATION'
  | 'FAILED';

export type ResponseOrigin =
  | 'COGNITIVE_RUNTIME'
  | 'LOCAL_RESPONSE'
  | 'CONVERSATION'
  | 'MEMORY'
  | 'MISSION'
  | 'PROVIDER'
  | 'SYSTEM'
  | 'LEGACY_COMPATIBILITY';

export interface ProductPresentation {
  visible_state: CognitiveResponseStatus;
  title: string;
  tone: string;
  response_origin: ResponseOrigin;
  show_provider_execution: boolean;
  show_mission: boolean;
  show_missing_capabilities: boolean;
  requires_authorization: boolean;
  requires_confirmation: boolean;
  suggested_actions: string[];
  interactive_actions: string[];
}

export interface CognitiveProductResponse {
  product_contract_version: '1.0';
  text: string;
  status: CognitiveResponseStatus;
  execution_mode: string;
  epistemic_status: string;
  confidence: number;
  response_origin: ResponseOrigin;
  provider: string | null;
  provider_called: boolean;
  resource_provenance: string[];
  mission_id: string | null;
  verification_evidence: Record<string, unknown>[];
  limitations: string[];
  missing_capabilities: string[];
  authorization_requirements: string[];
  next_actions: string[];
  ok: boolean;
  presentation: ProductPresentation;
  response_authority: 'CognitiveResponseAssembler';
  product_presentation_authority: 'CognitiveProductPresenter';
  compatibility_path_used: boolean;
  compatibility_traces: Record<string, unknown>[];
  error_code?: string;
  transport_failure?: boolean;
  gateway_mode?: 'connected' | 'unavailable';
  [key: string]: unknown;
}

const STATUSES = new Set<CognitiveResponseStatus>([
  'COMPLETED',
  'WAITING_CONTEXT',
  'UNKNOWN',
  'BLOCKED',
  'AUTHORIZATION_REQUIRED',
  'EXTERNAL_RESOURCE_REQUIRED',
  'WAITING_CONFIRMATION',
  'FAILED',
]);

const ORIGINS = new Set<ResponseOrigin>([
  'COGNITIVE_RUNTIME',
  'LOCAL_RESPONSE',
  'CONVERSATION',
  'MEMORY',
  'MISSION',
  'PROVIDER',
  'SYSTEM',
  'LEGACY_COMPATIBILITY',
]);

type PresentationSemantics = Pick<
  ProductPresentation,
  'title' | 'tone' | 'requires_authorization' | 'requires_confirmation'
>;

const PRESENTATION_BY_STATUS: Record<CognitiveResponseStatus, PresentationSemantics> = {
  COMPLETED: {
    title: 'Resposta', tone: 'neutral',
    requires_authorization: false, requires_confirmation: false,
  },
  WAITING_CONTEXT: {
    title: 'Contexto necessário', tone: 'attention',
    requires_authorization: false, requires_confirmation: false,
  },
  UNKNOWN: {
    title: 'Informação desconhecida', tone: 'uncertain',
    requires_authorization: false, requires_confirmation: false,
  },
  BLOCKED: {
    title: 'Solicitação bloqueada', tone: 'blocked',
    requires_authorization: false, requires_confirmation: false,
  },
  AUTHORIZATION_REQUIRED: {
    title: 'Autorização necessária', tone: 'authorization',
    requires_authorization: true, requires_confirmation: false,
  },
  EXTERNAL_RESOURCE_REQUIRED: {
    title: 'Recurso externo necessário', tone: 'resource',
    requires_authorization: false, requires_confirmation: false,
  },
  WAITING_CONFIRMATION: {
    title: 'Confirmação necessária', tone: 'confirmation',
    requires_authorization: false, requires_confirmation: true,
  },
  FAILED: {
    title: 'Falha de execução', tone: 'error',
    requires_authorization: false, requires_confirmation: false,
  },
};

const EXECUTION_MODES_BY_STATUS: Record<CognitiveResponseStatus, ReadonlySet<string>> = {
  COMPLETED: new Set(['LOCAL_RESPONSE', 'CONVERSATION', 'MISSION']),
  WAITING_CONTEXT: new Set(['CONVERSATION']),
  UNKNOWN: new Set(['UNKNOWN']),
  BLOCKED: new Set(['BLOCKED']),
  AUTHORIZATION_REQUIRED: new Set(['AUTHORIZATION_REQUIRED']),
  EXTERNAL_RESOURCE_REQUIRED: new Set(['EXTERNAL_REASONING_REQUIRED']),
  WAITING_CONFIRMATION: new Set(['MISSION']),
  FAILED: new Set(['FAILED']),
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function recordArray(value: unknown): value is Record<string, unknown>[] {
  return Array.isArray(value) && value.every(isRecord);
}

function sameStrings(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

export function transportFailureProductResponse(
  text: string,
  errorCode: string,
): CognitiveProductResponse {
  return {
    product_contract_version: '1.0',
    text,
    status: 'FAILED',
    execution_mode: 'FAILED',
    epistemic_status: 'unknown',
    confidence: 1,
    response_origin: 'SYSTEM',
    provider: null,
    provider_called: false,
    resource_provenance: [],
    mission_id: null,
    verification_evidence: [],
    limitations: [errorCode],
    missing_capabilities: [],
    authorization_requirements: [],
    next_actions: [],
    ok: false,
    presentation: {
      visible_state: 'FAILED',
      title: 'Falha de execução',
      tone: 'error',
      response_origin: 'SYSTEM',
      show_provider_execution: false,
      show_mission: false,
      show_missing_capabilities: false,
      requires_authorization: false,
      requires_confirmation: false,
      suggested_actions: [],
      interactive_actions: [],
    },
    response_authority: 'CognitiveResponseAssembler',
    product_presentation_authority: 'CognitiveProductPresenter',
    compatibility_path_used: false,
    compatibility_traces: [],
    error_code: errorCode,
    transport_failure: true,
    gateway_mode: 'unavailable',
  };
}

/**
 * Validate and preserve the canonical contract without reclassifying it.
 * Contract violations fail closed as transport failures at the caller.
 */
export function preserveCognitiveProductResponse(
  raw: unknown,
): CognitiveProductResponse {
  if (!isRecord(raw)) throw new Error('response_not_object');
  const status = raw.status as CognitiveResponseStatus;
  const origin = raw.response_origin as ResponseOrigin;
  const presentation = raw.presentation;
  if (!STATUSES.has(status)) throw new Error('invalid_status');
  if (!ORIGINS.has(origin)) throw new Error('invalid_response_origin');
  if (raw.product_contract_version !== '1.0') throw new Error('invalid_contract_version');
  if (raw.response_authority !== 'CognitiveResponseAssembler') throw new Error('invalid_response_authority');
  if (raw.product_presentation_authority !== 'CognitiveProductPresenter') throw new Error('invalid_presentation_authority');
  if (typeof raw.text !== 'string' || typeof raw.execution_mode !== 'string') throw new Error('invalid_text_or_mode');
  if (!EXECUTION_MODES_BY_STATUS[status].has(raw.execution_mode)) throw new Error('execution_mode_status_mismatch');
  if (typeof raw.epistemic_status !== 'string' || typeof raw.confidence !== 'number' || !Number.isFinite(raw.confidence) || raw.confidence < 0 || raw.confidence > 1) throw new Error('invalid_epistemic_fields');
  if (typeof raw.ok !== 'boolean' || raw.ok !== (status !== 'FAILED')) throw new Error('ok_status_mismatch');
  if (typeof raw.provider_called !== 'boolean') throw new Error('invalid_provider_called');
  if (raw.provider !== null && typeof raw.provider !== 'string') throw new Error('invalid_provider');
  if (raw.mission_id !== null && typeof raw.mission_id !== 'string') throw new Error('invalid_mission_id');
  if (!stringArray(raw.resource_provenance)) throw new Error('invalid_resource_provenance');
  if (!recordArray(raw.verification_evidence)) throw new Error('invalid_verification_evidence');
  if (!stringArray(raw.limitations) || !stringArray(raw.missing_capabilities)) throw new Error('invalid_limitations');
  if (!stringArray(raw.authorization_requirements) || !stringArray(raw.next_actions)) throw new Error('invalid_actions');
  if (!isRecord(presentation) || presentation.visible_state !== status) throw new Error('presentation_state_mismatch');
  if (
    typeof presentation.title !== 'string'
    || typeof presentation.tone !== 'string'
    || typeof presentation.show_provider_execution !== 'boolean'
    || typeof presentation.show_mission !== 'boolean'
    || typeof presentation.show_missing_capabilities !== 'boolean'
    || typeof presentation.requires_authorization !== 'boolean'
    || typeof presentation.requires_confirmation !== 'boolean'
    || !stringArray(presentation.suggested_actions)
    || !stringArray(presentation.interactive_actions)
  ) throw new Error('invalid_presentation_fields');
  if (presentation.response_origin !== origin) throw new Error('presentation_origin_mismatch');
  if (presentation.show_provider_execution !== raw.provider_called) throw new Error('provider_presentation_mismatch');
  if (presentation.show_mission !== Boolean(raw.mission_id)) throw new Error('mission_presentation_mismatch');

  const expectedPresentation = PRESENTATION_BY_STATUS[status];
  if (presentation.title !== expectedPresentation.title) throw new Error('presentation_title_mismatch');
  if (presentation.tone !== expectedPresentation.tone) throw new Error('presentation_tone_mismatch');
  if (presentation.requires_authorization !== expectedPresentation.requires_authorization) throw new Error('authorization_presentation_mismatch');
  if (presentation.requires_confirmation !== expectedPresentation.requires_confirmation) throw new Error('confirmation_presentation_mismatch');
  if (presentation.show_missing_capabilities !== (raw.missing_capabilities.length > 0)) throw new Error('missing_capabilities_presentation_mismatch');
  if (!sameStrings(presentation.suggested_actions, raw.next_actions)) throw new Error('suggested_actions_mismatch');
  // Contract 1.0 has no supported interactive resume/execute command boundary.
  if (presentation.interactive_actions.length > 0) throw new Error('unsupported_interactive_actions');

  const providerProvenance = raw.resource_provenance.some((item) => item.startsWith('provider:'));
  const invokedProviderProvenance = raw.provider
    ? raw.resource_provenance.includes(`provider:${raw.provider}`)
    : false;
  if (raw.provider_called && (!raw.provider || !providerProvenance || !invokedProviderProvenance)) throw new Error('provider_evidence_incomplete');
  if (!raw.provider_called && providerProvenance) throw new Error('provider_evidence_fabricated');
  if (!raw.provider_called && raw.provider !== null && raw.provider !== 'local') throw new Error('provider_selection_presented_as_invocation');
  if (status === 'UNKNOWN' && (raw.provider_called || raw.mission_id)) throw new Error('unknown_semantic_override');
  if (status === 'EXTERNAL_RESOURCE_REQUIRED' && raw.provider_called) throw new Error('external_resource_provider_override');
  if (status === 'WAITING_CONFIRMATION' && !raw.mission_id) throw new Error('confirmation_without_mission');
  if (status === 'COMPLETED' && raw.execution_mode === 'MISSION' && (!raw.mission_id || raw.verification_evidence.length === 0)) {
    throw new Error('unverified_mission_completion');
  }
  if (typeof raw.compatibility_path_used !== 'boolean' || !recordArray(raw.compatibility_traces)) throw new Error('invalid_compatibility_evidence');
  if (raw.compatibility_path_used !== (raw.compatibility_traces.length > 0)) throw new Error('compatibility_trace_mismatch');
  return raw as CognitiveProductResponse;
}
