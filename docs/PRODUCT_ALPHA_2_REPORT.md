# Product Alpha 2 — First Complete Intent

## Resultado

O fluxo do Product Alpha agora aceita uma intenção simples, produz o Intent Model,
compila uma Mission pelo Kernel canônico, encaminha a execução pela Constitution e
Capability Router, usa o Provider selecionado e registra o resultado para continuidade.

## Causa raiz

Frases simples como “Explique qual é sua função” eram classificadas como
`Domain.OTHER`. Esse domínio não possuía Capability canônica associada; portanto, o
Kernel pulava a criação da Mission. Paralelamente, o estado de Mission disponível na
composição era somente em memória, impossibilitando continuidade após reinício.

## Correção

- Todos os domínios, inclusive `OTHER`, possuem rota canônica explícita.
- O Kernel devolve a identidade da Mission e o Intent Model pelo contexto controlado.
- A bridge grava um registro local atômico por sessão em `Data/missions`.
- O registro contém Intent, Mission, resposta, histórico, estado e data de atualização.
- A restauração utiliza o mesmo identificador de sessão.
- Falhas do Provider são registradas como recuperáveis e apresentadas sem payloads técnicos.

## Validação

- Product Alpha 1 + 2: 16 testes aprovados.
- Suíte completa: 574 aprovados; 3 falhas históricas/de ambiente (encoding padrão do
  Windows, descoberta de programas no sandbox e escrita fora do workspace).
- Teste real: a OpenAI recebeu a chamada, mas o projeto selecionado respondeu
  `insufficient_quota`. O produto agora converte esse estado em orientação clara e
  preserva a Mission como `failed_recoverable`.

## Segurança

A chave criada pela OpenAI Platform foi salva somente no arquivo local ignorado
`.env.local`. Seu valor não foi exibido, registrado ou incluído no Git. A chave exposta
anteriormente não foi utilizada.
