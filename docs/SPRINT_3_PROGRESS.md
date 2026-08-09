# Sprint 3 — Canonical PKB Consolidation

- **Data:** 2026-07-29
- **Branch:** `feat/openai-integration`
- **Referência:** `docs/ArchitectureTarget_v2.md`
- **Objetivo:** estabelecer um modelo, um Curator e um fluxo oficial de
  conhecimento sem remover formatos ou implementações antigas

## 1. Resumo executivo

A PKB possui agora um único fluxo oficial tipado. O modelo exportado por
`intent_kernel.pkb.KnowledgeEvent` é o contrato canônico criado na Sprint 1. A
classificação, score, conflito, persistência e auditoria são coordenados por
`KnowledgePipeline`.

O comportamento da baseline foi preservado:

- confiança abaixo de `0.3` permanece transient;
- confiança entre `0.3` e `0.6` permanece candidate;
- confiança a partir de `0.6` permanece approved;
- MEMORY permanece sempre approved;
- duplicata permanece candidate;
- reasons de lifecycle continuam `Curator: candidate` e
  `Curator: approved`.

Os modelos, Curators e stores anteriores continuam importáveis e acessíveis
através de adaptadores. Não houve migração automática de dados.

## 2. Arquitetura final da PKB

```text
Legacy KnowledgeEvent ── Legacy Event Adapter ──┐
                                                │
Canonical KnowledgeEvent ───────────────────────┤
                                                ▼
                                      KnowledgePipeline
                                                │
                                      ConstitutionEngine
                                                │
                                  CanonicalKnowledgeCurator
                                                │
                                  KnowledgeScoreCalculator
                                                │
                                Duplicate / Conflict Resolution
                                                │
                                         KnowledgeStore
                                                │
                              JsonFileStore compatibility adapter
                                                │
                                      Snapshot / Export / Delete
                                                │
                                  Audit log + EventPublisher
```

O formato JSON físico atual não foi alterado. O adaptador traduz o evento
canônico para esse formato somente na borda de infraestrutura.

## 3. Modelo oficial

Modelo oficial:

```text
intent_kernel.contracts.KnowledgeEvent
intent_kernel.pkb.KnowledgeEvent
```

Ambos referenciam a mesma classe.

O modelo canônico passou a transportar também:

- `lifecycle_history`;
- `expires_at`;
- versão e relações de versão;
- `mission_id`, `session_id` e correlação;
- lifecycle canônico;
- `schema_version`.

Modelo anterior:

```text
intent_kernel.pkb.models.KnowledgeEvent
intent_kernel.pkb.LegacyKnowledgeEvent
```

Permanece disponível para código legado. Conversões são realizadas por:

- `from_legacy_knowledge_event`;
- `to_legacy_knowledge_event`.

Os adaptadores preservam lifecycle history, expiração, versionamento, metadata,
timestamps e identidade.

## 4. Curator oficial

Local:

```text
intent_kernel/pkb/canonical_curator.py
```

Componente oficial:

```text
CanonicalKnowledgeCurator
```

Responsabilidades:

- receber somente `KnowledgeEvent` canônico;
- incorporar verdict da Constitution;
- calcular score composto;
- aplicar limiares de lifecycle compatíveis;
- detectar duplicatas;
- detectar conflitos de fatos;
- identificar correções explícitas para merge;
- produzir decisão tipada;
- produzir evidência de auditoria.

Decisões oficiais:

- `DISCARD`;
- `CANDIDATE`;
- `APPROVE`;
- `MERGE`;
- `CONFLICT`;
- `REJECT`.

O score usa definitivamente o `KnowledgeScoreCalculator`. Quando não existe
breakdown explícito, os cinco fatores recebem a confiança normalizada. Isso
preserva matematicamente os limites caracterizados. Um breakdown completo pode
ser fornecido em `metadata.score_breakdown` sem criar outro modelo de score.

## 5. Curators legados

### curator.py

`KnowledgeCurator` é agora um alias para
`LegacyKnowledgeCuratorAdapter`. A API antiga (`evaluate`, `should_promote`,
`should_archive`) permanece, mas delega ao Curator canônico.

### curator_v2.py

A classe dict-based foi nomeada `LegacyV2KnowledgeCuratorAdapter` e continua
exportada pelo alias histórico `KnowledgeCurator`. Suas APIs de recálculo,
auto-promotion e acesso a filas permanecem disponíveis para consumidores ainda
não migrados.

O fluxo v2 antigo não é exportado como fluxo oficial pelo pacote `pkb`.

## 6. Knowledge Pipeline

Local:

```text
intent_kernel/pkb/knowledge_pipeline.py
```

Sequência implementada:

```text
KnowledgeEvent
→ ConstitutionEngine
→ CanonicalKnowledgeCurator
→ KnowledgeScore
→ Duplicate / Conflict Resolution
→ KnowledgeStore
→ Audit + EventPublisher
```

O pipeline oferece:

- `ingest`;
- `query`;
- `get`;
- `delete`;
- `snapshot`;
- `rollback`;
- `export`;
- `delete_all`;
- `count`;
- `get_audit_log`.

Cada decisão gera `KnowledgeAuditEntry`. Quando há EventPublisher, o evento
interno `knowledge.audit` é publicado com ação, reason, score e conflito
relacionado.

## 7. Score e relevância

O fluxo oficial usa uma única implementação:

```text
KnowledgeScoreCalculator
KnowledgeScore
KnowledgeScoreBreakdown
```

Fatores:

- relevância;
- persistência;
- reutilização;
- impacto;
- alinhamento com objetivos.

O score acompanha toda decisão de curation e toda entrada de auditoria. Ele não é
gravado implicitamente no conteúdo do usuário, evitando mudança no formato
exportado atual.

## 8. Conflitos

Regras oficiais nesta Sprint:

1. mesmo tipo, domínio e título: duplicata, mantida como candidate;
2. FACT no mesmo domínio com conteúdo diferente: conflict;
3. CORRECTION explícita sobre fato conflitante: merge;
4. conflito não sobrescreve o evento persistido;
5. merge cria nova versão do evento existente;
6. toda decisão registra o ID relacionado na auditoria.

Não foi implementada resolução semântica por IA.

## 9. Persistence

`KnowledgeManager` depende internamente apenas de `KnowledgeStore` e delega
operações ao `KnowledgePipeline`.

A propriedade pública `store` ainda aponta para o store antigo porque FastAPI e
Cognitive Map usam essa superfície. Ela é uma fachada de compatibilidade; o
fluxo oficial não a utiliza.

Stores antigos preservados:

- `JsonFileStore`;
- `PersistenceKnowledgeStore`;
- Protocol antigo em `pkb/store.py`.

Nenhum deles foi removido. O Composition Root utiliza
`LegacyKnowledgeStoreAdapter` para apresentar a Port canônica ao pipeline.

Não houve:

- migração de arquivos;
- alteração de schema físico;
- reescrita de eventos existentes;
- mudança de diretório;
- exclusão de implementação.

## 10. Exportação, versionamento e soberania

As operações abaixo passam pelo fluxo/Port oficial:

- export;
- snapshot;
- rollback;
- delete por ID;
- delete total;
- count.

O teste de rollback confirma:

1. persistência do evento;
2. criação de snapshot;
3. atualização;
4. rollback;
5. recuperação do conteúdo anterior;
6. incremento de versão pelo store legado caracterizado.

## 11. Testes da Sprint 3

Arquivo:

```text
tests/test_sprint_3_canonical_pkb.py
```

Oito testes novos cobrem:

- export oficial de um único modelo;
- Curator oficial;
- score e auditoria;
- comportamento de duplicata;
- persistência e publicação de audit;
- conflito sem overwrite;
- merge de correção;
- snapshot, rollback, export e delete;
- adaptação completa do evento legado.

Os 72 testes focados nas Sprints 0–3 passaram em conjunto.

## 12. Resultado completo da baseline

### Compilação

```text
python -m compileall -q intent_kernel intent_os_desktop
Resultado: aprovado
```

### Testes

| Métrica | Resultado |
|---|---:|
| Coletados | 476 |
| Aprovados | 473 |
| Falhos | 3 |
| Ignorados | 0 |
| Erros de coleta | 0 |
| Avisos | 3 |
| Novos testes Sprint 3 | 8 aprovados |

As três falhas conhecidas continuam:

1. fonte UTF-8 lida como `cp1252`;
2. detecção de programas vazia no host Windows;
3. escrita no diretório pessoal real pelo teste Symbiotic.

Os três avisos continuam sendo a coroutine `KnowledgeManager.count` não
aguardada no Monitor.

Não surgiu falha, erro de coleta ou aviso novo.

## 13. Cobertura

Cobertura combinada: **77%**, aumento de um ponto percentual.

| Componente | Cobertura |
|---|---:|
| Contratos canônicos | 100% |
| Knowledge Pipeline | 92% |
| Curator canônico | 88% |
| Adaptador Curator v1 | 88% |
| JsonFileStore | 82% |
| KnowledgeManager | 79% |
| Adaptadores gerais | 76% |
| Score | 80% |

`curator_v2.py` permanece com 0% porque é somente compatibilidade não utilizada
pelo fluxo oficial e não possuía caracterização na baseline inicial.

## 14. Aderência à ArchitectureTarget v2

| Diretriz | Estado |
|---|---|
| Um KnowledgeEvent oficial | Concluído |
| Um Curator oficial | Concluído |
| Um ciclo de conhecimento | Concluído |
| Score integrado | Concluído |
| Auditoria integrada | Concluído |
| Persistência por Port | Concluído no fluxo oficial |
| Formatos legados por adapters | Concluído |
| Versionamento e rollback | Preservados |
| Migração de dados versionada | Não iniciada, conforme escopo |

## 15. Percentual estimado

- **Migração da PKB:** 90%;
- **Migração arquitetural total do projeto:** 60%.

Os 10% restantes da PKB são:

- persistência nativa de eventos canônicos sem adaptador JSON legado;
- migração versionada de dados existentes;
- retirada futura das fachadas públicas antigas;
- decisão de destino do Curator v2 não utilizado.

## 16. Componentes ainda dependentes do legado

- JsonFileStore e formato JSON atual;
- PersistenceKnowledgeStore;
- Curator v2 dict-based;
- conteúdo tipado em `pkb/models.py`;
- FastAPI e Cognitive Map acessando `KnowledgeManager.store`;
- PipelineDAG produzindo eventos legados;
- Core Apps, agentes e Symbiotic Layer criando eventos legados;
- `IntentOutput.events` ainda tipado pelo modelo anterior.

## 17. Riscos restantes

1. Migrar arquivos existentes sem schema versionado pode perder lifecycle ou
   relações de versão.
2. Remover o modelo legado antes de migrar PipelineDAG e Core Apps quebraria a
   superfície pública.
3. Alterar os limiares de score mudaria a baseline de curation.
4. Resolver conflitos automaticamente com IA exige confirmação e evidência.
5. O Curator v2 possui regras não exercitadas por testes históricos.
6. Audit em memória não substitui ainda um AuditStore persistente.
7. Expor score dentro do JSON atual seria uma mudança de formato e deve ocorrer
   somente com migração explícita.

## 18. Próxima etapa recomendada

Na Sprint 4:

1. migrar PipelineDAG e Core Apps para produzir KnowledgeEvent canônico;
2. definir `ExecutionPort`/roteamento canônico;
3. integrar Mission Engine ao pipeline sem criar missão implícita;
4. migrar agentes para Agent Port;
5. manter respostas públicas e formato físico da PKB protegidos;
6. preparar, mas não executar, plano de schema migration para uma release
   posterior.
