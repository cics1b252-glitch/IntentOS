"""RFC-0005 — Sprint 1 Execution Plan

**Status:** In Progress
**Author:** Dali
**Date:** 2026-07-22
**Version:** 1.0.0
**Depends on:** RFC-0004 (Sprint 0)

---

## 1. Resumo

O Sprint 1 transforma o Kernel funcional do Sprint 0 em um sistema utilizável:
- FastAPI server com REST API
- OpenAI provider (respostas reais)
- Módulo FIN (finanças)
- PostgreSQL store (opcional, substitui JsonStore)

## 2. Escopo

### O que está IN
- FastAPI server com endpoints REST
- OpenAI provider
- Finance module (FIN)
- PostgreSQL + SQLAlchemy store
- Autenticação básica (API key)
- Documentação OpenAPI automática

### O que está OUT
- Flutter / mobile
- WebSocket / real-time
- Multi-tenant
- Interface web (Sprint 2)
- Mais módulos de domínio

## 3. Novos Componentes

```
intent-os/
├── server/
│   ├── __init__.py
│   ├── app.py              # FastAPI application
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── process.py      # POST /process
│   │   ├── query.py        # GET /query
│   │   ├── pkb.py          # PKB endpoints
│   │   └── status.py       # GET /status
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── auth.py         # API key auth
│   └── models.py           # Request/Response schemas
├── intent_kernel/
│   └── providers/
│       └── openai_provider.py  # OpenAI implementation
│   └── modules/
│       └── fin/
│           └── module.py       # Finance module
│   └── pkb/
│       └── pg_store.py         # PostgreSQL store
```

## 4. API Endpoints

### POST /api/v1/process
Processa uma intenção do usuário.

```json
// Request
{
  "text": "Quero investir 5000/mês",
  "context": {"risk_profile": "conservative"},
  "mode": "auto"  // auto | quick | basic | detail | expert | architect
}

// Response
{
  "text": "Sua resposta...",
  "mode": "basic",
  "domain": "finance",
  "confidence": 0.75,
  "epistemic_status": "conclusion",
  "events": [...],
  "next_steps": [...]
}
```

### GET /api/v1/query?q=investimento
Consulta a PKB.

### GET /api/v1/status
Status do Kernel.

### GET /api/v1/pkb/events
Lista eventos da PKB.

### DELETE /api/v1/pkb/events/{id}
Deleta um evento (Soberania).

## 5. OpenAI Provider

```python
class OpenAIProvider(LLMProvider):
    name = "openai"
    models = ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]

    async def complete(self, messages, model=None, ...):
        # Uses openai Python client
        response = await client.chat.completions.create(...)
        return CompletionResult(text=..., model=..., usage=...)
```

## 6. Finance Module

O módulo FIN processa intenções financeiras:
- Análise de investimento
- Planejamento financeiro
- Comparação de ativos
- Perfil de risco

## 7. PostgreSQL Store

```python
class PostgresStore:
    """KnowledgeStore backed by PostgreSQL."""
    
    async def append(self, event) -> str:
        # INSERT INTO knowledge_events ...
    
    async def query(self, filters) -> list:
        # SELECT ... WHERE ...
```

## 8. Decisões de Design

| Decisão | Escolha | Motivo |
|---|---|---|
| FastAPI | Python moderno, async, OpenAPI automático | Mais rápido que Flask, tipado |
| OpenAI via httpx | client oficial | Battle-tested |
| API key auth | simples, sem OAuth | MVP |
| PostgreSQL via asyncpg | async nativo | Performance |
| SQLAlchemy 2.0 | ORM maduro, async | Migration fácil |

---

## 9. Critérios de Done

- [ ] FastAPI server roda com `uvicorn`
- [ ] POST /process retorna resposta
- [ ] OpenAI provider gera respostas reais
- [ ] Finance module processa intenções financeiras
- [ ] PostgreSQL store persiste eventos
- [ ] API key auth funciona
- [ ] OpenAPI docs acessíveis em /docs
- [ ] Todos os testes passam
"""
