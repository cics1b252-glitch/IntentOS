import { IntentGatewayTransport, LocalProcessTransport, GatewayStatus } from './transport.js';
import {
  CognitiveProductResponse,
  preserveCognitiveProductResponse,
  transportFailureProductResponse,
} from './product-response.js';

export class IntentGatewayAdapter {
  private transport: IntentGatewayTransport;

  constructor(transport?: IntentGatewayTransport) {
    this.transport = transport || new LocalProcessTransport();
  }

  public async init(): Promise<void> {
    await this.transport.start();
  }

  public async getStatus(): Promise<any> {
    const transportStatus = this.transport.getStatus();
    if (transportStatus.mode === 'unavailable') {
      return {
        ok: false,
        ready: false,
        mode: 'unavailable',
        message: 'Kernel externo indisponível neste ambiente',
        error: transportStatus.error || 'Gateway transport unavailable',
      };
    }
    const bridgeResponse = await this.transport.sendRequest('status');
    return {
      mode: 'connected',
      ready: true,
      ...bridgeResponse,
    };
  }

  public async processIntent(payload: Record<string, any>): Promise<CognitiveProductResponse> {
    const transportStatus = this.transport.getStatus();
    if (transportStatus.mode === 'unavailable') {
      return transportFailureProductResponse(
        'Kernel externo indisponível neste ambiente.',
        'gateway_unavailable',
      );
    }
    const response = await this.transport.sendRequest('intent', payload);
    try {
      const preserved = preserveCognitiveProductResponse(response);
      preserved.gateway_mode = 'connected';
      return preserved;
    } catch (error) {
      const reason = error instanceof Error ? error.message : 'unknown_contract_error';
      return transportFailureProductResponse(
        'A resposta do runtime não corresponde ao contrato cognitivo do produto.',
        `product_contract_violation:${reason}`,
      );
    }
  }

  public async understandIntent(payload: Record<string, any>): Promise<any> {
    const transportStatus = this.transport.getStatus();
    if (transportStatus.mode === 'unavailable') {
      return {
        ok: false,
        mode: 'unavailable',
        ready: false,
        message: 'Kernel externo indisponível neste ambiente',
      };
    }
    return await this.transport.sendRequest('iue', payload);
  }

  public async evaluateDialogue(payload: Record<string, any>): Promise<any> {
    const transportStatus = this.transport.getStatus();
    if (transportStatus.mode === 'unavailable') {
      return {
        ok: false,
        mode: 'unavailable',
        ready: false,
        message: 'Kernel externo indisponível neste ambiente',
      };
    }
    return await this.transport.sendRequest('cdm', payload);
  }

  public async createPlan(payload: Record<string, any>): Promise<any> {
    const transportStatus = this.transport.getStatus();
    if (transportStatus.mode === 'unavailable') {
      return {
        ok: false,
        mode: 'unavailable',
        ready: false,
        message: 'Kernel externo indisponível neste ambiente',
      };
    }
    return await this.transport.sendRequest('cpe', payload);
  }

  public async orchestrate(payload: Record<string, any>): Promise<any> {
    const transportStatus = this.transport.getStatus();
    if (transportStatus.mode === 'unavailable') {
      return {
        ok: false,
        mode: 'unavailable',
        ready: false,
        message: 'Kernel externo indisponível neste ambiente',
      };
    }
    return await this.transport.sendRequest('cor', payload);
  }

  public async executePipeline(payload: Record<string, any>): Promise<any> {
    const transportStatus = this.transport.getStatus();
    if (transportStatus.mode === 'unavailable') {
      return {
        ok: false,
        mode: 'unavailable',
        ready: false,
        message: 'Kernel externo indisponível neste ambiente',
      };
    }
    return await this.transport.sendRequest('ecc', payload);
  }

  public async manageMission(payload: Record<string, any>): Promise<any> {
    const transportStatus = this.transport.getStatus();
    if (transportStatus.mode === 'unavailable') {
      return {
        ok: false,
        mode: 'unavailable',
        ready: false,
        message: 'Kernel externo indisponível neste ambiente',
      };
    }
    return await this.transport.sendRequest('mission', payload);
  }

  public async getProviders(): Promise<any> {
    const transportStatus = this.transport.getStatus();
    if (transportStatus.mode === 'unavailable') {
      return {
        ok: false,
        mode: 'unavailable',
        ready: false,
        message: 'Kernel externo indisponível neste ambiente',
        available: [],
      };
    }
    return await this.transport.sendRequest('providers');
  }

  public async getCoreApps(): Promise<any> {
    const transportStatus = this.transport.getStatus();
    if (transportStatus.mode === 'unavailable') {
      return {
        ok: false,
        mode: 'unavailable',
        ready: false,
        message: 'Kernel externo indisponível neste ambiente',
        modules: [],
      };
    }
    return await this.transport.sendRequest('core_apps');
  }

  public async getConstitution(): Promise<any> {
    const transportStatus = this.transport.getStatus();
    if (transportStatus.mode === 'unavailable') {
      return {
        ok: false,
        mode: 'unavailable',
        ready: false,
        message: 'Kernel externo indisponível neste ambiente',
        version: 'Indisponível',
        guardians: [],
      };
    }
    return await this.transport.sendRequest('constitution');
  }

  public async getDiagnostics(): Promise<any> {
    const transportStatus = this.transport.getStatus();
    if (transportStatus.mode === 'unavailable') {
      return {
        ok: false,
        mode: 'unavailable',
        ready: false,
        message: 'Kernel externo indisponível neste ambiente',
        trace: null,
      };
    }
    return await this.transport.sendRequest('diagnostics');
  }

  public async stop(): Promise<void> {
    await this.transport.stop();
  }
}
