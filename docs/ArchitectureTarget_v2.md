# Intent OS — Architecture Target v2.0

- **Status:** arquitetura canônica proposta
- **Autoridade:** referência oficial para as Sprints 1–4
- **Branch de origem:** `feat/openai-integration`
- **Data:** 2026-07-29
- **Escopo:** especificação arquitetural; não autoriza migração ou mudança de
  comportamento

## 0. Convenções normativas

Os termos **DEVE**, **NÃO DEVE**, **PODE** e **RECOMENDA-SE** são normativos.

Classificação de componentes:

- **Oficial:** pertence à arquitetura canônica v2.0.
- **Ativo:** existe e participa do comportamento atual.
- **Planejado:** pertence ao alvo, mas ainda não possui implementação canônica.
- **Legado:** pode permanecer durante a migração, porém não recebe novas
  responsabilidades.
- **Adaptador:** integra uma tecnologia, interface ou fornecedor à arquitetura.
- **Porta (Port):** contrato estável definido pelo núcleo e implementado por
  adaptadores.

Esta especificação não declara que a estrutura atual já está em conformidade. A
baseline de comportamento está documentada em
`docs/SPRINT_0_TEST_BASELINE.md`.

O arquivo `docs/ArchitectureReview.md`, citado como entrada da missão, não estava
presente na branch no momento desta redação. As decisões abaixo foram baseadas no
inventário do código, nos RFCs existentes e na baseline de caracterização.

---

## 1. Visão geral

### 1.1 Missão

O Intent OS é uma camada cognitiva que transforma intenções humanas em missões
compreendidas, planejadas, executadas, verificadas e preservadas com continuidade.

O sistema existe para:

1. compreender a intenção sem exigir conhecimento da arquitetura;
2. manter contexto e continuidade ao longo do tempo;
3. selecionar capacidades e inteligências adequadas;
4. aplicar limites constitucionais antes de decisões e efeitos;
5. produzir resultados explicáveis e auditáveis;
6. preservar o conhecimento como patrimônio do usuário.

O Intent OS não é um provedor de IA, um conjunto de agentes independentes nem uma
coleção de aplicativos expostos. O usuário interage com uma identidade única.

### 1.2 Princípios arquiteturais

1. **Kernel único:** todas as interfaces usam a mesma instância lógica e os mesmos
   casos de uso.
2. **Ports and Adapters:** domínio e aplicação não importam FastAPI, UI, SDKs de
   fornecedores ou detalhes de persistência.
3. **Constitution única:** toda decisão relevante passa por um fluxo canônico de
   validação.
4. **PKB única:** existe um modelo oficial de evento, um Curator e um ciclo de
   conhecimento.
5. **Provider agnostic:** fornecedores são substituíveis e não definem contratos
   do Kernel.
6. **Mission first:** a unidade de continuidade é a missão, não a requisição HTTP
   ou a mensagem isolada.
7. **Agentes sem soberania:** agentes executam trabalho delegado; não controlam
   missão, política, memória ou efeitos externos.
8. **Core Apps como domínios:** Atlas, Logos e OEM Studio oferecem capacidades
   especializadas por contratos, sem duplicar Kernel ou PKB.
9. **Interfaces finas:** CLI, API e Desktop traduzem entrada e saída; não contêm
   regra de negócio.
10. **Efeitos explícitos:** chamadas externas, gravações e ações no hospedeiro são
    mediadas por portas, política, auditoria e idempotência.
11. **Compatibilidade observável:** migrações mantêm testes de caracterização até
    a substituição explícita de um contrato.
12. **Offline degradável:** ausência de rede ou provider reduz capacidades, mas
    não corrompe missão, memória ou conhecimento.

### 1.3 Responsabilidade superior do Kernel

O Kernel é o composition root e a fachada de aplicação do Intent OS. Ele recebe
uma intenção, cria ou retoma uma missão, coordena políticas e capacidades e
devolve um resultado uniforme.

O Kernel governa a ordem; não implementa cada domínio.

---

## 2. Diagrama canônico

### 2.1 Fluxo principal

```text
Pessoa ou Sistema Cliente
          │
          ▼
┌───────────────────────────────────────────────────────────────┐
│ ADAPTADORES DE ENTRADA                                        │
│ CLI │ Desktop/Cognitive Shell │ FastAPI │ integrações futuras │
└───────────────────────────────┬───────────────────────────────┘
                                │ IntentPort
                                ▼
┌───────────────────────────────────────────────────────────────┐
│ KERNEL — fachada, composição, identidade e contexto           │
│ process │ start/resume/cancel mission │ query │ status        │
└───────────────────────────────┬───────────────────────────────┘
                                │ MissionPort
                                ▼
┌───────────────────────────────────────────────────────────────┐
│ MISSION ENGINE                                                │
│ compreender → planejar → validar → executar → verificar       │
│ → persistir checkpoint → concluir/pausar/bloquear             │
└───────────┬───────────────────┬───────────────────┬───────────┘
            │ PolicyPort        │ ExecutionPort     │ MissionStorePort
            ▼                   ▼                   ▼
┌───────────────────┐  ┌──────────────────────┐  ┌───────────────┐
│ CONSTITUTION      │  │ PIPELINE             │  │ CONTINUIDADE  │
│ Guardians         │  │ passos e checkpoints │  │ missões       │
│ decisão canônica  │  │ retries/idempotência │  │ bloqueios     │
└─────────┬─────────┘  └───────┬──────────────┘  └───────┬───────┘
          │ AuditPort           │                       │
          └───────────────┬─────┴───────────────────────┘
                          ▼
┌───────────────────────────────────────────────────────────────┐
│ CAPABILITY ROUTER                                             │
│ seleciona Core App, agente, provider e ferramenta por contrato│
└─────────────┬──────────────────────┬──────────────────────────┘
              │                      │
              │ CoreAppPort          │ ProviderPort
              ▼                      ▼
┌──────────────────────────┐  ┌─────────────────────────────────┐
│ CORE APPS                │  │ PROVIDER MANAGER                │
│ Atlas │ Logos │ OEM      │  │ registro │ seleção │ fallback  │
│ Studio │ futuros         │  │ health │ custo │ capacidades   │
└─────────────┬────────────┘  └───────────────┬─────────────────┘
              │ KnowledgePort                │
              └───────────────┬───────────────┘
                              ▼
┌───────────────────────────────────────────────────────────────┐
│ PKB — PERSONAL KNOWLEDGE BASE                                │
│ KnowledgeEvent │ Curator │ Score │ auditoria │ versões        │
└───────────────────────────────┬───────────────────────────────┘
                                │ KnowledgeStorePort
                                ▼
┌───────────────────────────────────────────────────────────────┐
│ ADAPTADORES DE SAÍDA                                          │
│ arquivo local │ banco │ cloud mesh │ LLM APIs │ Windows │ etc.│
└───────────────────────────────────────────────────────────────┘
```

### 2.2 Regra de dependência

```text
Adapters → Application → Domain
```

Dependências apontam para dentro:

- interfaces dependem de portas do Kernel;
- Kernel depende de portas de aplicação;
- Mission Engine depende de contratos, não de implementações;
- Core Apps dependem de tipos e portas canônicas;
- adaptadores implementam portas;
- domínio não importa adaptadores.

### 2.3 Componentes, portas, adaptadores e contratos

| Área | Estado alvo | Porta oficial | Adaptadores iniciais | Contratos principais |
|---|---|---|---|---|
| Interfaces | Oficial | `IntentPort` | CLI, FastAPI, Desktop | `IntentRequest`, `IntentResponse`, streaming opcional |
| Kernel | Oficial/ativo a consolidar | fachada das portas | composition root | `process`, `mission`, `query`, `status` |
| Mission Engine | Oficial/planejado | `MissionPort`, `MissionStorePort` | store local inicial | `Mission`, `MissionState`, `Checkpoint`, `Blocker` |
| Constitution | Oficial/ativo a consolidar | `PolicyPort`, `AuditPort` | Guardians oficiais | `PolicyRequest`, `PolicyDecision`, `Evidence` |
| Pipeline | Oficial/ativo a consolidar | `ExecutionPort` | DAG inicial | `Plan`, `Step`, `StepResult`, `ExecutionState` |
| Providers | Oficial/ativo a consolidar | `ProviderPort` | Mock, OpenAI, futuros | `ProviderRequest`, `ProviderResult`, `CapabilityDescriptor` |
| Core Apps | Oficial/ativo | `CoreAppPort` | Atlas, Logos, OEM Studio | `CapabilityRequest`, `CapabilityResult` |
| Agentes | Oficial/ativo a consolidar | `AgentPort` | agentes especializados | `AgentTask`, `AgentResult`, `AgentStatus` |
| PKB | Oficial/ativo a consolidar | `KnowledgePort`, `KnowledgeStorePort` | JSON inicial, banco futuro | `KnowledgeEvent`, `CurationDecision`, `KnowledgeQuery` |
| Eventos | Oficial/ativo | `EventPort` | Event Bus em memória | `DomainEvent`, assinatura, correlação |
| Hospedeiro | Adaptador | `HostPort` | Windows/local | ações observáveis e autorizadas |

### 2.4 Contratos transversais

Todos os contratos de aplicação DEVEM transportar, quando aplicável:

- `request_id`;
- `mission_id`;
- `session_id`;
- `correlation_id`;
- `actor`;
- `timestamp`;
- proveniência;
- nível de confiança;
- estado epistêmico;
- requisitos de autorização;
- idempotency key para efeitos;
- versão do schema.

Tipos de domínio não DEVEM depender de modelos HTTP, classes de SDK ou objetos de
interface gráfica.

---

## 3. Kernel

### 3.1 Responsabilidades

O Kernel DEVE:

1. compor as implementações das portas;
2. expor uma fachada uniforme às interfaces;
3. criar, retomar, pausar, cancelar e consultar missões;
4. estabelecer identidade, sessão, correlação e contexto;
5. delegar compreensão ao Intent Engine;
6. delegar ciclo de vida ao Mission Engine;
7. garantir passagem pelo PolicyPort nos pontos obrigatórios;
8. disponibilizar capacidades registradas;
9. publicar eventos de aplicação;
10. devolver respostas independentes da interface;
11. oferecer diagnóstico interno sem expor detalhes ao domínio.

### 3.2 Pertence ao Kernel

- composition root;
- casos de uso de alto nível;
- contratos canônicos compartilhados;
- registro de capacidades;
- coordenação de missão;
- integração entre Policy, Mission, Pipeline, PKB e Event Bus;
- controle de lifecycle da aplicação;
- observabilidade e correlação.

### 3.3 Nunca pertence ao Kernel

- HTML, widgets, prompts de terminal ou modelos FastAPI;
- SDK OpenAI, Gemini, Claude ou qualquer fornecedor;
- regras de carteira, documentos ou engenharia;
- caminhos rígidos do Windows;
- armazenamento JSON concreto;
- credenciais;
- templates específicos de provider;
- lógica de apresentação;
- acesso direto a rede, disco ou sistema operacional;
- comportamento autônomo de agentes;
- múltiplas versões concorrentes do mesmo contrato.

### 3.4 API conceitual

```text
process(IntentRequest) -> IntentResponse
start_mission(MissionRequest) -> MissionSnapshot
resume_mission(MissionId, ResumeInput?) -> MissionSnapshot
cancel_mission(MissionId, reason) -> MissionSnapshot
get_mission(MissionId) -> MissionSnapshot
query_knowledge(KnowledgeQuery) -> KnowledgeResult
status(StatusScope) -> SystemStatus
```

`Kernel.process` torna-se uma fachada de compatibilidade sobre criação ou retomada
de missão, e não um segundo fluxo independente.

---

## 4. Mission Engine

### 4.1 Princípio

> A missão continua automaticamente até sua conclusão, interrompendo apenas
> quando houver decisão estratégica, informação ausente, risco significativo ou
> mudança de escopo.

Continuação automática não amplia permissões. Cada efeito continua sujeito à
Constitution e ao modelo de autorização.

### 4.2 Entidade Mission

Uma missão DEVE possuir:

- identidade estável;
- intenção original e objetivo normalizado;
- critérios de sucesso;
- escopo;
- estado;
- plano versionado;
- passo atual;
- checkpoints;
- dependências;
- bloqueios;
- decisões solicitadas;
- evidências;
- artefatos;
- eventos de conhecimento relacionados;
- histórico de transições;
- resultado final;
- política de retomada.

### 4.3 Estados oficiais

```text
CREATED
  → UNDERSTANDING
  → PLANNING
  → READY
  → RUNNING
  → VERIFYING
  → COMPLETED

Transições laterais:
  WAITING_FOR_INFORMATION
  WAITING_FOR_DECISION
  WAITING_FOR_PERMISSION
  BLOCKED
  PAUSED
  CANCELLED
  FAILED_RECOVERABLE
  FAILED_FINAL
```

### 4.4 Ciclo da missão

1. **Intake:** registrar intenção e contexto.
2. **Understanding:** identificar objetivo, restrições, ambiguidades e risco.
3. **Planning:** criar passos, dependências, verificações e pontos de autorização.
4. **Policy pre-check:** validar plano e capacidades propostas.
5. **Execution:** executar um passo idempotente por vez.
6. **Checkpoint:** persistir estado antes e depois de efeitos.
7. **Verification:** comparar resultado com o critério do passo.
8. **Adaptation:** ajustar plano sem alterar objetivo ou escopo silenciosamente.
9. **Knowledge capture:** propor eventos relevantes ao Curator.
10. **Completion:** verificar critérios de sucesso e emitir resultado.

### 4.5 Planejamento

O plano é um artefato versionado. Cada passo DEVE declarar:

- objetivo;
- capacidade necessária;
- entradas;
- pré-condições;
- efeitos possíveis;
- classe de risco;
- política aplicável;
- condição de sucesso;
- estratégia de retry;
- compensação ou reversão, quando possível.

Replanejamento automático é permitido somente dentro do escopo aprovado.

### 4.6 Retomada e continuidade

Uma missão retomável DEVE persistir:

- último checkpoint consistente;
- passos concluídos;
- efeitos confirmados;
- pendências;
- bloqueador atual;
- contexto mínimo necessário;
- versão dos contratos utilizados.

Após reinício, o Mission Engine NÃO DEVE repetir efeito sem consultar a
idempotency key ou o estado do adaptador.

### 4.7 Bloqueios

Um `Blocker` possui tipo, descrição, evidência, responsável pela resolução e ação
de retomada.

Tipos oficiais:

- `MISSING_INFORMATION`;
- `STRATEGIC_DECISION`;
- `PERMISSION_REQUIRED`;
- `SIGNIFICANT_RISK`;
- `SCOPE_CHANGE`;
- `DEPENDENCY_UNAVAILABLE`;
- `PROVIDER_UNAVAILABLE`;
- `POLICY_DENIED`;
- `TECHNICAL_FAILURE`.

### 4.8 Critérios de interrupção

O Mission Engine interrompe quando:

1. falta informação que não pode ser inferida com segurança;
2. existem alternativas com impacto estratégico material;
3. um efeito exige autorização;
4. o risco ultrapassa o limite da política;
5. a próxima ação altera o escopo;
6. nenhuma capacidade saudável atende ao contrato;
7. a Constitution nega a ação;
8. retries seguros foram esgotados;
9. o usuário pausa ou cancela;
10. uma condição externa torna o plano inválido.

Não constituem interrupção por si:

- tarefa longa;
- necessidade de múltiplos passos;
- ausência do provider preferido quando há fallback compatível;
- reinício do processo quando existe checkpoint válido.

---

## 5. Constitution

### 5.1 Autoridade única

Existe uma única fachada `PolicyPort`. Implementações paralelas de validação NÃO
permanecem após a migração.

Guardians são políticas especializadas executadas por um único
`ConstitutionEngine`. Nenhum componente chama Guardians individualmente.

### 5.2 Fluxo canônico

```text
PolicyRequest
   ↓
normalização e contexto
   ↓
regras constitucionais invariantes
   ↓
Guardians na ordem oficial
   ↓
agregação de evidências
   ↓
PolicyDecision
   ↓
AuditPort + evento PKB quando relevante
```

### 5.3 Ordem oficial dos Guardians

1. **Sovereignty:** propriedade, consentimento e controle dos dados.
2. **Truth:** evidência, incerteza e não fabricação.
3. **Safety/Risk:** risco físico, financeiro, legal, reputacional e operacional.
4. **Privacy:** minimização e exposição.
5. **Continuity:** preservação e recuperabilidade.
6. **Knowledge Heritage:** integridade e portabilidade do conhecimento.
7. **Symbiosis:** impacto no sistema hospedeiro.
8. **Cognitive Growth:** ampliação, não substituição da autonomia.
9. **Human-Centered Evolution:** esforço e compreensão do usuário.

Nomes atuais em português ou inglês podem ser mapeados durante a migração. A
ordem final deve ser estável e versionada.

### 5.4 Tipos de decisão

- `ALLOW`: ação permitida.
- `ALLOW_WITH_CONDITIONS`: permitida mediante condições verificáveis.
- `REQUIRE_CONFIRMATION`: exige decisão humana no momento do efeito.
- `DEFER`: faltam evidências ou contexto.
- `DENY`: ação proibida.

Cada decisão inclui:

- código;
- razão em linguagem de sistema;
- explicação apropriada à interface;
- regras e Guardians acionados;
- evidências;
- nível de confiança;
- condições;
- validade temporal;
- versão da Constitution.

### 5.5 Pontos obrigatórios de validação

- aceitação inicial de missão, quando sensível;
- aprovação do plano;
- antes de cada efeito externo;
- antes de persistir conhecimento sensível;
- antes de compartilhar ou exportar dados;
- antes de instalar capacidades;
- após replanejamento que altere risco;
- antes de conclusão quando o resultado contém incerteza material.

### 5.6 Integração com PKB

Policy decisions relevantes geram `KnowledgeEvent` auditável, mas a Constitution
NÃO grava diretamente no store. Ela emite evento pelo `AuditPort` e pelo
`KnowledgePort`.

O registro deve preservar minimização: não duplicar segredo ou conteúdo pessoal
quando hashes, referências ou metadados forem suficientes.

---

## 6. PKB

### 6.1 Modelo oficial

Existe um único `KnowledgeEvent`, versionado por schema, contendo:

- `id`;
- `event_type`;
- `domain`;
- `title`;
- `content`;
- `summary`;
- `confidence`;
- `epistemic_status`;
- `lifecycle`;
- `source` e proveniência;
- `mission_id`, `session_id` e correlação;
- relações com outros eventos;
- tags e metadados;
- versão e ancestralidade;
- timestamps;
- política de retenção e sensibilidade;
- histórico de lifecycle.

Subtipos são payloads validados, não modelos concorrentes.

### 6.2 Curator único

O Curator oficial:

1. valida schema;
2. aplica política constitucional;
3. calcula duplicidade e relações;
4. calcula Knowledge Score;
5. decide lifecycle;
6. produz justificativa auditável;
7. solicita merge, aprovação ou descarte;
8. envia comandos ao `KnowledgeStorePort`.

`curator.py` e `curator_v2.py` são fontes de comportamento para a consolidação,
não duas autoridades permanentes.

### 6.3 Lifecycle oficial

```text
OBSERVED
  → TRANSIENT
  → CANDIDATE
  → APPROVED
  → CONSTITUTIONAL
  → ARCHIVED

Transições auxiliares:
  MERGED
  REJECTED
  SUPERSEDED
  DELETED
```

Nem todo evento percorre todos os estados. Exclusão respeita soberania, auditoria
e política de retenção.

### 6.4 Knowledge Score

O score é uma decisão explicável composta por:

- relevância;
- persistência;
- reutilização;
- impacto;
- alinhamento a objetivos;
- confirmação;
- conectividade;
- atualidade.

Pesos são versionados. Score não substitui Constitution nem decisão explícita do
usuário.

### 6.5 Auditoria

Toda mutação registra:

- ator;
- missão;
- comando;
- versão anterior e nova;
- decisão do Curator;
- decisão constitucional;
- timestamp;
- causa;
- reversibilidade.

### 6.6 Persistência

`KnowledgeStorePort` define:

```text
append
get
query
update
delete
count
snapshot
rollback
export
health
```

JSON local pode ser o primeiro adaptador oficial. Banco, cloud e replicação são
adaptadores adicionais, nunca novos modelos de PKB.

### 6.7 Versionamento

- schemas possuem versão explícita;
- migrações são progressivas e reversíveis;
- leitura suporta ao menos a versão anterior durante transição;
- snapshots precedem migrações destrutivas;
- exportação usa formato portátil documentado;
- eventos são preferencialmente append-only, com supersessão explícita.

---

## 7. Providers

### 7.1 Contrato único

`ProviderPort` representa uma capacidade externa ou local. O contrato não expõe
classes de SDK.

```text
descriptor() -> CapabilityDescriptor
health() -> HealthStatus
execute(ProviderRequest) -> ProviderResult
estimate(RequestProfile) -> CostLatencyEstimate
```

Para LLMs, `ProviderRequest` inclui mensagens, ferramentas permitidas, limites,
modelo opcional e política de dados. `ProviderResult` inclui conteúdo, uso,
finish reason, evidências do provider e erro normalizado.

### 7.2 ProviderManager

Responsabilidades:

- registro e lifecycle;
- descoberta de capacidades;
- seleção por requisitos;
- health e circuit breaker;
- política de custo/latência/privacidade;
- fallback;
- rate limit;
- normalização de erros;
- observabilidade sem vazar credenciais.

O ProviderManager não interpreta intenção, não grava PKB e não decide política.

### 7.3 Registro e capacidades

Cada provider declara:

- id e versão;
- tipo;
- modelos;
- capacidades;
- limites;
- requisitos de rede;
- regiões e política de dados;
- custo estimável;
- suporte a streaming e ferramentas;
- estado de saúde.

Capability Registry e Provider Registry convergem para contratos coordenados,
mantendo responsabilidades distintas: capacidade descreve **o que** é necessário;
provider descreve **quem** pode executar.

### 7.4 Fallback

Fallback ocorre apenas entre providers compatíveis com:

- capacidade;
- política;
- qualidade mínima;
- formato de saída;
- orçamento;
- autorização de dados.

Mudança de provider não pode alterar silenciosamente risco, privacidade ou
efeitos. Fallback é registrado na missão.

### 7.5 Offline

Sem provider remoto:

1. usar capacidade local compatível;
2. executar regras determinísticas;
3. preservar missão como retomável;
4. informar limitação;
5. nunca apresentar template simulado como resposta de IA real;
6. não perder contexto nem checkpoint.

`MockProvider` permanece somente para desenvolvimento, demonstração explicitamente
rotulada e testes.

---

## 8. Core Apps

### 8.1 Regra geral

Core Apps são bounded contexts. Eles oferecem capacidades ao Capability Router e
não possuem Kernel, Constitution, ProviderManager ou PKB próprios.

Um Core App:

- recebe `CapabilityRequest`;
- aplica regras de domínio;
- solicita providers ou agentes por portas;
- propõe eventos ao PKB;
- devolve `CapabilityResult`;
- não produz efeitos externos diretamente.

### 8.2 Atlas

Responsável por:

- patrimônio, ativos, passivos e fluxo de caixa;
- objetivos financeiros;
- cenários e simulações;
- perfil e limites financeiros;
- rastreabilidade de premissas.

Atlas NÃO executa transações, não substitui aconselhamento profissional e não
duplica o módulo FIN. Operações sensíveis exigem PolicyPort e confirmação.

### 8.3 Logos

Responsável por:

- projetos intelectuais;
- documentos, notas e pesquisa;
- decisões e relações;
- recuperação e síntese de conhecimento;
- organização de artefatos.

Logos não é a PKB. Ele usa a PKB como infraestrutura de conhecimento e adiciona
semântica de domínio.

### 8.4 OEM Studio

Responsável por:

- projetos de engenharia;
- requisitos, peças e versões;
- documentos técnicos;
- protótipos e print jobs;
- rastreabilidade de decisões técnicas.

Não controla arquivos ou equipamentos sem HostPort e política.

### 8.5 Novos Core Apps

Um novo Core App exige:

1. bounded context e vocabulário definidos;
2. capacidades declaradas;
3. contratos de entrada e saída;
4. ausência de dependência em adaptadores;
5. mapeamento de eventos PKB;
6. política de risco;
7. testes de contrato;
8. registro pelo Capability Router;
9. aprovação arquitetural.

Core Apps não são criados apenas para agrupar telas.

---

## 9. Agentes

### 9.1 Papel

Agentes são executores especializados, efêmeros ou retomáveis, convocados pelo
Mission Engine para realizar uma tarefa limitada.

Eles podem:

- analisar;
- pesquisar;
- propor plano;
- gerar artefato;
- validar resultado;
- operar uma ferramenta permitida.

Eles não podem:

- alterar o objetivo da missão;
- conceder a si mesmos permissão;
- escolher política;
- persistir conhecimento diretamente;
- controlar outros agentes fora do plano;
- executar efeito sensível sem confirmação;
- tornar-se interface alternativa do usuário.

### 9.2 Lifecycle

```text
REGISTERED
  → ASSIGNED
  → RUNNING
  → WAITING
  → COMPLETED

ou:
  BLOCKED
  CANCELLED
  FAILED
```

Cada tarefa de agente possui escopo, orçamento, prazo, capacidades, ferramentas,
entradas, formato de saída e critério de aceite.

### 9.3 Relação com Mission Engine

- Mission Engine cria `AgentTask`.
- Agent Orchestrator seleciona implementação compatível.
- Agente devolve `AgentResult` e evidências.
- Mission Engine verifica e decide o próximo passo.
- Checkpoints pertencem à missão.

### 9.4 Relação com Providers

Agentes não instanciam SDKs. Solicitam `ProviderRequest` pelo ProviderPort, com
limites definidos pela tarefa e pela política.

### 9.5 Relação com PKB

Agentes propõem `KnowledgeCandidate`. Somente o KnowledgePort e o Curator decidem
persistência, merge, lifecycle e score.

---

## 10. Interfaces

### 10.1 Regra

CLI, FastAPI e Desktop são adaptadores da mesma `IntentPort`. Não existem Kernel
especializado, store separado ou fluxo de processamento próprio por interface.

### 10.2 CLI

Responsável por:

- traduzir comandos e texto em requests;
- apresentar responses;
- stream de progresso;
- códigos de saída;
- modo diagnóstico autorizado.

Não contém regra de missão ou domínio.

### 10.3 FastAPI

Responsável por:

- transporte HTTP;
- autenticação e limites da borda;
- validação de DTOs;
- mapeamento para contratos;
- streaming;
- códigos HTTP;
- serialização.

Models Pydantic da API não atravessam a porta.

### 10.4 Desktop

Responsável por:

- Cognitive Shell;
- voz, acessibilidade e visualização;
- estado de apresentação;
- notificações;
- confirmação na interface;
- conexão com o mesmo Kernel.

Desktop não executa providers nem grava PKB diretamente.

### 10.5 Intent Design System

O [Intent Design System](design/README.md) é o contrato normativo da camada de
apresentação. Ele orienta CLI, Desktop e futuras interfaces visuais sem alterar
os contratos canônicos da aplicação.

- IDS e componentes visuais consomem somente contratos públicos.
- Kernel, Mission Engine, Constitution, PKB, Providers e Core Apps não importam
  tokens ou componentes visuais.
- Estados de apresentação traduzem estados canônicos; não criam regras de
  negócio, permissões ou persistência.
- O pacote histórico `intent_kernel/ids` permanece como adaptador legado de
  apresentação até uma missão futura de migração.
- A especificação visual pode evoluir sem alterar a arquitetura técnica
  canônica.

### 10.6 Paridade

O mesmo request, identidade, contexto e capacidades devem produzir resultado
semanticamente equivalente em todas as interfaces. Diferenças permitidas:

- formatação;
- streaming;
- recursos de acessibilidade;
- componentes visuais transitórios.

Testes de contrato devem executar a mesma suíte contra os três adaptadores.

### 10.7 Bootstrap canônico

`ApplicationFactory` é o único Composition Root oficial. CLI, FastAPI e
Desktop obtêm o mesmo grafo de aplicação por ela. Configuração de ambiente,
Providers, stores, registries, Core Apps e adaptadores ocorre no
`KernelBuilder`, nunca nas interfaces ou classes de domínio.

`Kernel()` sem argumentos permanece exclusivamente como caminho de
compatibilidade caracterizado e deve declarar esse modo em diagnóstico. Novos
pontos de entrada não podem utilizá-lo.

O inventário operacional de entradas está em
[`BOOTSTRAPS.md`](BOOTSTRAPS.md), e as condições de retirada do legado estão em
[`DEPRECATION_POLICY.md`](DEPRECATION_POLICY.md).

---

## 11. Estratégia de migração

Nenhuma linha desta tabela autoriza alteração nesta Sprint 0.5.

| Componente atual | Destino canônico | Ação futura |
|---|---|---|
| `kernel.py` | Kernel/Fachada oficial | migrar incrementalmente |
| `types.py` | contratos canônicos versionados | separar por contexto sem quebrar compatibilidade |
| `engine/intent_engine.py` | Intent Understanding dentro da aplicação | preservar e evoluir por contrato |
| `engine/pipeline.py` | ExecutionPort/Pipeline oficial | incorporar checkpoints e passos |
| `engine/nodes.py` | biblioteca de passos | migrar nós para contratos de execução |
| `conversation/` | adaptador conversacional/Cognitive Shell | retirar regras duplicadas de aplicação |
| `bus/event_bus.py` | EventPort + adaptador em memória | manter como primeiro adaptador |
| `capabilities.py` | Capability Registry oficial | consolidar descritores |
| `router/module_router.py` | Capability Router | migrar |
| `constitution/models.py` | modelo canônico de política | migrar |
| `constitution/defaults.py` | configuração versionada | migrar |
| `constitution/checker.py` | ConstitutionEngine | incorporar, removendo fluxo paralelo ao final |
| `constitution/guardians/*` | Guardians oficiais | mapear, ordenar e consolidar |
| `continuidade.py` e `continuity.py` | Guardian de continuidade único | incorporar comportamentos e retirar duplicidade |
| `pkb/models.py` | `KnowledgeEvent` oficial | manter como base e versionar |
| `pkb/curator.py` | Curator oficial | migrar comportamento v1 caracterizado |
| `pkb/curator_v2.py` | Curator oficial | incorporar score, auditoria e decisões |
| `pkb/score.py` | Knowledge Score oficial | migrar e versionar pesos |
| `pkb/knowledge_manager.py` | KnowledgePort/application service | migrar |
| `pkb/store.py` | KnowledgeStorePort | adotar como contrato único |
| `pkb/json_store.py` | adaptador JSON legado/inicial | migrar para a porta |
| `pkb/persistence_store.py` | adaptador oficial candidato | incorporar o que superar testes de contrato |
| `persistence/` | infraestrutura genérica de persistência | delimitar fora da PKB |
| `providers/base.py` | ProviderPort | incorporar contrato mínimo |
| `providers/layer.py` | registry e interfaces de adaptadores | incorporar capacidades úteis |
| `providers/manager.py` | ProviderManager oficial | migrar seleção e fallback |
| `providers/mock_provider.py` | adaptador de teste/demo | manter explicitamente não produtivo |
| `providers/openai_provider.py` | adaptador OpenAI | migrar após testes de contrato |
| `modules/core` | capacidade geral mínima | reduzir ou absorver pela aplicação |
| `modules/fin` | Atlas | migrar comportamento e descontinuar duplicidade |
| `modules/atlas` | Core App Atlas | oficializar |
| `modules/logos` | Core App Logos | oficializar |
| `modules/oem_studio` | Core App OEM Studio | oficializar |
| `agents/` | AgentPort + Agent Orchestrator | migrar lifecycle e contratos |
| `continuity/` | MissionStore/continuidade cognitiva | dividir responsabilidades por porta |
| `local/` | adaptadores locais | migrar dados e operações para portas |
| `symbiotic/` | HostPort/adaptador de ambiente | migrar; remover acesso direto do núcleo |
| `evolution/` v1/v2/v3 | serviços de análise cognitiva | consolidar depois da PKB oficial |
| `cognitive_map/` | projeção da PKB | manter como read model |
| `home/` | apresentação/Cognitive Shell | mover responsabilidade visual |
| `workspace/` | apresentação + contexto de missão | separar UI de aplicação |
| `monitor/` e `monitor/v2.py` | observabilidade interna | consolidar fora da experiência comum |
| `ids/` | design system do Desktop | manter como adaptador de apresentação |
| `onboarding/` | fluxo do Desktop | migrar para Cognitive Shell |
| `server/app.py` | adaptador FastAPI | tornar fino |
| `intent_kernel/__main__.py` | adaptador CLI | tornar fino |
| `intent_os_desktop/` | adaptador Desktop | substituir painel técnico pelo Shell em Sprint própria |
| `rc1/` | Legacy/registro histórico | arquivar após extrair contratos úteis |
| RC1/RC1.5 empacotado | release legacy | preservar, não evoluir como arquitetura v2 |

### 11.1 Regra de substituição

Um componente legado só pode ser arquivado quando:

1. comportamento relevante estiver caracterizado;
2. contrato canônico estiver aprovado;
3. adaptador novo passar testes de contrato;
4. dados possuírem migração e rollback;
5. consumidor tiver migrado;
6. observabilidade confirmar equivalência;
7. decisão for registrada.

---

## 12. Roadmap técnico

### Sprint 1 — Contratos canônicos e esqueleto de aplicação

**Objetivo**

Criar os contratos v2.0 sem substituir implementações atuais.

**Componentes**

- package de contratos versionados;
- `IntentPort`;
- `MissionPort` e modelos de missão;
- `PolicyPort`;
- `ProviderPort`;
- `KnowledgePort` e `KnowledgeStorePort`;
- `CoreAppPort`;
- `AgentPort`;
- testes de contrato;
- adaptadores de compatibilidade para o Kernel atual.

**Risco**

Definir contratos que apenas reproduzam classes existentes ou que vazem detalhes
de FastAPI, JSON e OpenAI.

**Dependências**

- baseline da Sprint 0;
- aprovação deste documento;
- recuperação ou incorporação posterior de `ArchitectureReview.md`;
- inventário de consumidores.

**Critério de conclusão**

- contratos aprovados;
- dependências apontando para dentro verificadas;
- comportamento atual preservado;
- interfaces atuais operando por adaptadores de compatibilidade;
- nenhum componente legado removido;
- baseline sem novas falhas.

**Sequência recomendada**

1. definir IDs, erros e envelopes transversais;
2. definir Mission e lifecycle;
3. definir portas sem implementações;
4. criar testes de contrato;
5. criar adaptadores de compatibilidade;
6. verificar CLI, API e Desktop contra a mesma fachada;
7. documentar qualquer divergência antes de prosseguir.

### Sprint 2 — Constitution e PKB únicas

**Objetivo**

Consolidar política e conhecimento atrás das portas canônicas, preservando dados e
comportamentos caracterizados.

**Componentes**

- ConstitutionEngine único;
- Guardian Registry oficial;
- PolicyDecision e auditoria;
- KnowledgeEvent versionado;
- Curator único;
- Knowledge Score;
- KnowledgeStorePort;
- adaptador JSON;
- migração e rollback de dados.

**Risco**

Alterar lifecycle, score, serialização, decisões constitucionais ou dados
persistidos.

**Dependências**

- Sprint 1;
- caracterização específica de `curator_v2.py`, `store.py` e schemas;
- backup verificável.

**Critério de conclusão**

- nenhum fluxo paralelo ativo;
- testes de contrato e migração aprovados;
- export/import round-trip;
- decisões explicáveis;
- rollback demonstrado;
- consumidores usando somente as portas.

### Sprint 3 — Mission Engine, Providers e Agents

**Objetivo**

Estabelecer missão retomável e execução agnóstica a providers.

**Componentes**

- Mission Engine;
- Mission Store;
- Pipeline com checkpoints;
- ProviderManager único;
- Mock e OpenAI por ProviderPort;
- fallback e offline;
- Agent Orchestrator;
- lifecycle de AgentTask;
- idempotência e bloqueios.

**Risco**

Repetir efeitos, perder contexto, fallback incompatível, agentes ultrapassarem
escopo ou mudanças de resposta não intencionais.

**Dependências**

- Sprints 1 e 2;
- testes de provider com doubles;
- política de efeitos e autorização;
- persistência de missão.

**Critério de conclusão**

- missão longa retoma após reinício;
- bloqueios oficiais funcionam;
- ausência de provider não perde missão;
- agentes não acessam store ou SDK diretamente;
- fallback é auditado;
- efeitos são idempotentes.

### Sprint 4 — Core Apps e interfaces convergentes

**Objetivo**

Conectar Atlas, Logos e OEM Studio ao Kernel único e fazer CLI, FastAPI e Desktop
compartilharem a mesma aplicação.

**Componentes**

- CoreAppPort;
- Atlas oficial com migração de FIN;
- Logos oficial;
- OEM Studio oficial;
- Capability Router;
- adaptadores CLI, FastAPI e Desktop finos;
- Cognitive Shell;
- testes de paridade;
- arquivo dos componentes RC1 substituídos.

**Risco**

Levar regras para a UI, expor arquitetura interna, divergência entre interfaces e
remoção prematura de legado.

**Dependências**

- Sprints 1–3;
- contratos de cada domínio;
- critérios de UX e acessibilidade;
- plano de compatibilidade.

**Critério de conclusão**

- mesmo caso de uso passa pelas três interfaces;
- Core Apps não importam adaptadores;
- FIN não possui fluxo ativo paralelo;
- painel técnico não define a experiência comum;
- legado só é arquivado conforme regra de substituição;
- testes de aceitação e paridade aprovados.

---

## 13. Componentes oficiais v2.0

1. Kernel/Fachada única
2. Intent Understanding
3. Mission Engine
4. ConstitutionEngine + Guardians
5. Pipeline/Execution Engine
6. Capability Router e Registry
7. ProviderManager + ProviderPort
8. Agent Orchestrator + AgentPort
9. PKB + Curator + Knowledge Score
10. KnowledgeStorePort e adaptadores
11. EventPort/Event Bus
12. Atlas
13. Logos
14. OEM Studio
15. CLI adapter
16. FastAPI adapter
17. Desktop/Cognitive Shell adapter
18. Mission/continuity store
19. Host adapters
20. Observabilidade e auditoria

## 14. Componentes declarados legados ou transitórios

- RC1 e suas telas administrativas;
- módulo FIN separado de Atlas;
- Curators v1 e v2 como autoridades simultâneas;
- múltiplos stores sem porta única;
- múltiplos contratos de provider;
- validações constitucionais paralelas;
- Guardians de continuidade duplicados;
- regras de aplicação dentro de CLI, FastAPI ou Desktop;
- MockProvider apresentado como inteligência produtiva;
- acesso direto do núcleo ao hospedeiro.

Legado não significa descartável. Cada componente é fonte de comportamento,
testes e requisitos até completar sua migração.

---

## 15. Decisões arquiteturais vinculantes

1. A unidade principal de trabalho v2.0 é `Mission`.
2. `Kernel.process` é fachada de compatibilidade, não pipeline independente.
3. Existe uma única Constitution e um único fluxo de PolicyDecision.
4. Existe uma única PKB, um único KnowledgeEvent e um único Curator.
5. Providers e Agents são executores sem autoridade sobre missão ou conhecimento.
6. Core Apps são bounded contexts conectados por portas.
7. Todas as interfaces compartilham o mesmo Kernel.
8. Efeitos externos exigem adaptadores, política, idempotência e auditoria.
9. Offline preserva continuidade e explicita limitações.
10. Nenhum legado é removido antes de contrato, migração, testes e rollback.

### Estado de migração de domínios — Sprint 8

- Atlas é o proprietário oficial de Finance.
- Logos é o proprietário oficial de Research, Writing, Planning e Education.
- OEM Studio é o proprietário oficial de Engineering e Programming.
- Programming permanece parcialmente migrado porque a precedência
  caracterizada do classificador foi preservada.
- Business, Marketing, Data, Creativity, Legal, Life e Other permanecem como
  fallbacks legados explícitos.
- Um domínio migrado deve ter uma capability e um Core App proprietário e não
  pode retornar silenciosamente ao `ModuleRouter`.
- Fallbacks de compatibilidade são inventariados, testados e observáveis.
- As evidências detalhadas estão em `DOMAIN_MIGRATION_MATRIX.md` e
  `LEGACY_FALLBACKS.md`.

## 16. Critério de adoção desta arquitetura

Architecture Target v2.0 torna-se canônica quando:

- revisada pela equipe;
- conflitos com `ArchitectureReview.md`, quando recuperado, forem resolvidos;
- contratos da Sprint 1 forem derivados sem alterar comportamento;
- toda exceção futura for registrada em ADR;
- Sprints seguintes referenciarem este documento como fonte de verdade.

## 17. Product Alpha 1 interface binding

The Windows UI obtains one canonical graph through `ApplicationFactory` inside a packaged private
bridge. Communication is process-local stdio; no network listener exists. Credentials remain owned
by the Windows host and are supplied in memory to the bridge. The UI does not access PKB, Core Apps,
Provider implementations, Constitution, or Mission Engine directly.
