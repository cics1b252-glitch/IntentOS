import { spawn, ChildProcess } from 'child_process';
import readline from 'readline';

export interface GatewayStatus {
  ready: boolean;
  mode: 'connected' | 'unavailable';
  error?: string;
  kernel?: string;
  appVersion?: string;
}

export interface IntentGatewayTransport {
  sendRequest(action: string, payload?: Record<string, any>): Promise<any>;
  getStatus(): GatewayStatus;
  start(): Promise<void>;
  stop(): Promise<void>;
}

export class LocalProcessTransport implements IntentGatewayTransport {
  private childProcess: ChildProcess | null = null;
  private readlineInterface: readline.Interface | null = null;
  private status: GatewayStatus = { ready: false, mode: 'unavailable', error: 'Not started' };
  private pendingRequests = new Map<string, {
    resolve: (value: any) => void;
    reject: (reason: any) => void;
    timer: NodeJS.Timeout;
  }>();
  private requestCounter = 0;
  private pythonCommand: string;
  private bridgeScript: string;

  constructor(pythonCommand = 'python3', bridgeScript = 'product_bridge.py') {
    this.pythonCommand = pythonCommand;
    this.bridgeScript = bridgeScript;
  }

  public getStatus(): GatewayStatus {
    return { ...this.status };
  }

  public async start(): Promise<void> {
    if (this.childProcess) {
      return;
    }

    return new Promise<void>((resolve) => {
      let resolved = false;

      try {
        const env = { ...process.env, PYTHONUNBUFFERED: '1' };
        this.childProcess = spawn(this.pythonCommand, [this.bridgeScript], {
          env,
          cwd: process.cwd(),
          stdio: ['pipe', 'pipe', 'pipe'],
        });

        this.readlineInterface = readline.createInterface({
          input: this.childProcess.stdout!,
          crlfDelay: Infinity,
        });

        this.readlineInterface.on('line', (line) => {
          const trimmed = line.trim();
          if (!trimmed) return;

          try {
            const data = JSON.parse(trimmed);

            if (data.event === 'READY' || data.ready === true) {
              this.status = {
                ready: true,
                mode: 'connected',
                kernel: data.kernel_status || 'ready',
                appVersion: data.app_version || '0.4.4-alpha',
              };
              if (!resolved) {
                resolved = true;
                resolve();
              }
              return;
            }

            if (data.requestId && this.pendingRequests.has(data.requestId)) {
              const pending = this.pendingRequests.get(data.requestId)!;
              clearTimeout(pending.timer);
              this.pendingRequests.delete(data.requestId);
              pending.resolve(data);
            }
          } catch (err) {
            console.error('[GatewayTransport] Failed to parse JSON from ProductBridge:', line);
          }
        });

        this.childProcess.stderr?.on('data', (chunk) => {
          console.error('[ProductBridge stderr]:', chunk.toString('utf-8').trim());
        });

        this.childProcess.on('error', (err) => {
          console.error('[GatewayTransport] Spawn error:', err.message);
          this.status = {
            ready: false,
            mode: 'unavailable',
            error: `Process error: ${err.message}`,
          };
          this.clearPendingRequests('Process error: ' + err.message);
          if (!resolved) {
            resolved = true;
            resolve();
          }
        });

        this.childProcess.on('close', (code) => {
          console.log(`[GatewayTransport] ProductBridge process exited with code ${code}`);
          this.status = {
            ready: false,
            mode: 'unavailable',
            error: `Process exited with code ${code}`,
          };
          this.childProcess = null;
          this.clearPendingRequests('ProductBridge process exited');
          if (!resolved) {
            resolved = true;
            resolve();
          }
        });

        // Timeout fallback if READY line is never received in 5s
        setTimeout(() => {
          if (!resolved) {
            resolved = true;
            if (!this.status.ready) {
              this.status = {
                ready: false,
                mode: 'unavailable',
                error: 'Handshake timeout',
              };
            }
            resolve();
          }
        }, 5000);

      } catch (err: any) {
        this.status = {
          ready: false,
          mode: 'unavailable',
          error: `Startup exception: ${err.message}`,
        };
        if (!resolved) {
          resolved = true;
          resolve();
        }
      }
    });
  }

  public async sendRequest(action: string, payload: Record<string, any> = {}): Promise<any> {
    if (this.status.mode === 'unavailable' || !this.childProcess) {
      return {
        ok: false,
        ready: false,
        mode: 'unavailable',
        message: 'Kernel externo indisponível neste ambiente',
        error: 'Gateway unavailable',
        error_code: 'gateway_unavailable',
      };
    }

    const requestId = `req_${++this.requestCounter}_${Date.now()}`;
    const message = JSON.stringify({ requestId, action, ...payload }) + '\n';

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        if (this.pendingRequests.has(requestId)) {
          this.pendingRequests.delete(requestId);
          resolve({
            ok: false,
            error: 'Operação excedeu o tempo limite.',
            error_code: 'gateway_timeout',
            requestId,
          });
        }
      }, 15000);

      this.pendingRequests.set(requestId, { resolve, reject, timer });

      try {
        this.childProcess!.stdin!.write(message, 'utf-8', (err) => {
          if (err) {
            clearTimeout(timer);
            this.pendingRequests.delete(requestId);
            resolve({
              ok: false,
              error: `Erro ao enviar comando: ${err.message}`,
              error_code: 'gateway_write_error',
            });
          }
        });
      } catch (err: any) {
        clearTimeout(timer);
        this.pendingRequests.delete(requestId);
        resolve({
          ok: false,
          error: `Falha na gravação do canal: ${err.message}`,
          error_code: 'gateway_write_exception',
        });
      }
    });
  }

  public async stop(): Promise<void> {
    if (this.readlineInterface) {
      this.readlineInterface.close();
      this.readlineInterface = null;
    }
    if (this.childProcess) {
      this.childProcess.kill('SIGTERM');
      this.childProcess = null;
    }
    this.status = { ready: false, mode: 'unavailable', error: 'Stopped' };
    this.clearPendingRequests('Transport stopped');
  }

  private clearPendingRequests(reason: string) {
    for (const [requestId, pending] of this.pendingRequests.entries()) {
      clearTimeout(pending.timer);
      pending.resolve({
        ok: false,
        ready: false,
        mode: 'unavailable',
        error: reason,
        error_code: 'gateway_process_stopped',
        requestId,
      });
    }
    this.pendingRequests.clear();
  }
}

/**
 * Interface placeholders for future remote kernel connection (RFC-0006 Requirement 9).
 */
export class HttpTransport implements IntentGatewayTransport {
  constructor(private remoteUrl: string) {}
  async sendRequest(action: string, payload?: Record<string, any>): Promise<any> {
    throw new Error('HttpTransport not implemented yet');
  }
  getStatus(): GatewayStatus {
    return { ready: false, mode: 'unavailable', error: 'HttpTransport placeholder' };
  }
  async start(): Promise<void> {}
  async stop(): Promise<void> {}
}

export class WebSocketTransport implements IntentGatewayTransport {
  constructor(private wsUrl: string) {}
  async sendRequest(action: string, payload?: Record<string, any>): Promise<any> {
    throw new Error('WebSocketTransport not implemented yet');
  }
  getStatus(): GatewayStatus {
    return { ready: false, mode: 'unavailable', error: 'WebSocketTransport placeholder' };
  }
  async start(): Promise<void> {}
  async stop(): Promise<void> {}
}
