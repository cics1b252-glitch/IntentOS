# Relatório técnico — Product Alpha 2.1.4

## Escopo

Esta correção trata exclusivamente o fluxo funcional da primeira intenção e a normalização de
timestamps. Startup e lifecycle da bridge permanecem conforme 0.4.3-alpha.

## Causas raiz

1. O host persistia itens de conversa em PascalCase, enquanto a UI lia camelCase. O timestamp era
válido, mas a UI recebia `undefined` e construía `Invalid Date`.
2. O callback de telemetria do host entrava no contexto canônico. Ao copiar esse contexto, o
Capability Router atingia um lock não serializável e interrompia a execução após `mission_persisted`.
3. A bridge concatenava histórico e intenção antes da classificação. O módulo financeiro podia
capturar um número de resposta antiga e convertê-lo indevidamente em valor mensal.
4. Sem chamada de Provider, o Provider padrão era atribuído à resposta local, indicando Gemini
indevidamente.

## Correções

- Contexto de runtime e contexto canônico serializável foram separados.
- A intenção atual é classificada isoladamente; histórico segue apenas como contexto da Mission.
- Valores financeiros ambíguos exigem confirmação de recorrência.
- Respostas locais são identificadas como `local`; Provider só é registrado após chamada real.
- Datas ISO, Unix em segundos/milissegundos, Date e valores ausentes são normalizados em UTC.
- Registros legados recebem backup antes da regravação; registros inválidos são isolados.
- O diagnóstico expõe correlação, IDs, estágios, Provider, persistência e renderização.

## Segurança

O log estruturado não contém prompt, resposta integral nem credenciais. Erros são reduzidos a códigos
e tipos seguros. A atualização não modifica o armazenamento protegido de chaves.

## Validação

- Testes automatizados cobrem formatos financeiros, normalização, migração, telemetria, persistência,
falha recuperável, renderização segura e regressões existentes.
- Build e smoke test do executável empacotado são executados pelo pipeline Windows.
- Chamada Gemini real, instalação limpa e validação visual permanecem testes manuais.

## Limitações

Sem credencial e cota disponíveis durante o build, o pacote não comprova uma resposta Gemini real.
O instalador Alpha não é assinado e pode acionar o SmartScreen.
