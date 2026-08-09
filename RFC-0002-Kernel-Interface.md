# RFC-0002 — Kernel Interface

**Status:** Draft  
**Author:** Dali  
**Date:** 2026-07-22  
**Version:** 1.0.0  
**Depends on:** RFC-0001 (Living Constitution)

---

## 1. Resumo

O Kernel do Intent OS é uma biblioteca Python pura, sem dependências externas. Este RFC define suas interfaces públicas — o contrato que separa o que o Kernel faz de como o mundo exterior o implementa.

## 2. Princípio

O Kernel é **importável como lib**. Funciona sem servidor, sem banco, sem API, sem LLM. Tudo que precisa de algo externo é injetado via interfaces.

```python
from intent_kernel import Kernel

kernel = Kernel()  # funciona imediatamente, zero config
result = await kernel.process("Quero investir 5000/mês")
```

## 3. Arquitetura do Kernel

```
intent_kernel/
├── __init__.py              # Kernel class (ponto de entrada)
├── constitution/
│   ├── __init__.py
│   ├── models.py            # Constitution, Pillar, Constraint
│   └── validator.py         # validate() → ConstitutionVerdict
├── engine/
│   ├── __init__.py
│   ├── intent_engine.py     # parsing + classificação
│   ├── pipeline.py          # DAG executor
│   └── nodes.py             # nós do pipeline (Intake, Classify, etc.)
├── pkb/
│   ├── __init__.py
│   ├── models.py            # KnowledgeEvent, EventLifecycle
│   ├── curator.py           # Knowledge Curator (Candidate → Approved)
│   └── store.py             # KnowledgeStore (interface)
├── bus/
│   ├── __init__.py
│   └── event_bus.py         # Event Bus (pub/sub interno)
├── router/
│   ├── __init__.py
│   └── module_router.py     # detecta domínio, carrega módulo
├── providers/
│   ├── __init__.py
│   ├── base.py              # LLMProvider (interface)
│   └── manager.py           # ProviderManager
├── modules/
│   ├── __init__.py
│   ├── base.py              # Module (interface)
│   └── core/                # módulo CORE (primeiro plugin)
│       ├── __init__.py
│       └── module.py
└── types.py                 # IntentInput, IntentOutput, etc.
```

## 4. Interfaces Principais

### 4.1 Kernel (ponto de entrada)

```python
@dataclass
class Kernel:
    constitution: Constitution
    event_bus: EventBus
    pkb: KnowledgeManager
    router: ModuleRouter
    providers: ProviderManager

    async def process(self, user_input: str, context: dict | None = None) -> IntentOutput:
        """
        Fluxo completo:
        1. Constitution.validate(action="process")
        2. IntentEngine.parse(user_input)
        3. Pipeline.execute(intent, mode)
        4. KnowledgeCurator.evaluate(output)
        5. PKB.commit(events)
        6. Retorna IntentOutput
        """
        ...

    async def query(self, question: str) -> list[KnowledgeEvent]:
        """Consulta direta à PKB."""
        ...

    def constitution_check(self, action: str) -> ConstitutionVerdict:
        """Consulta manual à Constitution."""
        ...
```

### 4.2 IntentInput / IntentOutput

```python
@dataclass
class IntentInput:
    text: str                           # texto do usuário
    context: dict[str, Any]              # contexto da sessão
    user_profile: UserProfile | None     # perfil dinâmico (inferido)
    session_id: str                      # ID da sessão atual
    timestamp: datetime

@dataclass
class IntentOutput:
    text: str                           # resposta gerada
    mode: Mode                          # QUICK/BASIC/DETAIL/EXPERT/ARCHITECT
    domain: Domain                      # domínio classificado
    confidence: float                   # 0.0 a 1.0
    epistemic_status: EpistemicStatus   # FACT/ESTIMATE/CONCLUSION/ASSUMPTION/DK
    alternatives: list[str]             # alternativas, se houver
    next_steps: list[str]               # próximos passos sugeridos
    events: list[KnowledgeEvent]        # eventos gerados nesta execução
    reasoning: str | None               # raciocínio (opcional, para DEBUG)
```

### 4.3 KnowledgeStore (interface)

```python
class KnowledgeStore(Protocol):
    """Interface para persistência. Implementações: JsonFile, PostgreSQL, etc."""

    async def append(self, event: KnowledgeEvent) -> str:
        """Adiciona evento. Retorna event_id."""
        ...

    async def get(self, event_id: str) -> KnowledgeEvent | None:
        ...

    async def query(
        self,
        domain: Domain | None = None,
        event_type: EventType | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100
    ) -> list[KnowledgeEvent]:
        ...

    async def version_snapshot(self, event_id: str) -> VersionSnapshot:
        """Snapshot do estado da PKB num ponto no tempo."""
        ...

    async def rollback(self, snapshot_id: str) -> bool:
        ...

    async def export(self, format: str = "json") -> bytes:
        """Exportação completa (Soberania)."""
        ...

    async def delete_all(self) -> bool:
        """Delete real, não mark-as-delete (Soberania)."""
        ...
```

### 4.4 LLMProvider (interface)

```python
class LLMProvider(Protocol):
    """Interface para provedores de LLM."""

    name: str
    models: list[str]

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048
    ) -> CompletionResult:
        ...

    async def health_check(self) -> bool:
        ...
```

### 4.5 Module (interface)

```python
class Module(Protocol):
    """Interface para módulos/plugins."""

    name: str
    version: str
    triggers: list[str]                # palavras que ativam este módulo
    domains: list[Domain]              # domínios que cobre
    required_providers: list[str]      # providers necessários

    async def execute(self, intent: IntentInput, ctx: PipelineContext) -> ModuleOutput:
        ...

    def validate_config(self, config: dict) -> bool:
        """Verifica se a config não viola a Constitution."""
        ...
```

### 4.6 KnowledgeEvent

```python
class EventType(str, Enum):
    DECISION = "decision"
    REQUIREMENT = "requirement"
    RFC = "rfc"
    ARTIFACT = "artifact"
    DOCUMENT = "document"
    MEMORY = "memory"
    ARCHITECTURE = "architecture"
    PLUGIN = "plugin"
    MISSION = "mission"
    GOAL = "goal"
    STRATEGY = "strategy"
    PARAMETER = "parameter"

class EventLifecycle(str, Enum):
    TRANSIENT = "transient"
    CANDIDATE = "candidate"
    APPROVED = "approved"
    CONSTITUTIONAL = "constitutional"

@dataclass
class KnowledgeEvent:
    id: str
    type: EventType
    lifecycle: EventLifecycle
    domain: Domain
    content: dict[str, Any]            # payload flexível
    confidence: float
    epistemic_status: EpistemicStatus
    version: int
    parent_event_id: str | None
    created_at: datetime
    updated_at: datetime
    source: str                        # "user" | "system" | module_name
    tags: list[str]
```

### 4.7 EventBus

```python
class EventBus:
    """Pub/sub interno do Kernel. Módulos se inscrevem em eventos."""

    def subscribe(self, event_type: str, handler: Callable) -> None:
        ...

    async def publish(self, event_type: str, data: Any) -> None:
        ...

    # Eventos padrão do Kernel:
    # "intent.parsed"      → quando a intenção é classificada
    # "pipeline.node.done" → quando um nó termina
    # "module.loaded"      → quando um módulo é carregado
    # "knowledge.approved" → quando o Curator aprova um evento
    # "knowledge.rejected" → quando o Curator rejeita um evento
    # "constitution.blocked" → quando a Constitution bloqueia algo
```

## 5. Módulos do Kernel

### 5.1 Constitution

```python
class Constitution:
    version: str
    supreme_principle: str
    pillars: list[Pillar]
    constraints: list[Constraint]

    def validate(self, action: Action) -> ConstitutionVerdict: ...
    def add_constraint(self, constraint: Constraint) -> None: ...
    def add_pillar(self, pillar: Pillar) -> None: ...
    def export(self) -> dict: ...
```

### 5.2 IntentEngine

```python
class IntentEngine:
    async def parse(self, text: str) -> ParsedIntent:
        """
        Retorna:
        - intent: str (intenção limpa)
        - domain: Domain (classificação)
        - mode: Mode (complexidade)
        - entities: list[Entity] (entidades detectadas)
        - ambiguities: list[str] (ambiguidades encontradas)
        """
        ...
```

### 5.3 Pipeline (DAG)

```python
class Pipeline:
    def __init__(self):
        self.nodes: dict[str, PipelineNode] = {}
        self.edges: dict[str, list[str]] = {}

    def register(self, node: PipelineNode) -> None: ...

    async def execute(self, intent: ParsedIntent, mode: Mode) -> PipelineResult:
        """
        Traverse o DAG no caminho correto para o modo.
        Cada nó recebe Context e retorna Context atualizado.
        """
        ...
```

**Caminhos por modo:**

| Modo | Caminho |
|---|---|
| QUICK | Intake → Classify → Build → Deliver |
| BASIC | Intake → Classify → Diagnose → Build → Review → Deliver |
| DETAIL | Intake → Classify → Diagnose → Plan → Build → Review → Deliver |
| EXPERT | todos os nós |
| ARCHITECT | todos os nós + sub-pipelines paralelos |

### 5.4 KnowledgeManager

```python
class KnowledgeManager:
    store: KnowledgeStore
    curator: KnowledgeCurator

    async def ingest(self, events: list[KnowledgeEvent]) -> IngestResult:
        """
        1. Curator.evaluate cada evento
        2. Classifica lifecycle (Transient/Candidate/Approved)
        3. Approved → store.append + commit
        4. Retorna estatísticas
        """
        ...

    async def query(self, filters: QueryFilters) -> list[KnowledgeEvent]: ...
    async def snapshot(self) -> VersionSnapshot: ...
    async def rollback(self, snapshot_id: str) -> bool: ...
```

### 5.5 ProviderManager

```python
class ProviderManager:
    providers: dict[str, LLMProvider]

    def register(self, name: str, provider: LLMProvider) -> None: ...

    def get(self, name: str) -> LLMProvider:
        """Retorna provider pelo nome. Levanta KeyError se não existe."""
        ...

    async def route(self, task: TaskRequirement) -> LLMProvider:
        """
        Roteamento inteligente:
        - QUICK → provider mais rápido/barato
        - ARCHITECT → provider mais potente
        - fallback → primeiro provider disponível
        """
        ...
```

## 6. Modo de Uso

### 6.1 Uso básico (terminal)

```python
import asyncio
from intent_kernel import Kernel
from intent_kernel.providers.json_store import JsonFileStore

async def main():
    kernel = Kernel(
        store=JsonFileStore("~/.intent-os/pkb")
    )
    result = await kernel.process("Quero montar um plano de estudos para data science")
    print(result.text)
    print(f"Modo: {result.mode}")
    print(f"Confiança: {result.confidence}")

asyncio.run(main())
```

### 6.2 Com provider de LLM

```python
from intent_kernel.providers.openai_provider import OpenAIProvider

kernel = Kernel(
    store=JsonFileStore("~/.intent-os/pkb"),
    providers=ProviderManager({"openai": OpenAIProvider(api_key="sk-...")})
)
```

### 6.3 Consulta à PKB

```python
decisions = await kernel.query("investimento")
for d in decisions:
    print(f"[{d.version}] {d.content}")
```

## 7. Constitution Integration

Todo componente do Kernel recebe a Constitution na inicialização e a valida antes de agir:

```python
class Kernel:
    def __init__(self, constitution: Constitution | None = None, ...):
        self.constitution = constitution or Constitution.default()

    async def process(self, user_input, context=None):
        # 1. Validate
        verdict = self.constitution.validate(Action(type="process", data=user_input))
        if not verdict.allowed:
            return IntentOutput(
                text=f"Operação bloqueada pela Constitution: {verdict.reason}",
                confidence=1.0,
                epistemic_status=EpistemicStatus.FACT
            )
        # 2. Continue...
```

## 8. Validação de Imports

Para garantir que o Kernel não dependa de nada externo:

```python
# tests/test_kernel_independence.py
import ast
import pathlib

FORBIDDEN_IMPORTS = {"fastapi", "sqlalchemy", "redis", "requests", "httpx"}

def test_kernel_no_external_imports():
    kernel_dir = pathlib.Path("intent_kernel")
    for py_file in kernel_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in FORBIDDEN_IMPORTS, \
                        f"{py_file} importa {alias.name}"
```

## 9. Decisões de Design

| Decisão | Escolha | Motivo |
|---|---|---|
| Kernel é Python puro | stdlib + pydantic | Zero dependências externas |
| Protocol para interfaces | structural typing | Implementações não precisam herdar |
| Pipeline é DAG | não linear | Modos diferentes, caminhos diferentes |
| EventBus é interno | não Redis | Kernel funciona sem infra |
| KnowledgeStore é Protocol | não ABC | Mais flexível, duck typing |
| Constitution é dataclass | não YAML | Código é verificável, texto não |

## 10. Checklist de Implementação

- [ ] `intent_kernel/types.py` — todos os tipos base
- [ ] `intent_kernel/constitution/` — Constitution + Pillar + Constraint
- [ ] `intent_kernel/engine/intent_engine.py` — parser + classificador
- [ ] `intent_kernel/engine/pipeline.py` — DAG executor
- [ ] `intent_kernel/pkb/store.py` — KnowledgeStore interface
- [ ] `intent_kernel/pkb/curator.py` — Knowledge Curator
- [ ] `intent_kernel/bus/event_bus.py` — EventBus
- [ ] `intent_kernel/router/module_router.py` — Module Router
- [ ] `intent_kernel/providers/base.py` — LLMProvider interface
- [ ] `intent_kernel/providers/manager.py` — ProviderManager
- [ ] `intent_kernel/modules/base.py` — Module interface
- [ ] `intent_kernel/modules/core/` — módulo CORE
- [ ] `tests/test_kernel_independence.py` — validação de isolamento
- [ ] `tests/test_pipeline.py` — testes do DAG
- [ ] `tests/test_constitution.py` — validação de constraints

---

**Próximo:** RFC-0003 — Knowledge Event Model
