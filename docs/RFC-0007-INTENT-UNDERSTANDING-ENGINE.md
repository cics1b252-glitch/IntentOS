# RFC-0007: Intent Understanding Engine (IUE)

**Status:** Aprovado (Conceitual & Implementação Canonical Engine)  
**Autor:** Intent OS Architecture Team  
**Data:** 2026-08-06  
**Alvo:** Núcleo de Compreensão Estruturada do Intent OS  

---

## 1. Problema

Muitas IAs e assistentes de linguagem tentam compensar uma intenção humana vaga, incompleta ou ambígua gerando respostas prolixas, presunçosas e repletas de suposições infundadas.

Por exemplo, diante de uma entrada como:
> *"Quero investir 23.500"*

Sistemas tradicionais frequentemente assumem perfil de risco (ex: conservador), horizonte de investimento (ex: 1 ano), liquidez e estratégia sem consultar o contexto do usuário nem perguntar o que falta, resultando em recomendações potencialmente prejudiciais.

### Defeitos do Modelo Tradicional:
1. **Atropelo de Execução:** A IA responde antes de entender a real necessidade.
2. **Fabricação de Dados (Hallucinated Context):** Inventa perfil, prazo ou restrições não declaradas.
3. **Falta de Transparência de Incerteza:** O sistema não quantifica a clareza nem a completude do que foi recebido.
4. **Desconexão com a Mission:** Tenta resolver em um único turno de chat uma intenção que exigia a construção de uma Missão com estados e planejamento.

---

## 2. Princípios Arquiteturais Permanentes

1. **Entender antes de responder:** Nenhuma ação final ou execução de missão deve ocorrer sem uma avaliação prévia da compreensão estruturada da intenção.
2. **A IA não compensa intenção mal compreendida com resposta eloquente:** Respostas bonitas sobre premissas erradas são falhas críticas.
3. **Transparência de Lacunas (Missing Context):** O sistema expõe o que sabe (`known_context`) e o que precisa descobrir (`missing_context`).
4. **Esclarecimento Mínimo Útil:** Se faltarem dados críticos, o sistema deve formular apenas a pergunta indispensável que altera a tomada de decisão.
5. **Independência da Execução:** O IUE produz compreensão estruturada (`StructuredIntent`), deixando a execução para o Planner, Mission Engine e Providers.

---

## 3. Arquitetura do Pipeline do IUE

```
Entrada do Usuário
       │
       ▼
1. Intent Parser ───────────────► Extrai tokens, numéricos e entidades primitivas
       │
       ▼
2. Intent Understanding ────────► Identifica objetivo explícito e implícito
       │
       ▼
3. Context Retrieval ───────────► Busca no PKB, na sessão e na memória histórica
       │
       ▼
4. Ambiguity Analysis ──────────► Detecta termos ambíguos ou interpretações concorrentes
       │
       ▼
5. Intent Completion ───────────► Avalia lacunas de dados cruciais (missing context)
       │
       ▼
6. Intent Quality Index (IQI) ──► Calcula o índice de clareza, completude e acionabilidade
       │
       ▼
7. Mission Builder ─────────────► Determina se a intenção se qualifica como Candidate Mission
       │
       ▼
8. Planner & Router ────────────► Seleciona capacidades, agentes e perfil de provider
       │
       ▼
Output Estruturado (StructuredIntent) ──► Enviado ao Gateway e ao Usuário
```

---

## 4. Contrato de Saída Estruturada (`StructuredIntent`)

O IUE produz um payload JSON padronizado com os seguintes campos:

```json
{
  "intent_id": "iue_9a8b7c6d",
  "raw_input": "Quero investir 23.500",
  "goal": "Alocar montante financeiro de R$ 23.500",
  "implicit_goal": "Maximizar rentabilidade com segurança adequada e perfil de risco alinhado",
  "domain": "finance",
  "known_context": [
    "Montante disponível: R$ 23.500,00",
    "Moeda: BRL"
  ],
  "missing_context": [
    "Objetivo do investimento (ex: reserva de emergência, aposentadoria, compra futura)",
    "Prazo / Horizonte de liquidez",
    "Perfil de risco do investidor"
  ],
  "constraints": [],
  "preferences": [],
  "ambiguities": [
    "O valor informado de 23.500 é um aporte único ou recorrente?",
    "Não há indicação se o valor está em conta corrente ou pronto para aplicação."
  ],
  "requires_confirmation": true,
  "confidence": 0.65,
  "recommended_capabilities": [
    "fin.investment_allocator",
    "fin.risk_assessment"
  ],
  "recommended_agents": [
    "financial_advisor_agent"
  ],
  "recommended_provider_profile": "analytic_precise",
  "mission_candidate": true,
  "clarifying_question": "Para eu montar a melhor estratégia para seus R$ 23.500, qual é o objetivo principal e em quanto tempo você pretende usar esse dinheiro?",
  "intent_quality_index": {
    "overall_score": 0.58,
    "clarity": 0.80,
    "completeness": 0.40,
    "context_richness": 0.50,
    "actionability": 0.60
  }
}
```

---

## 5. Métrica Intent Quality Index (IQI)

O **Intent Quality Index (IQI)** é a métrica quantitativa usada pelo Intent OS para medir a maturidade da intenção antes da execução:

- **Clarity (0.0 - 1.0):** Clareza sintática e semântica do objetivo (ausência de jargões conflitantes ou comandos truncados).
- **Completeness (0.0 - 1.0):** Proporção de parâmetros obrigatórios presentes em relação aos exigidos pelo domínio.
- **Context Richness (0.0 - 1.0):** Grau de alinhamento com o contexto do PKB e histórico do usuário.
- **Actionability (0.0 - 1.0):** Capacidade de mapear a intenção para chamadas concretas de capacidades/ferramentas.
- **Overall Score (0.0 - 1.0):** Média ponderada:
  $$\text{IQI} = 0.3 \times \text{Clarity} + 0.3 \times \text{Completeness} + 0.2 \times \text{ContextRichness} + 0.2 \times \text{Actionability}$$

### Regra de Threshold do Executor:
- **$\text{IQI} \ge 0.75$:** A intenção é considerada madura. O Mission Engine pode iniciar a execução diretamente.
- **$0.50 \le \text{IQI} < 0.75$:** A intenção exige confirmação ou preenchimento de premissas explícitas antes de executar.
- **$\text{IQI} < 0.50$:** A intenção é ambígua/incompleta. O sistema **interrompe a execução direta** e responde com a **pergunta de esclarecimento única**.

---

## 6. Integração com o Intent Gateway

O `product_bridge.py` e o `server.ts` expõem a funcionalidade do IUE através dos seguintes mecanismos:

1. **Endpoint dedicado:** `POST /api/iue`  
   Recebe o texto do usuário e retorna exclusivamente o objeto `StructuredIntent` com a análise do IUE.
2. **Pass-Through no Endpoint de Intenção:** `POST /api/intent`  
   Toda requisição enviada ao endpoint de intenção do gateway aciona o IUE em primeiro lugar. Se o IQI for inferior ao limiar seguro, a resposta retorna contendo os metadados de inteligência do IUE e a solicitação pontual de contexto ausente.

---

## 7. Critérios de Aceitação

- [x] O IUE analisa entradas humanas sem gerar respostas arbitrárias ou presunçosas.
- [x] Para a entrada "Quero investir 23.500", o sistema identifica os dados faltantes (prazo, objetivo, perfil) e calcula o IQI adequadamente.
- [x] Respostas em modo de chat contêm o breakdown do IUE no payload para inspeção na UI.
- [x] Testes unitários em Python e testes de integração em JS/TS validam o comportamento do IUE.
