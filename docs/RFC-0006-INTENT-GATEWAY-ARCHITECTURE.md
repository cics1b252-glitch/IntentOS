# RFC-0006: Intent Gateway Architecture

**Status:** Aprovada (Conceitual & Implementação Studio)  
**Autor:** Intent OS Core Architecture Team  
**Data:** 2026-08-06  
**Alvo:** Adaptação de Clientes (AI Studio / Web Shell / Hybrid Host)  

---

## 1. Problema

O Intent OS possui um núcleo cognitivo canônico implementado em Python (Kernel, Mission Engine, Constitution, PKB, ProviderManager, Core Apps, Router e IDS). No entanto, ambientes de hospedagem web e plataformas serverless (como o preview do Google AI Studio) operam sobre rruntime Node.js/Express, sem garantia de dependências nativas como FastAPI ou Uvicorn.

Tentar duplicar a lógica cognitiva em TypeScript para atender a ambientes de pré-visualização resulta em:
1. **Divergência de Comportamento:** Regras de negócio, guardiões constitucionais e o motor de missões comportam-se de forma diferente entre o cliente e o núcleo.
2. **Duplicação de Código (Slop Architecture):** Reimplementação de parsers, roteamento e estado em Node.js.
3. **Quebra de Continuidade:** Fragmentação da memória e do estado de missões.

---

## 2. Decisão Architectural

Adotar a **Intent Gateway Architecture**. O ambiente do AI Studio (Node.js/Express) atua exclusivamente como um **Cliente e Adaptador de Transporte do Intent Gateway**, comunicando-se com o núcleo canônico do Intent OS através de uma abstração de transporte estronca.

### Princípios Obrigatórios:
- **Existe um único Kernel canônico:** O núcleo cognitivo é único e reside na implementação canônica (Python).
- **Clientes não duplicam lógica cognitiva:** O cliente Node.js é estritamente um pass-through de requisições, serializador de mensagens e servidor de arquivos estáticos da UI.
- **Toda integração externa usa o Intent Gateway:** Nenhuma chamada direta de IA ou persistência paralela ocorre fora da arquitetura do Gateway.
- **Continuidade Preservada:** A troca de transporte ou cliente não afeta as missões, a memória ou a constituição.
- **Componentes Substituíveis:** Transportes (stdio, HTTP, WebSockets, gRPC) e provedores são plugáveis e substituíveis.
- **Independência de Tecnologia:** A intenção expressa pelo usuário é independente da linguagem ou framework da interface.

---

## 3. Visão Geral da Arquitetura

```
+-------------------------------------------------------+
|                   AI Studio UI / Shell               |
+-------------------------------------------------------+
                           |  HTTP / REST
                           v
+-------------------------------------------------------+
|             Express Server (server.ts)                |
|  - Pass-Through Router                                |
|  - Static Asset Server                                |
+-------------------------------------------------------+
                           |  Method Calls
                           v
+-------------------------------------------------------+
|              IntentGatewayAdapter (TS)                |
|  - Transport Abstraction                              |
|  - Request Serializer & Timeout Control               |
+-------------------------------------------------------+
                           |  IntentGatewayTransport (Interface)
                           v
+-------------------------------------------------------+
|            LocalProcessTransport (Stdio)              |
|  - Subprocess Management (python3 product_bridge.py)  |
|  - JSON-Lines / UTF-8 Protocol                        |
+-------------------------------------------------------+
                           |  Stdio (stdin / stdout / stderr)
                           v
+-------------------------------------------------------+
|                ProductBridge (Python)                 |
|  - Canonical Kernel / Factory                         |
|  - Mission Engine / Constitution / ProviderManager    |
+-------------------------------------------------------+
```

---

## 4. Responsabilidades e Limites

### Express / Node.js Host (`server.ts`):
- **Permitido:** Servir assets estáticos da UI, rotear requisições HTTP para o `IntentGatewayAdapter`, tratar encerramento do processo Node.js, expor o status de disponibilidade do Gateway.
- **Proibido:** Fazer chamadas diretas a provedores de IA (ex: Gemini SDK em Node.js), implementar regras de intenção, criar respostas por template, persistir estado de missões em Node.
- **Controle Estrutural:** O arquivo `server.ts` não pode conter condicionais de negócio ou lógica de cálculo de estado.

### IntentGatewayAdapter (`gateway/adapter.ts`):
- Adapta requisições HTTP REST para comandos estruturados enviados ao transporte.
- Gerencia o estado de prontidão e fallback de modo (`MODE A - Connected` vs `MODE B - Gateway Unavailable`).

### IntentGatewayTransport (`gateway/transport.ts`):
- Abstração de transporte que define os métodos `sendRequest()`, `getStatus()`, `start()` e `stop()`.
- Implementação inicial: `LocalProcessTransport` (processo Python persistente via stdio JSON-Lines).
- Interfaces preparadas para extensões futuras: `HttpTransport`, `WebSocketTransport`, `GrpcTransport`.

### ProductBridge (`product_bridge.py`):
- Ponto de entrada canônico do Kernel Python via linhas JSON.
- Instancia e opera o `ApplicationFactory` do `intent_kernel`.
- Executa dispatching para ações canônicas: `status`, `intent`, `mission`, `providers`, `core_apps`, `constitution`, `diagnostics`.

---

## 5. Contratos de API do Gateway

O Gateway Express expõe os seguintes endpoints REST mínimos:

| Endpoint | Método | Descrição | Origem dos Dados |
|---|---|---|---|
| `/api/status` | `GET` | Status do Gateway e do Kernel | `ProductBridge.dispatch({"action": "status"})` |
| `/api/intent` | `POST` | Processa uma intenção do usuário | `ProductBridge.dispatch({"action": "intent", ...})` |
| `/api/mission` | `POST` | Gerencia/consulta missões no Mission Engine | `ProductBridge.dispatch({"action": "mission", ...})` |
| `/api/providers` | `GET` | Lista de provedores de IA disponíveis | `ProductBridge.dispatch({"action": "providers"})` |
| `/api/core-apps` | `GET` | Lista de módulos/Core Apps registrados | `ProductBridge.dispatch({"action": "core_apps"})` |
| `/api/constitution` | `GET` | Versão e Guardiões da Constituição | `ProductBridge.dispatch({"action": "constitution"})` |
| `/api/diagnostics` | `GET` | Trilhas de execução e diagnósticos | `ProductBridge.dispatch({"action": "diagnostics"})` |

---

## 6. Lifecycle e Tratamento de Erros do Transporte Stdio

1. **Start:** O `LocalProcessTransport` inicia `python3 product_bridge.py`.
2. **Handshake:** Aguarda a mensagem inicial de protocolo `{"event": "READY", "ok": true}`.
3. **Ready:** Define o status do Gateway como `mode: "connected"`.
4. **Request / Response:** Cada requisição inclui um `requestId` único. As respostas são pareadas assincronamente.
5. **Timeout:** Requisições com tempo limite excedido (padrão 15s) geram erro do tipo `gateway_timeout`.
6. **Robustez de UTF-8:** A comunicação força a codificação UTF-8 em ambos os lados (`reconfigure(encoding="utf-8")`).
7. **Isolamento de Stderr:** Logs e erros de stderr do Python são capturados separadamente e nunca contaminam o fluxo JSON de stdout.
8. **Segurança de Segredos:** Nenhuma chave de API ou credencial é exposta em logs de transporte ou respostas JSON.
9. **Graceful Fallback (MODE B):** Se o processo Python falhar na inicialização ou for encerrado sem possibilidade de reinício imediato, o Gateway responde com `mode: "unavailable"` e a mensagem `Kernel externo indisponível neste ambiente`.

---

## 7. Capability Discovery & Modos do Preview (Modo A vs Modo B)

A UI (Dashboard/Desktop Shell) lê dinamicamente as capacidades do sistema via Gateway:

- **Modo A (Gateway Real):** Quando o `ProductBridge` está ativo. A UI exibe dados reais trazidos do Kernel (status Online, versão da constituição, provedores reais ativos e módulos registrados).
- **Modo B (Gateway Indisponível):** Quando o ambiente não suporta a execução do Kernel ou o processo é interrompido. A UI continua acessível, porém exibe explicitamente "Indisponível" para métricas de sistema e a mensagem `"Kernel externo indisponível neste ambiente"`. **É expressamente proibido simular valores falsos ou exibir "0" como se fosse dado real.**

---

## 8. Critérios de Conformidade (Compliance Checklist)

- [x] O arquivo `server.ts` não possui regras de negócio cognitivas em TypeScript.
- [x] Nenhuma lógica do Kernel Python foi reescrita ou duplicada em Node.js.
- [x] Todos os endpoints do Gateway delegam estritamente para o `ProductBridge`.
- [x] A comunicação por transporte preserva UTF-8 e isola logs de stderr.
- [x] O Dashboard realiza Capability Discovery dinâmico sem listas estáticas ou dados mockados falsos.
- [x] O suporte a um transporte remoto futuro (HTTP/WebSocket) é garantido pela interface `IntentGatewayTransport`.
