# RFC-0011 — Executive Cognitive Controller (ECC)

## Status: APPROVED & IMPLEMENTED
**Author:** AI Studio Team  
**Module:** `intent_kernel/ecc.py`  
**Dependencies:** IUE (RFC-0007), CDM (RFC-0008), CPE (RFC-0009), COR (RFC-0010)

---

## 1. Visão Geral

O **Executive Cognitive Controller (ECC)** é o **supervisor cognitivo supremo** do Intent OS. Ele é responsável por orquestrar a progressão sequencial do pipeline de processamento de intenções através das quatro camadas fundamentais:

```
User Input ──► ECC ──► IUE ──► ECC ──► CDM ──► ECC ──► CPE ──► ECC ──► COR ──► ECC ──► Mission Runtime
```

### Princípio Arquitetural Sagrado
> **"Os módulos pensam. O ECC decide QUANDO cada módulo deve pensar."**

* O ECC **NUNCA** substitui o raciocínio das camadas internas.
* O ECC **NUNCA** chama diretamente LLM Providers ou SDKs externos.
* O ECC **NUNCA** executa Agentes, Capabilities ou Ferramentas.
* O ECC **NUNCA** gera respostas conversacionais diretamente.
* O ECC é **estritamente supervisório**: avalia decisões executivas, Quality Gates, políticas de segurança/constituição e autoriza ou bloqueia a transição entre estados.

---

## 2. Máquina de Estados Cognitivos (`CognitiveState`)

O ECC gerencia o ciclo de vida da intenção através dos seguintes estados formais:

| Estado | Descrição |
| :--- | :--- |
| `RECEIVED` | Intenção do usuário recebida na borda do kernel. |
| `UNDERSTANDING` | Processamento ativo no IUE (Intent Understanding Engine). |
| `WAITING_CONTEXT` | Pipeline suspenso aguardando esclarecimento ou contexto adicional do usuário (CDM). |
| `READY_FOR_PLANNING` | Intenção compreendida e validada; pronta para o CPE (Cognitive Planning Engine). |
| `REPLANNING` | Plano rejeitado pelo Quality Gate ou ambiente; solicitada nova tentativa de planejamento. |
| `READY_FOR_ORCHESTRATION` | Plano de execução aprovado; pronto para o COR (Capability Orchestrator). |
| `REORCHESTRATING` | Grafo de execução bloqueado ou inválido; solicitada reorquestração com novas restrições. |
| `READY_FOR_EXECUTION` | Grafo de execução totalmente resolvido, alocado e validado para o runtime de missões. |
| `EXECUTION_BLOCKED` | Execução paralisada por violação de políticas, constituição ou segurança. |
| `FAILED` | Falha irrecuperável no pipeline cognitivo. |

---

## 3. Ações Executivas (`ExecutiveAction`)

Após cada estágio do pipeline, o ECC toma uma das seguintes **Ações Executivas**:

* **`CONTINUE`**: Avança para o próximo estágio do pipeline.
* **`RETURN`**: Retorna ao estágio anterior para refinamento.
* **`RETRY`**: Executa novamente o módulo atual com parâmetros ajustados.
* **`ASK_USER`**: Pausa o pipeline e dispara uma Pergunta ao Usuário via CDM/IUE.
* **`REPLAN`**: Descarta o plano atual e exige que o CPE crie um novo plano.
* **`REORCHESTRATE`**: Exige que o COR reavalie alocações e fornecedores.
* **`BLOCK`**: Interrompe o processamento por violar políticas ou limites.
* **`FAIL`**: Marca a execução como falha irrecuperável.
* **`ABORT`**: Cancela o pipeline imediatamente.

---

## 4. Quality Gates e Motores de Avaliação

O ECC aplica **Quality Gates** matemáticos e determinísticos em cada transição:

1. **Gate 1 — IUE (IQI - Intent Quality Index):**
   * *Métrica:* `overall_score >= 0.60`.
   * *Regra:* Se `IQI < 0.60` ou se houver `clarifying_question`, a ação é `ASK_USER` e o estado transita para `WAITING_CONTEXT`.

2. **Gate 2 — CDM (Dialogue Decision):**
   * *Regra:* Se `decision.requires_question` for `True` e `can_proceed` for `False`, a ação é `ASK_USER` com pausa no estado `WAITING_CONTEXT`.

3. **Gate 3 — CPE (PQI - Plan Quality Index):**
   * *Métrica:* `overall_score >= 0.60` e `status != 'blocked'`.
   * *Regra:* Se `PQI < 0.60`, o ECC tenta até 2 iterações de `REPLAN`.

4. **Gate 4 — COR (Execution Graph Validation):**
   * *Métrica:* `status != 'blocked'` e `estimated_cost <= max_cost`.
   * *Regra:* Se o grafo for bloqueado ou exceder custos/latência, o ECC tenta `REORCHESTRATE` ou finaliza em `FAILED`.

---

## 5. Rastreabilidade Executiva (`ExecutiveTrace`)

Cada execução gerada pelo ECC produz um relatório de telemetria completo:

```json
{
  "run_id": "ecc_run_a1b2c3d4",
  "current_state": "READY_FOR_EXECUTION",
  "final_action": "CONTINUE",
  "executive_trace": {
    "trace_id": "trace_ecc_run_a1b2c3d4",
    "intent_id": "iue_7f8e9d",
    "steps": [
      {
        "step_index": 1,
        "module": "IUE",
        "input_summary": "Quero investir R$ 23.500 em CDB...",
        "output_summary": "IQI: 0.85",
        "action": "CONTINUE",
        "state_after": "READY_FOR_PLANNING",
        "reason": "IQI aprovado (0.85 >= min 0.60).",
        "duration_ms": 1.2
      }
    ]
  },
  "metrics": {
    "total_duration_ms": 8.4,
    "planning_iterations": 1,
    "dialogue_iterations": 1,
    "orchestration_iterations": 1,
    "pipeline_completion": 1.0
  }
}
```

---

## 6. Isolamento e Integridade

O módulo `intent_kernel/ecc.py` foi projetado sob rigoroso isolamento e **não importa** bibliotecas de LLM (OpenAI, Anthropic, Google GenAI), frameworks HTTP (requests, httpx) ou módulos de execução do SO (subprocess). É um componente **puro em Python e orientado a objetos**, totalmente testável e determinístico.
