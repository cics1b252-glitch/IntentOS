# Sprint 1 — Canonical Contracts & Composition Root

- **Data:** 2026-07-29
- **Branch:** `feat/openai-integration`
- **Arquitetura de referência:** `docs/ArchitectureTarget_v2.md`
- **Objetivo:** introduzir contratos canônicos e composição explícita sem
  substituir o Kernel ou alterar o comportamento protegido pela baseline

## 1. Resumo

A Sprint 1 introduziu uma fronteira canônica, independente de infraestrutura,
que pode coexistir com os tipos e componentes atuais. O Kernel legado continua
sendo a implementação executada por CLI, FastAPI e Desktop.

Nenhum bootstrap foi redirecionado. Nenhum código legado foi removido, unificado
ou refatorado. A nova estrutura é opt-in e prepara migrações posteriores.

## 2. Contratos implementados

Local: `intent_kernel/contracts/`

### Modelos

- `Mission`;
- `MissionId`;
- `MissionStatus`;
- `MissionResult`;
- `MissionContext`;
- `Capability`;
- `CapabilityResult`;
- `ProviderMessage`;
- `ProviderRequest`;
- `ProviderResponse`;
- `KnowledgeEvent`;
- `ConstitutionVerdict`;
- `ErrorCode`;
- `Domain`;
- `IntentMode`.

Também foram definidos os enums auxiliares `KnowledgeLifecycle` e
`ConstitutionDecision`, necessários para que lifecycle e decisões da
Constitution não dependam de strings livres.

Os contratos usam apenas a biblioteca padrão do Python. Eles não importam
FastAPI, SDKs de provedores, persistência, interface ou componentes legados.

## 3. Ports implementados

Local: `intent_kernel/contracts/ports.py`

- `KnowledgeStore`;
- `Provider`;
- `MissionStore`;
- `EventPublisher`;
- `CapabilityExecutor`;
- `Agent`;
- `ConstitutionEngine`.

As Ports são `Protocol` verificáveis em runtime. Elas pertencem à fronteira
canônica e podem ser implementadas por adaptadores locais, serviços externos ou
substitutos de teste.

## 4. Composition Root

Local: `intent_kernel/application/composition.py`

Foram criados:

- `ApplicationComponents`: conjunto explícito dos componentes montados;
- `KernelBuilder`: configuração da Constitution, store, ProviderManager,
  EventBus, Router e caminho da PKB;
- `ApplicationFactory`: criação lazy e compartilhada de uma única instância;
- `_default_router`: composição equivalente dos módulos atuais `core` e `fin`.

O Composition Root monta o `Kernel` existente e expõe as Ports canônicas através
dos adaptadores. CLI, FastAPI e Desktop ainda usam seus bootstraps atuais. A
migração dessas interfaces pertence a uma Sprint posterior.

## 5. Adaptadores de compatibilidade

Local: `intent_kernel/adapters/legacy.py`

| Adaptador | Componente atual encapsulado | Port canônica |
|---|---|---|
| `LegacyProviderAdapter` | `LLMProvider` | `Provider` |
| `LegacyEventPublisherAdapter` | `EventBus` | `EventPublisher` |
| `LegacyConstitutionEngineAdapter` | `Constitution` | `ConstitutionEngine` |
| `LegacyKnowledgeStoreAdapter` | `JsonFileStore` | `KnowledgeStore` |
| `LegacyCapabilityExecutorAdapter` | `ModuleRouter` | `CapabilityExecutor` |
| `LegacyAgentAdapter` | agente atual | `Agent` |
| `InMemoryMissionStoreAdapter` | não há store legado de missão | `MissionStore` |

Os adaptadores apenas traduzem tipos e chamadas. Regras de negócio permanecem
nos componentes existentes.

O `InMemoryMissionStoreAdapter` não é persistência de produção. Ele existe para
que o Composition Root seja instanciável antes da implementação oficial do
Mission Engine e de seu store.

## 6. Compatibilidade verificada

Foi criado `tests/test_canonical_contracts.py`, com dez testes:

- defaults e versionamento dos modelos canônicos;
- equivalência da resposta do `MockProvider` através do adaptador;
- tradução do verdict da Constitution atual;
- round-trip de um evento pelo `JsonFileStore`;
- preservação do payload no EventBus;
- isolamento por cópia no store temporário de missões;
- instanciação do Composition Root;
- singleton de aplicação por `ApplicationFactory`;
- equivalência observável entre `Kernel()` e o Kernel composto.

O teste de equivalência compara texto, modo, domínio, confiança, estado
epistêmico e próximos passos para a mesma intenção. Não houve alteração de
respostas.

## 7. Resultado completo da baseline

### Compilação

```text
python -m compileall -q intent_kernel
Resultado: aprovado
```

### Testes

```text
Coletados: 462
Aprovados: 459
Falhos: 3
Ignorados: 0
Erros de coleta: 0
Avisos: 3
Novos testes da Sprint 1: 10 aprovados
```

As três falhas e os três avisos são exatamente os registrados na Sprint 0:

1. `test_kernel_no_external_imports`: leitura UTF-8 usa `cp1252`;
2. `test_programs_detected`: inspeção do host retorna lista vazia;
3. `test_sync_with_kernel`: teste tenta gravar em `~/.intent-os/pkb`;
4. três avisos do Monitor por `KnowledgeManager.count` não aguardado.

Nenhuma nova falha ou aviso foi introduzido.

## 8. Impacto na cobertura

| Medição | Sprint 0 | Sprint 1 | Variação |
|---|---:|---:|---:|
| Cobertura combinada | 75% | 76% | +1 ponto percentual |

Cobertura dos novos componentes:

- contratos/models: 100%;
- contratos/ports: 100%;
- composition root: 86%;
- adaptadores legados: 69%.

As linhas não cobertas nos adaptadores correspondem principalmente a traduções
de Agent, Capability, snapshot, rollback, export e caminhos de erro. Elas devem
ser caracterizadas antes de cada migração correspondente, sem ampliar o escopo
desta Sprint.

## 9. Componentes ainda dependentes do legado

- CLI, FastAPI e Desktop instanciam o Kernel pelos bootstraps atuais;
- `Kernel` ainda cria internamente `IntentEngine` e `PipelineDAG`;
- o construtor do Kernel ainda não recebe EventBus e Router;
- o modelo legado de `KnowledgeEvent` continua ativo na PKB;
- `KnowledgeManager`, `curator.py` e `curator_v2.py` continuam inalterados;
- `ProviderManager` e `LLMProvider` continuam como implementação ativa;
- Constitution e Guardians atuais continuam como autoridade em produção;
- Core Apps e agentes ainda usam seus tipos atuais;
- não existe Mission Engine nem MissionStore persistente em produção.

## 10. Riscos encontrados

1. Há dois modelos de `KnowledgeEvent` durante a transição. Toda travessia deve
   passar pelo adaptador até a migração oficial da PKB.
2. Enums canônicos e legados precisam permanecer semanticamente alinhados.
3. Atribuir EventBus e Router após construir o Kernel é uma ponte temporária; o
   construtor deverá recebê-los quando a migração do Kernel for autorizada.
4. O provider padrão atual é escolhido por ordem de registro. O adaptador
   preserva essa regra imperfeita.
5. O store de missões é volátil e não pode ser confundido com implementação
   pronta do Mission Engine.
6. Conectar as interfaces ao Composition Root prematuramente pode mudar ciclo de
   vida, paths e estado compartilhado.
7. Corrigir as três falhas conhecidas dentro desta Sprint violaria o escopo de
   compatibilidade; elas permanecem registradas para tratamento explícito.

## 11. Próxima etapa recomendada

Executar a Sprint 2 definida em `ArchitectureTarget_v2.md` de forma incremental:

1. selecionar uma única fronteira de migração;
2. ampliar a caracterização específica dessa fronteira;
3. fazer o componente legado depender da Port canônica;
4. manter o adaptador como ponte;
5. comprovar equivalência antes de migrar a próxima fronteira.

Não conectar simultaneamente CLI, FastAPI e Desktop, nem consolidar PKB,
Constitution, Curators e Providers em uma única mudança.
