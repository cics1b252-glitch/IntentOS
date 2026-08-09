# RFC-0004 — Sprint 0 Execution Plan

**Status:** Draft  
**Author:** Dali  
**Date:** 2026-07-22  
**Version:** 1.0.0  
**Depends on:** RFC-0001 (Living Constitution), RFC-0002 (Kernel Interface), RFC-0003 (Knowledge Event Model)

---

## 1. Resumo

O Sprint 0 tem um único objetivo: **provar que o Kernel do Intent OS vive sozinho.**

Ao final, o seguinte comando deve funcionar:

```
$ python -m intent_kernel

Intent OS v0.1.0 (Kernel)
Digite sua intenção: Quero montar um plano de estudos para data science

📋 Modo: BASIC
🏷️ Domínio: Educação
💡 Resposta: [resposta estruturada]

📝 Conhecimento persistido (3 eventos)
🔒宪法: Todos os princípios validados ✓
```

Sem servidor. Sem banco complexo. Sem interface gráfica. Apenas o Kernel.

## 2. Escopo

### O que está IN

- Intent Kernel como lib Python pura
- Constitution como entidade execuável
- Pipeline DAG com 3 modos (QUICK, BASIC, DETAIL)
- Knowledge Curator com classificação de lifecycle
- JsonFileStore para persistência
- EventBus interno
- ModuleRouter com módulo CORE
- ProviderManager com 1 provider mock
- CLI interativo

### O que está OUT

- FastAPI / servidor web
- PostgreSQL / Redis
- Flutter / interface mobile
- Provider de LLM real (OpenAI, etc.)
- Módulos FIN, ENG, BUS, etc.
- Interface web
- Autenticação / multi-tenant
- Busca semântica

## 3. Estrutura do Repositório

```
intent-os/
├── README.md
├── pyproject.toml
├── intent_kernel/
│   ├── __init__.py
│   ├── __main__.py              # CLI entry point
│   ├── types.py                 # todos os tipos base
│   ├── constitution/
│   │   ├── __init__.py
│   │   ├── models.py            # Constitution, Pillar, Constraint
│   │   ├── validator.py         # validate()
│   │   └── defaults.py          # Constitution padrão
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── intent_engine.py     # parser + classificador
│   │   ├── pipeline.py          # DAG executor
│   │   └── nodes.py             # nós do pipeline
│   ├── pkb/
│   │   ├── __init__.py
│   │   ├── models.py            # KnowledgeEvent
│   │   ├── schemas.py           # content schemas
│   │   ├── curator.py           # Knowledge Curator
│   │   ├── store.py             # KnowledgeStore (interface)
│   │   └── json_store.py        # JsonFileStore
│   ├── bus/
│   │   ├── __init__.py
│   │   └── event_bus.py         # EventBus
│   ├── router/
│   │   ├── __init__.py
│   │   └── module_router.py     # Module Router
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py              # LLMProvider (interface)
│   │   ├── manager.py           # ProviderManager
│   │   └── mock_provider.py     # MockProvider (para testes)
│   └── modules/
│       ├── __init__.py
│       ├── base.py              # Module (interface)
│       └── core/
│           ├── __init__.py
│           └── module.py        # módulo CORE
├── tests/
│   ├── __init__.py
│   ├── test_kernel_independence.py
│   ├── test_constitution.py
│   ├── test_pipeline.py
│   ├── test_curator.py
│   ├── test_json_store.py
│   └── test_integration.py
└── docs/
    ├── RFC-0001-Living-Constitution.md
    ├── RFC-0002-Kernel-Interface.md
    ├── RFC-0003-Knowledge-Event-Model.md
    └── RFC-0004-Sprint-0.md
```

## 4. Plano de Execução

### Semana 1: Fundação

**Objetivo:** Tipos + Constitution + Kernel inicial

| Dia | Tarefa | Entregável |
|---|---|---|
| D1 | Setup do repo (pyproject.toml, estrutura) | Repo funcional com `pip install -e .` |
| D2 | `types.py` — todos os tipos base | Tipos sem dependências |
| D3 | Constitution models + defaults | Constitution carregável |
| D4 | Constitution validator | `validate()` funcional |
| D5 | `Kernel.__init__` + `process()` stub | Kernel importável |

**Teste:** `from intent_kernel import Kernel` funciona, Constitution valida.

### Semana 2: Engine

**Objetivo:** Pipeline + IntentEngine

| Dia | Tarefa | Entregável |
|---|---|---|
| D6 | IntentEngine (parser + classificador) | `parse()` retorna ParsedIntent |
| D7 | Pipeline DAG (executor base) | DAG executa sequência de nós |
| D8 | Nós do pipeline (Intake, Classify, Diagnose, Build, Review, Deliver) | 6 nós funcionais |
| D9 | Modos (QUICK/BASIC/DETAIL) mapeiam caminhos | Modo seleciona path correto |
| D10 | Testes do pipeline | Pipeline passa em todos os modos |

**Teste:** `kernel.process("teste")` executa o pipeline completo (sem LLM real).

### Semana 3: PKB

**Objetivo:** Knowledge Event Model + Curator + JsonStore

| Dia | Tarefa | Entregável |
|---|---|---|
| D11 | KnowledgeEvent + EventType + EventLifecycle | Modelo completo |
| D12 | Content schemas por tipo | Schemas validados |
| D13 | KnowledgeCurator | Curator classifica lifecycle |
| D14 | KnowledgeStore interface + JsonFileStore | Persistência em JSON |
| D15 | KnowledgeManager (orqistra store + curator) | Ingest + query funcional |

**Teste:** Eventos são criados, classificados, persistidos e consultados.

### Semana 4: Integração + CLI

**Objetivo:** Tudo conectado + CLI funcional

| Dia | Tarefa | Entregável |
|---|---|---|
| D16 | EventBus + ModuleRouter | Eventos circulam, módulo CORE carrega |
| D17 | LLMProvider interface + MockProvider | Provider mock responde |
| D18 | Kernel completo (todas as peças conectadas) | `kernel.process()` end-to-end |
| D19 | CLI interativo (`__main__.py`) | Terminal funcional |
| D20 | Testes de integração + polish | Suite de testes verde |

**Teste:** `python -m intent_kernel` roda, processa intenção, persiste conhecimento.

## 5. Constitution Defaults

A Constitution padrão do Sprint 0:

```python
CONSTITUTION_V1 = Constitution(
    version="1.0.0",
    supreme_principle="O Intent OS existe para ampliar a capacidade cognitiva do usuário, nunca para substituí-la.",
    pillars=[
        Pillar(
            id="soberania",
            name="Soberania",
            description="O usuário é dono dos seus dados",
            constraints=[
                Constraint(
                    id="data_sovereignty",
                    rule="Dados do usuário nunca saem sem consentimento",
                    enforced_by="provider_manager",
                    severity=Severity.BLOCK
                ),
                Constraint(
                    id="user_delete_real",
                    rule="Delete é remoção real, não mark-as-deleted",
                    enforced_by="knowledge_store",
                    severity=Severity.BLOCK
                ),
            ]
        ),
        Pillar(
            id="verdade",
            name="Verdade",
            description="O sistema nunca inventa",
            constraints=[
                Constraint(
                    id="no_fake_facts",
                    rule="Nunca apresentar estimativa como fato",
                    enforced_by="output_validator",
                    severity=Severity.BLOCK
                ),
                Constraint(
                    id="confidence_required",
                    rule="Todo output inclui confidence score",
                    enforced_by="output_validator",
                    severity=Severity.BLOCK
                ),
            ]
        ),
        Pillar(
            id="continuidade",
            name="Continuidade",
            description="Nenhum conhecimento importante morre em conversa",
            constraints=[
                Constraint(
                    id="knowledge_survives",
                    rule="Conhecimento approved persiste entre sessões",
                    enforced_by="knowledge_manager",
                    severity=Severity.BLOCK
                ),
            ]
        ),
        Pillar(
            id="evolucao",
            name="Evolução",
            description="O sistema nunca está pronto",
            constraints=[
                Constraint(
                    id="kernel_independence",
                    rule="Kernel não depende de services externos",
                    enforced_by="import_validator",
                    severity=Severity.BLOCK
                ),
                Constraint(
                    id="module_isolation",
                    rule="Módulos não acessam estado de outros módulos",
                    enforced_by="module_router",
                    severity=Severity.BLOCK
                ),
            ]
        ),
    ]
)
```

## 6. Modo de Uso Final

### Básico (sem LLM)

```python
import asyncio
from intent_kernel import Kernel

async def main():
    kernel = Kernel()  # Constitution padrão, JsonStore em ~/.intent-os/pkb
    result = await kernel.process("Quero investir 5000/mês")
    print(result.text)
    print(f"Modo: {result.mode}")
    print(f"Confiança: {result.confidence}")
    print(f"Eventos: {len(result.events)}")

asyncio.run(main())
```

### CLI

```bash
$ python -m intent_kernel

Intent OS v0.1.0 (Kernel)
Digite sua intenção: Quero montar um plano de estudos para data science

📋 Modo: BASIC
🏷️ Domínio: Educação
💡 Resposta: Para montar um plano de estudos para data science, recomendo...

📝 Conhecimento persistido (2 eventos):
  - [DECISION] Plano de estudos: Data Science
  - [GOAL] Meta: Competência em Data Science

🔒宪法: Todos os princípios validados ✓
```

### Consulta à PKB

```python
decisions = await kernel.query("investimento")
for d in decisions:
    print(f"[v{d.version}] {d.title} (confiança: {d.confidence})")
```

## 7. Critérios de Done

O Sprint 0 está concluído quando:

- [ ] `pip install -e .` instala o kernel sem erros
- [ ] `from intent_kernel import Kernel` funciona
- [ ] Constitution padrão carrega e valida
- [ ] Pipeline executa para QUICK, BASIC, DETAIL
- [ ] KnowledgeCurator classifica eventos corretamente
- [ ] JsonFileStore persiste e recupera eventos
- [ ] EventBus distribui eventos entre componentes
- [ ] ModuleRouter carrega módulo CORE
- [ ] `python -m intent_kernel` roda em terminal
- [ ] Todos os testes passam
- [ ] `test_kernel_independence.py` passa (zero imports externos)
- [ ] README.md documenta uso básico

## 8. Riscos e Mitigações

| Risco | Impacto | Mitigação |
|---|---|---|
| IntentEngine muito simplificado (sem LLM) | Respostas genéricas | Usar regras + regex no Sprint 0; LLM real no Sprint 1 |
| Curator muito conservador (rejeita tudo) | PKB vazia | Defaults permissivos, ajustar com uso |
| JsonStore não escala | Lento com muitos eventos | OK para Sprint 0; PostgreSQL no Sprint 1 |
| Modules muito coupled | Difícil de isolar | Protocol enforcement + testes de isolamento |

## 9. Próximo (Sprint 1)

Após o Sprint 0, o Sprint 1 adiciona:

- FastAPI server (API layer)
- PostgreSQL store (substitui JsonStore)
- OpenAI provider (substitui MockProvider)
- Modos EXPERT e ARCHITECT
- Módulo FIN (finanças)
- Interface web básica

---

**Próximo:** Sprint 1 RFC (após validação do Sprint 0)
