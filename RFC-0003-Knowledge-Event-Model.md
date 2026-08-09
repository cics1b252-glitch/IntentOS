# RFC-0003 — Knowledge Event Model

**Status:** Draft  
**Author:** Dali  
**Date:** 2026-07-22  
**Version:** 1.0.0  
**Depends on:** RFC-0001 (Living Constitution), RFC-0002 (Kernel Interface)

---

## 1. Resumo

O Knowledge Event Model define como o Intent OS representa, classifica e persiste conhecimento. É o coração da PKB — o sistema que transforma conversas passageiras em memória permanente.

## 2. Por que existe

Sem um modelo de eventos padronizado:
- Conhecimento fica preso em conversas
- Não há como comparar decisões ao longo do tempo
- A PKB vira um dump de texto sem estrutura
- Não é possível fazer rollback ou audit trail

## 3. Ciclo de Vida de um Evento

```
Conversa do usuário
       ↓
   [evento gerado]
       ↓
  Knowledge Curator
       ↓
  ┌────┴────────────┐
  │ Transient        │ → descartado após processamento
  │ Candidate        │ → buffer temporário (TTL)
  │ Approved         │ → persiste na PKB
  │ Constitutional   │ → imutável, append-only
  └─────────────────┘
```

### Classificação

| Lifecycle | Descrição | TTL | Persiste? | Pode revogar? |
|---|---|---|---|---|
| **Transient** | Contexto imediato, sem valor duradouro | Sessão | Não | N/A |
| **Candidate** | Potencialmente relevante, aguardando validação | 7 dias | Buffer | Sim (auto-expira) |
| **Approved** | Validado pelo Curator como conhecimento permanente | Infinito | PKB | Sim (nova versão) |
| **Constitutional** | Torna parte dos princípios do sistema | Infinito | PKB | Não (append-only) |

### Regras de Transição

```
Transient → (descarte automático)
Candidate → Approved (Curator aprova)
Candidate → (expira TTL)
Candidate → Transient (Curator rejeita)
Approved → Approved (nova versão, parent_event_id aponta para anterior)
Approved → Constitutional (upgrade via RFC)
```

## 4. Tipos de Evento

```python
class EventType(str, Enum):
    # Decisões
    DECISION = "decision"           # escolha entre alternativas
    STRATEGY = "strategy"           # abordagem de longo prazo
    
    # Conhecimento
    FACT = "fact"                   # informação verificada
    INSIGHT = "insight"             # observação não óbvia
    LESSON = "lesson"               # aprendizado (erros, acertos)
    
    # Estrutura
    REQUIREMENT = "requirement"     # necessidade identificada
    GOAL = "goal"                   # objetivo definido
    MISSION = "mission"             # missão de alto nível
    PARAMETER = "parameter"         # constraint ou configuração
    
    # Documentação
    RFC = "rfc"                     # proposta formal
    ARCHITECTURE = "architecture"   # decisão de design
    DOCUMENT = "document"           # documento de referência
    ARTIFACT = "artifact"           # output produzido
    
    # Sistema
    PLUGIN = "plugin"               # registro de módulo
    MEMORY = "memory"               # dado do perfil do usuário
    EVENT = "event"                 # evento do sistema (audit log)
```

## 5. Estrutura do KnowledgeEvent

```python
@dataclass
class KnowledgeEvent:
    # Identidade
    id: str                              # UUID v4
    type: EventType                      # categorização
    domain: Domain                       # domínio (FIN, ENG, BUS, etc.)
    
    # Conteúdo
    title: str                           # título curto (1 linha)
    content: dict[str, Any]              # payload flexível (schema por tipo)
    summary: str                         # resumo para busca
    
    # Classificação epistêmica
    confidence: float                    # 0.0 a 1.0
    epistemic_status: EpistemicStatus    # FACT/ESTIMATE/CONCLUSION/ASSUMPTION/DK
    
    # Lifecycle
    lifecycle: EventLifecycle            # TRANSIENT/CANDIDATE/APPROVED/CONSTITUTIONAL
    lifecycle_history: list[LifecycleTransition]  # audit trail de mudanças
    
    # Versionamento
    version: int                         # versão do evento
    parent_event_id: str | None          # evento anterior (para updates)
    root_event_id: str | None            # evento raiz da cadeia
    
    # Metadados
    source: str                          # "user" | "system" | module_name
    session_id: str                      # ID da sessão que gerou
    tags: list[str]                      # tags para busca
    metadata: dict[str, Any]             # extensões futuras
    
    # Temporal
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None          # TTL (para Candidate)
```

## 6. Schemas de Conteúdo por Tipo

Cada EventType tem um schema esperado para `content`:

### Decision

```python
@dataclass
class DecisionContent:
    question: str                        # "Qual framework usar?"
    chosen: str                          # "FastAPI"
    alternatives: list[str]              # ["Django", "Flask", "Litestar"]
    rationale: str                       # "Async nativo, Pydantic, performance"
    constraints: list[str]               # ["Precisa de async", "Zero deps no kernel"]
    reversible: bool                     # True
    impact: ImpactLevel                  # LOW/MEDIUM/HIGH/CRITICAL
```

### Goal

```python
@dataclass
class GoalContent:
    description: str                     # "Lançar Intent OS v1.0"
    success_criteria: list[str]          # ["Kernel funcional", "PKB com 100+ eventos"]
    deadline: datetime | None
    progress: float                      # 0.0 a 1.0
    dependencies: list[str]              # IDs de outros eventos
```

### Architecture

```python
@dataclass
class ArchitectureContent:
    decision: str                        # "Kernel como lib Python pura"
    alternatives_considered: list[str]   # ["Microserviço", "Monolito"]
    chosen_approach: str
    tradeoffs: list[str]                 # ["Mais complexo de deploy", "Mais portável"]
    related_events: list[str]            # IDs de eventos relacionados
```

### Memory (perfil do usuário)

```python
@dataclass
class MemoryContent:
    category: str                        # "preference" | "habit" | "constraint" | "context"
    key: str                             # "risk_tolerance"
    value: Any                           # "conservative"
    confidence: float                    # 0.6 (inferido, não declarado)
    observation_count: int               # 3 (quantas vezes observado)
```

### Lesson

```python
@dataclass
class LessonContent:
    what: str                            # "Não abstraia demais no Sprint 0"
    why: str                             # "Leva a infraestrutura não utilizada"
    context: str                         # "Discussão arquitetural do Intent OS"
    applicable_to: list[str]             # ["architecture", "plugin_design"]
```

## 7. Knowledge Curator

O Curator é o filtro entre eventos brutos e a PKB.

```python
class KnowledgeCurator:
    def __init__(self, constitution: Constitution):
        self.constitution = constitution
    
    async def evaluate(self, event: KnowledgeEvent) -> EventLifecycle:
        """
        Classifica o evento:
        1. Verifica se viola Constitution → REJECT
        2. Avalia relevância (tipo + domínio + confiança)
        3. Verifica se é duplicata de evento existente
        4. Retorna lifecycle suggestion
        """
        ...
    
    async def should_promote(self, candidate: KnowledgeEvent) -> bool:
        """Decide se um Candidate vira Approved."""
        ...
    
    async def should_archive(self, approved: KnowledgeEvent) -> bool:
        """Decide se um Approved está obsoleto."""
        ...
```

### Regras do Curator

| Regra | Ação |
|---|---|
| confidence < 0.3 | → Transient (descartar) |
| confidence 0.3–0.6 | → Candidate (avaliar) |
| confidence > 0.6 | → Approved (direto, se não duplicado) |
| EventType == DECISION e confidence > 0.8 | → Approved com prioridade |
| EventType == MEMORY | → Approved (sempre, para perfil do usuário) |
| Conteúdo idêntico a evento existente | → merge (atualiza versão) |
| Viola Constitution | → REJECT + log |

## 8. Versionamento

Todo evento pode ser versionado. A cadeia é:

```
Decision v1 (2026-07-22)
  └── Decision v2 (2026-07-25)  ← parent_event_id aponta para v1
        └── Decision v3 (2026-08-01)
```

### VersionSnapshot

```python
@dataclass
class VersionSnapshot:
    id: str
    event_id: str                        # evento que foi snapshotado
    version: int                         # versão do snapshot
    content: dict[str, Any]              # conteúdo naquele ponto
    created_at: datetime
    reason: str                          # "update" | "correction" | "rollback"
```

### Rollback

```python
async def rollback(self, snapshot_id: str) -> bool:
    """
    Restaura um evento para uma versão anterior.
    Cria um novo evento com parent_event_id = evento atual.
    """
    ...
```

## 9. Query Model

A PKB suporta queries por:

```python
@dataclass
class QueryFilters:
    domain: Domain | None = None
    event_type: EventType | None = None
    lifecycle: EventLifecycle | None = None
    tags: list[str] | None = None
    since: datetime | None = None
    until: datetime | None = None
    min_confidence: float | None = None
    source: str | None = None
    search_text: str | None = None       # full-text search (futuro)
    limit: int = 100
    offset: int = 0
    sort_by: str = "created_at"          # "created_at" | "confidence" | "version"
    sort_order: str = "desc"
```

## 10. JsonFileStore (implementação Sprint 0)

```python
class JsonFileStore:
    """KnowledgeStore para Sprint 0. Persiste em JSON no disco."""
    
    def __init__(self, path: str = "~/.intent-os/pkb"):
        self.path = Path(path).expanduser()
        self.path.mkdir(parents=True, exist_ok=True)
    
    # Estrutura no disco:
    # ~/.intent-os/pkb/
    # ├── events/
    # │   ├── {uuid}.json
    # │   └── ...
    # ├── snapshots/
    # │   ├── {uuid}.json
    # │   └── ...
    # └── index.json          # índice para queries rápidas
```

## 11. Exemplo Completo

```python
# Usuário: "Quero investir 5000/mês em ETFs, sou conservador"

# Evento gerado:
KnowledgeEvent(
    id="evt-001",
    type=EventType.DECISION,
    domain=Domain.FINANCE,
    title="Estratégia de investimento: ETFs conservadores",
    content={
        "question": "Como investir 5000/mês?",
        "chosen": "ETFs de renda fixa + multi-asset conservador",
        "alternatives": ["Ações individuais", "Crypto", "Poupança"],
        "rationale": "Perfil conservador, ETFs reduzem risco por diversificação",
        "constraints": ["Aporte mensal: 5000", "Perfil: conservador"],
        "reversible": True,
        "impact": "HIGH"
    },
    summary="Investimento conservador em ETFs com aporte de 5000/mês",
    confidence=0.85,
    epistemic_status=EpistemicStatus.CONCLUSION,
    lifecycle=EventLifecycle.APPROVED,  # Curator aprovou (decision + alta confiança)
    version=1,
    parent_event_id=None,
    root_event_id=None,
    source="system",
    session_id="sess-abc",
    tags=["investimento", "etf", "conservador"],
    created_at=datetime.now(),
    updated_at=datetime.now(),
    expires_at=None,
)
```

## 12. Relação com a Constitution

| Pilar | Impacto no Event Model |
|---|---|
| **Soberania** | Usuário pode exportar/deletar todos os eventos |
| **Verdade** | Todo evento tem `confidence` + `epistemic_status` |
| **Continuidade** | Approved e Constitutional persistem entre sessões |
| **Evolução** | Eventos são versionados, com rollback disponível |

## 13. Decisões de Design

| Decisão | Escolha | Motivo |
|---|---|---|
| EventLifecycle como enum | 4 estados fixos | Simplicidade > flexibilidade infinita |
| content é dict | não dataclass rígida | Cada tipo tem schema diferente, dict é mais flexível |
| Versionamento append-only | nunca mutar in-place | Audit trail completo |
| Candidate tem TTL | 7 dias default | Evita acúmulo de lixo |
| Curator é síncrono | não async | Regras simples, sem I/O |

## 14. Checklist de Implementação

- [ ] `intent_kernel/pkb/models.py` — KnowledgeEvent, EventType, EventLifecycle
- [ ] `intent_kernel/pkb/schemas.py` — content schemas por tipo
- [ ] `intent_kernel/pkb/curator.py` — KnowledgeCurator
- [ ] `intent_kernel/pkb/store.py` — KnowledgeStore (interface)
- [ ] `intent_kernel/pkb/json_store.py` — JsonFileStore
- [ ] `tests/test_event_model.py` — criação, validação, versionamento
- [ ] `tests/test_curator.py` — classificação de lifecycle
- [ ] `tests/test_json_store.py` — persistência e queries

---

**Próximo:** RFC-0004 — Sprint 0 Execution Plan
