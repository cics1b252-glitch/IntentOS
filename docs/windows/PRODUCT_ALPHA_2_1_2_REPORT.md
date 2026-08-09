# Product Alpha 2.1.2 — Bridge Lifecycle and Recovery

Versão: `0.4.2-alpha`

## Causa raiz

Na versão 0.4.1, a bridge foi corretamente alterada para emitir JSON compacto em UTF-8:

```json
{"event":"startup","ok":true}
```

O host .NET, porém, ainda validava o startup por busca textual de `"ok": true`, exigindo um espaço que não faz parte do contrato JSON. O processo existia e a resposta era válida, mas a condição falhava e o construtor `KernelBridge` lançava `InvalidOperationException` na antiga linha 327 de `windows/host/ProductController.cs`.

Estado observado: processo iniciado e pipe funcional; host ainda em bootstrap, sem handshake aceito; UI recebeu `bridge_unavailable/InvalidOperationException`.

## Solução

- handshake obrigatório `READY` em JSON;
- versões de app, bridge e protocolo validadas estruturalmente;
- health check antes de liberar a conversa;
- estados: `not_started`, `starting`, `ready`, `busy`, `degraded`, `restarting`, `unavailable`, `stopped`, `failed`;
- timeout de 15 segundos no handshake e 60 segundos nas solicitações;
- validação de executável, diretório de trabalho, diretório de dados e payload instalado;
- detecção de EOF, processo encerrado, JSON inválido, timeout e incompatibilidade;
- uma tentativa automática de reinício por falha, sem loop;
- uma intenção ativa não é repetida automaticamente, evitando efeito duplicado; após recuperação, a UI oferece nova tentativa;
- compositor bloqueado até `ready` e sempre liberado após falha;
- mensagem humana: “Não foi possível iniciar o núcleo do Intent OS.”;
- ações: tentar novamente, reiniciar núcleo, copiar e abrir diagnóstico;
- logs separados `host.log` e `bridge.log`, ambos UTF-8 e sem chaves/prompts/respostas.

## Atualização

O instalador extrai em staging, valida a versão `0.4.2-alpha`, remove integralmente o diretório antigo do programa e move o payload novo. `%LOCALAPPDATA%\IntentOS\Data` permanece separado e preserva DPAPI, preferências, histórico e dados.

## Testes automatizados

- handshake normal e health check;
- contrato para READY ausente, timeout, encerramento, JSON inválido e versão incompatível;
- executável/diretório ausente ou inválido;
- caminhos com espaços e acentos;
- política de reinício único e segunda falha sem loop;
- bloqueio da UI antes de `ready`;
- recuperação do loading e nova tentativa;
- logs separados e sanitizados;
- substituição de binários e preservação dos dados;
- smoke test do executável PyInstaller com handshake, health e Unicode.

Resultados finais:

- testes focados do produto: `53 passed`;
- suíte Python integral: `604 passed`, `2 failed` por restrições preexistentes do sandbox;
- JavaScript: `40 passed`;
- host e instalador .NET: compilados sem erro;
- smoke do executável empacotado: aprovado.

As duas falhas ambientais são: descoberta vazia de programas instalados no sandbox e bloqueio de escrita no diretório legado `%USERPROFILE%\.intent-os`. Não pertencem ao caminho Product Alpha nem representam regressão da bridge.

## Limitações e validação manual

A instalação limpa, atualização real sobre 0.4.1 e encerramento pelo Gerenciador de Tarefas devem ser executados pelo usuário conforme o roteiro separado. O instalador não foi executado automaticamente neste computador. Uma resposta real Gemini depende da chave DPAPI já configurada na instalação do usuário.
