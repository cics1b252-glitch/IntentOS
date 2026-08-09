# Intent OS Changelog

## 0.4.4-alpha — Product Alpha 2.1.4

- Corrige a interrupção da primeira intenção após a persistência da Mission.
- Separa callbacks internos do contexto canônico serializável.
- Evita que números de conversas anteriores alterem a intenção atual.
- Solicita confirmação antes de interpretar valores ambíguos como aportes mensais.
- Normaliza timestamps legados, Unix e ISO para UTC, com backup seguro.
- Remove `Invalid Date` e mantém compatibilidade com registros PascalCase.
- Registra estágios correlacionados sem prompts, chaves ou conteúdo sensível.
- Diferencia respostas locais de chamadas efetivas ao Provider.
- Retoma a mesma Mission após falha recuperável.

## 0.4.3-alpha — Product Alpha 2.1.3

- Remove esperas síncronas de handshake e health do thread visual do Windows.
- Exibe uma superfície nativa antes do WebView2, com estados e limites de tempo explícitos.
- Carrega a shell antes da bridge e mantém demonstração/recuperação disponíveis em modo degradado.
- Adiciona modo seguro, isolamento de preferências inválidas, limpeza segura de cache e diagnóstico.
- O fechamento cancela a inicialização e encerra processos filhos sem aguardar pumps assíncronos.
- Adiciona testes de inicialização, recuperação, encerramento e arquitetura não bloqueante.

## 0.4.2-alpha — Product Alpha 2.1.2

- Substitui a checagem textual frágil do bootstrap por handshake `READY` em JSON versionado.
- Adiciona health check canônico antes de liberar a conversa.
- Introduz estados explícitos do ciclo de vida da bridge e compatibilidade host/bridge/UI/protocolo.
- Reinicia a bridge uma única vez após queda, sem repetir automaticamente uma intenção ativa.
- Bloqueia o compositor antes de `ready` e oferece reinício e diagnóstico ao usuário.
- Separa `host.log` e `bridge.log`, mantendo conteúdo e segredos fora dos diagnósticos.
- Valida o payload da atualização e substitui integralmente binários antigos, preservando dados.

## 0.4.1-alpha — Product Alpha 2.1.1

- Corrige a queda da bridge em Windows CP1252 ao transportar emoji e Unicode.
- Define JSON Lines UTF-8 como protocolo exclusivo em stdout e move diagnóstico técnico para stderr/log.
- Torna arquivos de estado e logs explicitamente UTF-8.
- Adiciona timeout, detecção de encerramento inesperado e resposta estruturada do host.
- Recupera a conversa após falha: remove loading, reativa o envio e oferece nova tentativa e diagnóstico.
- Preserva configurações, chaves DPAPI, histórico, preferências e atalhos durante a atualização.

## 0.4.0-alpha — Product Alpha 2.1

- Added canonical Google Gemini Provider support.
- Added independent DPAPI-protected credentials and Provider status.
- Added default Provider selection and explicit opt-in fallback.
- Recorded the producing Provider without coupling history or Mission continuity to it.
- Added Gemini error classification, free-tier disclosure, tests and Windows package metadata.

## 0.3.0-alpha — Product Alpha 1

- Added Portuguese first-run onboarding, real OpenAI setup, DPAPI secret protection, and validation.
- Integrated the Windows Shell with the canonical Kernel through a private packaged stdio bridge.
- Added functional conversation, persistent recent history, honest demo mode, settings, and diagnostics.
- Simplified the primary surface and removed default fixture missions and simulated loading states.
- Prepared future account/cloud connectors without fake login or OAuth simulation.
- Updated the per-user installer in place while preserving existing preferences and data.

## 0.2.5-alpha — Windows Host & Installer Alpha

- Added a native, resizable Windows host for the existing Cognitive Shell.
- Added per-user setup/uninstall, shortcuts, Installed apps registration, and data preservation.
- Added self-contained Windows packaging with no Python requirement or external browser/server.
- Added version metadata, checksums, install manifest, packaging tests, and Windows documentation.
- Kernel, Mission Engine, Constitution, PKB, Providers, Core Apps, and domains remain unchanged.
# Product Alpha 2 — First Complete Intent

- Corrige intenções genéricas (`Domain.OTHER`) que não eram compiladas em Mission.
- Preserva a identidade da Mission e o Intent Model gerados pelo Kernel canônico.
- Persiste Intent, Mission, resposta e histórico localmente com gravação atômica.
- Restaura a sessão após reiniciar a bridge ou o aplicativo.
- Traduz falhas de cota, autenticação e conexão do Provider em mensagens compreensíveis.
- Mantém credenciais fora do repositório e dos registros de diagnóstico.
