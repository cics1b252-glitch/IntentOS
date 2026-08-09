# IDS-008 — Cognitive Shell

> Windows Alpha: Studio 2.5 hosts this same Shell in a native WebView2 window. The query
> `host=windows-alpha` adds only a discreet local-demonstration label; it does not redesign the
> Shell or bind it to the Kernel.

> Product Alpha 1 supersedes that default demonstration surface with a conversation-first Portuguese
> experience. Demonstration fixtures are now opt-in and visibly labelled. The Product UI communicates
> through the Windows application bridge and never imports concrete Kernel or Provider implementations.

Status: primeira interface executável de apresentação do Intent OS.

## Propósito e responsabilidades

O Cognitive Shell é o host visual principal demonstrativo. Ele organiza a
experiência em torno da missão e mostra somente estados públicos. Nesta versão,
todo conteúdo vem de fixtures locais identificadas como demonstração. O Shell
não executa ações externas e não se conecta à arquitetura da aplicação.

Responsabilidades:

- fornecer navegação local compreensível;
- organizar missões, workspace, contexto e atividade;
- compor componentes base e cognitivos do IDS;
- aplicar preferências pelo Theme Engine existente;
- responder de forma acessível a tamanhos de viewport diferentes;
- manter estado de apresentação recriável e serializável.

## Estrutura visual

```text
Cognitive Shell
├── Global Navigation
├── Mission Rail
├── Primary Workspace
├── Context Panel
├── Activity Layer
└── System Status Area
```

A missão ocupa o centro da experiência. Painéis complementares podem ser
recolhidos; a informação primária permanece no workspace.

## Global Navigation

Home, Missions, Knowledge, Atlas, OEM Studio e Settings compartilham um roteador
hash local. Home, Missions e Settings são demonstrativos completos. Os futuros
workspaces são itens desabilitados na navegação principal e possuem placeholder
acessível quando acessados diretamente. O item atual usa `aria-current`.

## Mission Rail

Apresenta Mission Cards locais agrupados em Active e Recent. Suporta seleção,
estado vazio, recolhimento e conteúdo longo. Em desktop é uma coluna; em tablet
e viewport estreito torna-se painel sobreposto. A seleção altera somente o
estado visual local.

## Primary Workspace

Suporta `welcome`, `empty`, `mission-selected`, `preparing`, `running`,
`waiting-for-user`, `completed`, `failed` e `unavailable`. Home reúne missões
recentes, capacidades e atividade. Missions reúne a missão selecionada e sua
atividade pública. Nenhum Mission Workspace completo foi criado.

## Context Panel

Compõe Context Cards, Provenance Cards, Capability Badges, Agent Status e
Knowledge Relationships. Pode estar aberto, fechado ou fixado. Em layouts
menores é sobreposto; ao abrir, o primeiro controle recebe foco. Escape fecha o
painel não fixado antes de fechar o Mission Rail.

## Activity Layer

Compõe Cognitive Pulse, Execution Indicator, Decision Timeline e Confidence
Indicator somente quando confiança foi fornecida. Seus estados públicos cobrem
idle, preparação, execução, espera, confirmação, conclusão e falha. Não
representa operações internas privadas.

## System Status

Área discreta com estado local, eixos do tema, conectividade simulada,
disponibilidade simulada de providers e indicação inequívoca de demonstração.
Não apresenta CPU, memória ou métricas técnicas.

## Responsividade

- **Desktop:** navegação expandível, Mission Rail, workspace e Context Panel.
- **Tablet:** navegação compacta e painéis laterais sobrepostos/recolhíveis.
- **Viewport estreito:** workspace prioritário, navegação inferior e painéis em
  drawer, sem largura fixa ou rolagem horizontal criada pelo Shell.

Breakpoints e dimensões usam exclusivamente tokens existentes. Zoom e Forced
Colors são tratados pelas regras fluídas e media queries do IDS.

## Acessibilidade

- skip link para o workspace;
- landmarks e hierarquia de headings;
- item atual e itens indisponíveis identificados semanticamente;
- foco visível, controles nativos e ordem linear;
- painéis abertos recebem foco em seu primeiro controle;
- Escape fecha camadas locais não fixadas;
- nenhum estado depende somente de cor, ícone ou movimento;
- Reduced Motion e Forced Colors;
- conteúdo redimensionável e quebra de texto;
- ausência de armadilhas intencionais de teclado.

## Contrato de estado

`ui/shell/state.js` normaliza um objeto simples:

```text
route
navigation
selectedMission
missions
workspaceState
context / provenance / capabilities / agents / relationships
activity
systemStatus
panels
preferences
```

Defaults seguros permitem recriar integralmente a interface mesmo com dados
ausentes. Os contratos cognitivos normalizam os itens compostos. Nenhum modelo
de domínio é importado.

## Limites arquiteturais

O Shell não importa Kernel, Mission Engine, Constitution, PKB, Providers, Core
Apps ou lógica de domínio. Não possui `fetch`, autenticação, persistência de
missões, streaming, telemetria ou ação externa. Preferências visuais utilizam a
persistência já fornecida pelo Theme Engine.

## Integração futura

Um adaptador de apresentação poderá fornecer ao Shell o mesmo contrato simples
a partir de contratos públicos da aplicação. Essa integração deverá ficar fora
do IDS e preservar a direção de dependência: aplicação → adaptador → estado do
Shell. O Shell nunca importará a implementação do Kernel.

## Registro Studio 2

- branch de origem: `feat/ids-cognitive-components`;
- hash-base: `378beb0d530be75d06d7bb0718b759acd43c6568`;
- árvore inicial: limpa;
- divergência inicial de `origin/feat/openai-integration`: 13 commits à frente.

Resultados de testes e validação visual são registrados no relatório final da
missão para manter esta especificação estável.

## Evidência de validação Studio 2

A validação real no navegador confirmou:

- carregamento do host separado e composição completa dos landmarks;
- navegação Home, Missions e Settings;
- seleção de missão e estado `waiting-for-user`;
- fechamento e reabertura do Context Panel com foco no primeiro controle;
- persistência dos quatro eixos pelo Theme Engine;
- Light/Neutral/Comfortable/Full;
- Dark/Atlas/Compact/Reduced;
- Dark/Lavender e Light/Cream;
- ausência de rolagem horizontal no viewport de desktop disponível;
- expansão, estados indisponíveis e indicação de demonstração.

A sessão de navegador disponível não expôs controle real de viewport, zoom,
Forced Colors ou leitura do console. Tentativas de teclado sintético também não
transferiram foco de forma observável. Portanto, tablet, viewport estreito,
zoom 200%, Forced Colors, sequência exclusivamente por teclado e console
permanecem validados estruturalmente por testes e CSS, mas não são declarados
como validação manual. Devem ser repetidos no primeiro host com essas
capacidades.
