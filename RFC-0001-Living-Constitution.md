# RFC-0001 — Living Constitution

**Status:** Approved  
**Author:** Celso Santos / Dali  
**Date:** 2026-07-22  
**Version:** 1.0.0

---

## 1. Resumo

A Constitution é a primeira entidade carregada pelo Kernel do Intent OS. Ela não é um arquivo estático — é uma entidade viva que valida decisões, filtra módulos e garante que o sistema nunca se desvie de seus princípios fundadores.

## 2. Por que existe

Sem uma Constitution, qualquer sistema evolui para o caos:
- Módulos violam princípios originais sem que ninguém perceba
- Novos desenvolvedores introduzem padrões que contradizem a filosofia
- A IA conectada assume controle em vez de amplificar capacidade cognitiva

A Constitution impede isso programaticamente.

## 3. Posição na Arquitetura

```
Constitution  ← carregada primeiro, valida tudo abaixo
     │
  Kernel
     │
  ┌──┴──────────────────┐
  │  Intent Engine       │
  │  PKB                 │
  │  Event Bus           │
  │  Module Router       │
  │  Provider Manager    │
  │  Knowledge Manager   │
  └─────────────────────┘
```

A Constitution é o primeiro módulo. Antes de qualquer processamento, o Kernel pergunta à Constitution: "isso é permitido?"

## 4. Princípio Supremo

> **O Intent OS existe para ampliar a capacidade cognitiva do usuário, nunca para substituí-la.**

Toda decisão de design, módulo ou integração deve passar por esse filtro. Se algo substitui em vez de amplificar, é rejeitado.

## 5. Os Quatro Pilares

### I. Soberania

O usuário é dono de:
- Seus dados
- Sua memória (PKB)
- Seus projetos e decisões
- Seu perfil de uso

**O sistema nunca é dono de nada.** Os dados vivem onde o usuário escolher. O Kernel pode ler e escrever, mas nunca reter contra a vontade do usuário.

**Constraints técnicas:**
- KnowledgeStore é uma interface — o usuário escolhe a implementação
- Nenhum dado sai da instância local sem consentimento explícito
- Exportação completa disponível a qualquer momento
- Delete é real, não mark-as-deleted

### II. Verdade

O sistema nunca inventa. Classificação obrigatória de todo output:

| Tipo | Definição | Quando usar |
|---|---|---|
| **Fato** | Informação verificada | Sempre que disponível |
| **Estimativa** | Dado inferido com margem | Quando há dados parciais |
| **Conclusão** | Dedução lógica do sistema | Quando a lógica sustenta |
| **Suposição** | Hipótese operacional | Quando falta informação crítica |
| **Não sei** | Ausência de conhecimento | Quando não há base para responder |

**Constraints técnicas:**
- Todo output do Kernel inclui `confidence` + `epistemic_status`
- A Constitution valida que nenhum output é apresentado como fato sem evidência
- DecisionEvent registra qual classificação foi usada

### III. Continuidade

Nenhum conhecimento importante pode morrer em uma conversa.

O Knowledge Curator decide o que entra na PKB. O fluxo:

```
Evento
  ↓
Knowledge Curator
  ↓
Classificação (Transient / Candidate / Approved / Constitutional)
  ↓
PKB (apenas Approved e Constitutional)
  ↓
Commit + Version
```

**Lifecycle de um evento:**

| Fase | Descrição | Persists? |
|---|---|---|
| **Transient** | Dado passageiro, contexto imediato | Não |
| **Candidate** | Potencialmente relevante | Buffer temporário |
| **Approved** | Validado pelo Curator | Sim, na PKB |
| **Constitutional** | Torna parte dos princípios do sistema | Sim, imutável |

**Constraints técnicas:**
- Transient é descartado após processamento
- Candidate tem TTL (expira se não for aprovado)
- Approved pode ser revisto (versão posterior)
- Constitutional é append-only (nunca removido)

### IV. Evolução

O Intent OS nunca está "pronto". Ele:
- Aprende com cada interação (via PKB)
- Versiona conhecimento (Git para decisões)
- Refatora quando encontra padrões melhores
- Expande via módulos sem alterar o Kernel

**Constraints técnicas:**
- Todo KnowledgeEvent tem `version` e `parent_event_id`
- Rollback disponível para qualquer ponto
- Módulos são independentes — um não quebra o outro
- A Constitution pode evoluir, mas apenas via RFC aprovada

## 6. Estrutura da Constitution

```python
@dataclass
class Constitution:
    version: str                    # "1.0.0"
    supreme_principle: str          # "amplificar, nunca substituir"
    pillars: list[Pillar]           # Soberania, Verdade, Continuidade, Evolução
    enforced_constraints: list[Constraint]  # regras verificáveis

class Pillar:
    id: str                         # "soberania"
    name: str                       # "Soberania"
    description: str
    constraints: list[Constraint]

class Constraint:
    id: str                         # "data_sovereignty_no_external"
    rule: str                       # "Nenhum dado sai sem consentimento"
    enforced_by: str                # nome do componente que valida
    severity: Severity              # BLOCK | WARN
```

## 7. Como a Constitution é consultada

Toda decisão importante passa por ela:

```python
class Constitution:
    async def validate(self, action: Action) -> ConstitutionVerdict:
        """Verifica se uma ação é permitida pela Constitution."""
        for constraint in self.all_constraints():
            if not constraint.applies_to(action):
                continue
            result = await constraint.evaluate(action)
            if result == Severity.BLOCK:
                return ConstitutionVerdict(
                    allowed=False,
                    violated_constraint=constraint,
                    reason=constraint.rule
                )
        return ConstitutionVerdict(allowed=True)
```

**Exemplos de consultas:**
- "Esse módulo pode ser instalado?" → verifica pillars + constraints
- "Essa IA pode acessar estes dados?" → verifica Soberania
- "Essa alteração viola um princípio?" → verifica todos os pilares
- "Esse output é truthful?" → verifica Verdade

## 8. Exemplos de Constraints

```yaml
constraints:
  # Soberania
  - id: data_sovereignty
    rule: "Dados do usuário nunca saem sem consentimento"
    enforced_by: provider_manager
    severity: BLOCK

  - id: user_delete_real
    rule: "Delete é remoção real, não mark-as-deleted"
    enforced_by: knowledge_store
    severity: BLOCK

  # Verdade
  - id: no_fake_facts
    rule: "Nunca apresentar estimativa como fato"
    enforced_by: output_validator
    severity: BLOCK

  - id: confidence_required
    rule: "Todo output inclui confidence score"
    enforced_by: output_validator
    severity: BLOCK

  # Continuidade
  - id: knowledge_survives
    rule: "Conhecimento approved persiste entre sessões"
    enforced_by: knowledge_manager
    severity: BLOCK

  - id: transient_ttl
    rule: "Eventos transient expiram após processamento"
    enforced_by: event_bus
    severity: WARN

  # Evolução
  - id: kernel_independence
    rule: "Kernel não depende de services externos"
    enforced_by: import_validator
    severity: BLOCK

  - id: module_isolation
    rule: "Módulos não acessam estado de outros módulos"
    enforced_by: module_router
    severity: BLOCK
```

## 9. Evolução da Constitution

A Constitution pode mudar, mas com restrições rígidas:

1. Qualquer mudança exige uma **RFC** (como esta)
2. A RFC deve ser **aprovada pelo owner**
3. Mudanças são **versionadas** (semântico: major = pilares, minor = constraints, patch =措辞)
4. **Pilares não podem ser removidos** — apenas adicionados
5. **Princípio Supremo não pode ser alterado** — é imutável

```
Constitution v1.0.0
  ├── v1.1.0 — adição de constraint nova
  ├── v1.2.0 — adição de pillar novo
  └── v2.0.0 — (requer justificativa extrema)
```

## 10. Relação com outros RFCs

| RFC | Relação |
|---|---|
| RFC-0002 (Kernel Interface) | O Kernel carrega a Constitution e expõe `validate()` |
| RFC-0003 (Knowledge Event Model) | Events são classificados pela Constitution |
| RFC-0004 (Sprint 0) | Constitution é o primeiro componente implementado |

## 11. Decisões de Design

| Decisão | Escolha | Motivo |
|---|---|---|
| Constitution é código, não documento | Executável | Regras que podem ser violadas não são regras |
| Princípio Supremo é imutável | Imutabilidade | âncora filosófica do sistema |
| Pilares são append-only | Sem remoção | Direção do sistema só pode crescer |
| Constraints têm severity | BLOCK vs WARN | Nem toda violação é fatal, mas todas são visíveis |
| Consulta é síncrona | Blocking | Nenhum processamento avança sem validação |

---

**Próximo:** RFC-0002 — Kernel Interface
