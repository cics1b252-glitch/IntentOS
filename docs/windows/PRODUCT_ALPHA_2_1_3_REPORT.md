# Product Alpha 2.1.3 — Startup Hang, White Screen and Forced Shutdown

Versão: `0.4.3-alpha`

## Causa raiz

O `ProductController` era construído no manipulador de inicialização da janela, antes da navegação
da shell. Seu construtor iniciava `KernelBridge`, que executava handshake e health check por
`GetAwaiter().GetResult()`. Essa espera síncrona ocorria no thread WinForms. Quando a bridge
atrasava, a shell ainda não havia sido navegada, a janela ficava branca e o loop de mensagens não
processava o fechamento pelo botão X. O descarte também aguardava sincronamente o pump de stderr.

## Correção

- `KernelBridge.StartAsync` aguarda READY e health sem bloquear o thread visual.
- Uma superfície WinForms aparece antes do WebView2.
- A shell carrega antes da bridge e pode permanecer em modo degradado.
- Estados: `launching`, `loading_host`, `loading_webview`, `loading_shell`, `starting_bridge`,
  `handshaking`, `ready`, `degraded`, `failed` e `shutting_down`.
- Limites: ambiente WebView2 15 s; inicialização 20 s; navegação 15 s; total 45 s; handshake 15 s;
  requisição 60 s.
- O botão X cancela a inicialização e força o encerramento da bridge sem aguardar pumps.
- Modo seguro ignora sessão, Provider automático e histórico, usando visuais padrão e demonstração.
- Preferências inválidas são isoladas com timestamp; o sistema retorna a valores padrão.
- Falhas oferecem nova tentativa, modo seguro, limpeza validada de cache, diagnóstico e fechamento.

## Observabilidade

Logs UTF-8 registram timestamps para `host_started`, `webview_environment_started`,
`webview_ready`, `shell_navigation_started`, `shell_loaded`, `bridge_process_started`,
`bridge_ready`, `kernel_ready`, `session_restored`, `app_ready`, `shutdown_started` e
`shutdown_completed`. Segredos não são registrados.

## Validação

Automatizada: compilação, suíte Python, testes JavaScript, smoke da bridge empacotada e contratos
específicos de estados, timeouts, ausência de bloqueios, safe mode, recuperação e encerramento.

Pendente de validação manual numa instalação Windows real: runtime WebView2 ausente/corrompido,
bridge travada antes de READY, X em todas as fases, atualização preservando dados, resposta real do
Gemini e restauração após reinício. Implementação não é apresentada como evidência desse teste.
