# Sprint 2 — Canonical Kernel Migration

- **Data:** 2026-07-29
- **Branch:** `feat/openai-integration`
- **Referência:** `docs/ArchitectureTarget_v2.md`
- **Objetivo:** migrar o fluxo interno do Kernel para contratos e Ports
  canônicas, preservando o comportamento protegido pela baseline

## 1. Resumo executivo

O fluxo principal do Kernel passou a consultar Constitution, persistência de
conhecimento, publicação de eventos e provedores através das Ports canônicas.
O `ApplicationFactory` monta todas essas dependências e fornece a mesma instância
para CLI, FastAPI e Desktop.

Foi criada a primeira implementação funcional do Mission Engine, limitada a
lifecycle e continuidade. Nenhum planejamento inteligente, execução autônoma ou
nova funcionalidade de usuário foi incluída.

Os componentes e atributos legados continuam disponíveis como fachadas de
compatibilidade. Nenhum arquivo legado foi removido.

## 2. Componentes migrados

### 2.1 Kernel

O `Kernel` agora recebe e utiliza:

- `ConstitutionEngine`;
- `KnowledgeStore`;
- `EventPublisher`;
- `CapabilityExecutor`;
- Mission Engine montado externamente.

O processamento usa `ConstitutionEngine.evaluate` em vez de chamar diretamente
`Constitution.validate`. A publicação de `kernel.process.done` usa
`EventPublisher`.

As propriedades legadas `constitution`, `store`, `event_bus`, `router` e
`providers` foram preservadas para compatibilidade externa. O método síncrono
`constitution_check` também permanece como fachada legada.

### 2.2 Providers

`ProviderManager` armazena e retorna somente objetos compatíveis com a Port
`Provider`.

`LLMProvider` passou a implementar estruturalmente essa Port:

- `execute(ProviderRequest)`;
- `health()`;
- `capabilities`.

Os métodos legados `complete` e `health_check` permanecem disponíveis. O pipeline
agora envia `ProviderRequest` e recebe `ProviderResponse`, sem alterar os textos,
modelo, uso ou `finish_reason` do MockProvider.

O MockProvider continua sendo registrado quando não existe provider disponível,
exclusivamente para preservar o comportamento atual da baseline.

### 2.3 PKB

`KnowledgeManager` usa internamente apenas a Port canônica `KnowledgeStore`.

Como o Curator v1 e os eventos produzidos pelo pipeline ainda são legados, a
conversão de `KnowledgeEvent` acontece na borda:

- legado para canônico antes da persistência;
- canônico para legado nas respostas públicas atuais.

A propriedade pública `KnowledgeManager.store` ainda expõe o store legado porque
FastAPI e Cognitive Map dependem dessa superfície. Internamente, as operações
passam por `_store`, que é a Port canônica.

`delete_all` foi acrescentado à Port oficial para preservar a garantia de
soberania já existente no sistema.

### 2.4 Constitution

O fluxo assíncrono do Kernel depende de `ConstitutionEngine`. A Constitution
atual e seus Guardians continuam ativos através de
`LegacyConstitutionEngineAdapter`.

Não houve consolidação, reordenação ou alteração de regras.

### 2.5 Interfaces

- CLI: `main()` obtém o Kernel através de `ApplicationFactory`;
- FastAPI: `get_kernel()` usa `ApplicationFactory` e `KernelBuilder`;
- Desktop: aceita uma factory injetada e obtém o Kernel dela.

Os pontos de entrada antigos e a criação direta de `Kernel()` continuam
disponíveis. Uma única factory pode ser compartilhada pelas três interfaces,
produzindo exatamente a mesma instância.

## 3. Mission Engine inicial

Local: `intent_kernel/application/mission_engine.py`

Operações implementadas:

- criação;
- início;
- pausa em estado retomável;
- armazenamento de bloqueio;
- retomada;
- conclusão;
- consulta da missão.

Estados usados:

- `CREATED`;
- `READY`;
- `RUNNING`;
- `PAUSED`;
- `BLOCKED`;
- `WAITING_FOR_INFORMATION`;
- `WAITING_FOR_DECISION`;
- `WAITING_FOR_PERMISSION`;
- `FAILED_RECOVERABLE`;
- `COMPLETED`;
- estados terminais já definidos no contrato.

Cada transição atualiza `updated_at` e persiste pela Port `MissionStore`.
Reinstanciar o Mission Engine sobre o mesmo store permite retomar a missão.
Transições inválidas produzem `MissionTransitionError`.

Não foram implementados:

- planejamento;
- seleção de agentes;
- execução de capabilities;
- automação;
- retry;
- idempotência;
- persistência permanente de missões.

O store atual de missões permanece em memória e é explicitamente transitório.

## 4. Composition Root

O `KernelBuilder` agora cria antes do Kernel:

1. Constitution e seu adaptador;
2. store legado e `KnowledgeStore` canônico;
3. ProviderManager;
4. EventBus e `EventPublisher`;
5. Router e `CapabilityExecutor`;
6. MissionStore e Mission Engine.

Depois injeta essas dependências no Kernel. Não há mais substituição posterior de
EventBus ou Router.

`ApplicationComponents` expõe o Mission Engine além das Ports já disponíveis na
Sprint 1.

## 5. Adaptadores ainda ativos

| Adaptador | Motivo atual |
|---|---|
| `LegacyConstitutionEngineAdapter` | Constitution e Guardians ainda são legados |
| `LegacyKnowledgeStoreAdapter` | JsonFileStore usa o modelo legado |
| `LegacyEventPublisherAdapter` | EventBus ainda não implementa correlação canônica diretamente |
| `LegacyCapabilityExecutorAdapter` | ModuleRouter e Core Apps ainda usam IntentInput legado |
| `LegacyProviderAdapter` | superfície de compatibilidade exposta por ApplicationComponents |
| `LegacyAgentAdapter` | agentes ainda não foram migrados |
| `InMemoryMissionStoreAdapter` | ainda não existe MissionStore persistente |

## 6. Dependências concretas restantes

- `IntentEngine` e `PipelineDAG` continuam concretos no Kernel;
- `ModuleRouter`, `CoreModule` e `FinanceModule` ainda são montados como legado;
- o pipeline ainda produz `IntentOutput` e eventos legados;
- `KnowledgeCurator` v1 continua trabalhando com o modelo legado;
- JsonFileStore continua sendo o adaptador de persistência padrão;
- Constitution concreta ainda é exposta pela fachada de compatibilidade;
- ProviderManager ainda é o serviço concreto de seleção;
- MissionStore é somente memória;
- Core Apps, agentes, Monitor, Cognitive Map e Symbiotic Layer ainda consomem
  superfícies legadas.

## 7. Testes acrescentados

`tests/test_sprint_2_canonical_kernel.py` contém seis testes:

1. lifecycle completo e continuidade da missão;
2. rejeição de transição inválida;
3. Ports expostas pelo Kernel composto;
4. ProviderManager consumindo Provider canônico;
5. CLI e Desktop compartilhando a mesma factory;
6. FastAPI obtendo a instância da mesma factory.

Os testes de Sprint 0 e Sprint 1 continuaram inalterados.

## 8. Resultado da baseline

### Compilação

```text
python -m compileall -q intent_kernel intent_os_desktop
Resultado: aprovado
```

### Suíte completa

| Métrica | Resultado |
|---|---:|
| Coletados | 468 |
| Aprovados | 465 |
| Falhos | 3 |
| Ignorados | 0 |
| Erros de coleta | 0 |
| Avisos | 3 |
| Novos testes Sprint 2 | 6 aprovados |

As três falhas e os três avisos são os mesmos da baseline:

1. leitura UTF-8 com `cp1252` em `test_kernel_no_external_imports`;
2. detecção de programas vazia no ambiente Windows;
3. tentativa de escrita em `~/.intent-os/pkb` no teste Symbiotic;
4. três avisos por coroutine `KnowledgeManager.count` não aguardada.

Nenhuma falha ou aviso adicional foi introduzido.

## 9. Cobertura

Cobertura combinada: **76%**, sem redução em relação à Sprint 1.

Componentes migrados:

- Kernel: 94%;
- Composition Root: 87%;
- Mission Engine: 82%;
- adaptadores: 73%;
- contratos e Ports: 100%;
- KnowledgeManager: 82%;
- servidor FastAPI: 71%.

## 10. Aderência à ArchitectureTarget v2

| Diretriz | Estado |
|---|---|
| Ports and Adapters | Parcialmente implementada no fluxo do Kernel |
| Composition Root oficial | Implementado e usado pelas interfaces |
| Mission first | Lifecycle inicial implementado; execução ainda não integrada |
| Constitution única | Uma implementação ativa através de uma Port |
| Provider agnostic | Manager e pipeline dependem do contrato canônico |
| PKB única | Store acessado por Port; modelo e Curator ainda em transição |
| Interfaces compartilham Kernel | Validado por teste |
| Compatibilidade incremental | Mantida sem remoção de legado |

## 11. Percentual estimado de migração

Estimativa arquitetural: **70% da migração do Kernel e 45% da arquitetura v2
completa**.

O núcleo de orquestração já atravessa as Ports principais. O percentual global é
menor porque Pipeline, Router/Core Apps, Curator/eventos, agentes e persistência
de missões ainda dependem do legado.

## 12. Riscos para Sprint 3

1. Migrar o modelo de KnowledgeEvent antes do Curator pode duplicar lifecycle,
   versionamento ou auditoria.
2. Substituir `IntentOutput` pode alterar respostas públicas protegidas.
3. Integrar Mission Engine ao `process` pode criar missões implícitas e mudar
   persistência observável.
4. Migrar ModuleRouter sem uma Port de roteamento explícita pode sobrecarregar
   `CapabilityExecutor`.
5. Persistir missões exige política de idempotência e migração de schema.
6. Remover as fachadas legadas agora quebraria Monitor, Cognitive Map,
   Symbiotic Layer e endpoints atuais.
7. Alterar seleção do provider mudaria a caracterização de “primeiro provider”.

## 13. Próxima etapa recomendada

Para a Sprint 3:

1. caracterizar profundamente o lifecycle e a serialização dos dois Curators;
2. escolher e versionar o único modelo persistido de KnowledgeEvent;
3. migrar Curator e PKB antes de remover qualquer conversão;
4. definir Port explícita para roteamento/execution do Pipeline;
5. manter `IntentOutput` como fachada até todas as interfaces estarem
   caracterizadas;
6. somente então integrar Mission Engine ao processamento real.
