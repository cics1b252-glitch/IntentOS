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
  compatibility_path_used?: boolean;
  compatibility_traces?: Record<string, unknown>[];
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function recordArray(value: unknown): value is Record<string, unknown>[] {
  return Array.isArray(value) && value.every(isRecord);
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
      title: 'Falha de comunicação',
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
  if (typeof raw.epistemic_status !== 'string' || typeof raw.confidence !== 'number') throw new Error('invalid_epistemic_fields');
  if (typeof raw.provider_called !== 'boolean') throw new Error('invalid_provider_called');
  if (raw.provider !== null && typeof raw.provider !== 'string') throw new Error('invalid_provider');
  if (raw.mission_id !== null && typeof raw.mission_id !== 'string') throw new Error('invalid_mission_id');
  if (!stringArray(raw.resource_provenance)) throw new Error('invalid_resource_provenance');
  if (!recordArray(raw.verification_evidence)) throw new Error('invalid_verification_evidence');
  if (!stringArray(raw.limitations) || !stringArray(raw.missing_capabilities)) throw new Error('invalid_limitations');
  if (!stringArray(raw.authorization_requirements) || !stringArray(raw.next_actions)) throw new Error('invalid_actions');
  if (!isRecord(presentation) || presentation.visible_state !== status) throw new Error('presentation_state_mismatch');
  if (presentation.response_origin !== origin) throw new Error('presentation_origin_mismatch');
  if (presentation.show_provider_execution !== raw.provider_called) throw new Error('provider_presentation_mismatch');
  if (presentation.show_mission !== Boolean(raw.mission_id)) throw new Error('mission_presentation_mismatch');

  const providerProvenance = raw.resource_provenance.some((item) => item.startsWith('provider:'));
  if (raw.provider_called && (!raw.provider || !providerProvenance)) throw new Error('provider_evidence_incomplete');
  if (!raw.provider_called && providerProvenance) throw new Error('provider_evidence_fabricated');
  if (status === 'UNKNOWN' && (raw.provider_called || raw.mission_id)) throw new Error('unknown_semantic_override');
  if (status === 'AUTHORIZATION_REQUIRED' && presentation.requires_confirmation === true) throw new Error('authorization_confirmation_collapsed');
  if (status === 'WAITING_CONFIRMATION' && presentation.requires_authorization === true) throw new Error('confirmation_authorization_collapsed');
  if (status === 'COMPLETED' && raw.execution_mode === 'MISSION' && (!raw.mission_id || raw.verification_evidence.length === 0)) {
    throw new Error('unverified_mission_completion');
  }
  if (raw.compatibility_path_used === false && Array.isArray(raw.compatibility_traces) && raw.compatibility_traces.length > 0) {
    throw new Error('compatibility_trace_mismatch');
  }
  return raw as CognitiveProductResponse;
}
