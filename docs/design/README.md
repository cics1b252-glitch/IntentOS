# Intent Design System

Status: fundação normativa de design. Este diretório especifica a experiência
visual do Intent OS; ele não introduz uma nova interface nem altera o
comportamento da aplicação.

## Propósito

O Intent Design System (IDS) preserva uma identidade reconhecível enquanto a
interface se adapta à tarefa, ao contexto e às necessidades de acessibilidade
do usuário. A experiência deve transmitir calma, continuidade, clareza e
inteligência sem expor a arquitetura interna.

## Princípios

1. **Living Interface** — a atmosfera pode mudar de forma gradual e limitada,
   mas a identidade permanece.
2. **Silent UI** — o conteúdo e a missão são protagonistas; a interface reduz
   ruído e desaparece quando não é necessária.
3. **Attention Principle** — a apresentação orienta atenção sem competir com o
   trabalho.
4. **Visual Continuity** — atualizações amadurecem a linguagem visual sem
   romper reconhecimento, posição dos controles essenciais ou memória de uso.
5. **Progressive Disclosure** — detalhes aparecem conforme a necessidade e o
   nível cognitivo escolhido, nunca todos ao mesmo tempo.
6. **Accessibility by default** — contraste, foco, teclado, leitura assistiva,
   texto alternativo e movimento reduzido fazem parte da fundação.
7. **Human-Centered Evolution** — o sistema adapta a apresentação ao usuário,
   sem inferir estados psicológicos nem exigir que ele aprenda a arquitetura.

## Documentos oficiais

- [IDS-001 — Living Interface](IDS-001_LIVING_INTERFACE.md)
- [IDS-002 — Color System](IDS-002_COLOR_SYSTEM.md)
- [IDS-003 — Cognitive Spaces](IDS-003_COGNITIVE_SPACES.md)
- [IDS-004 — Component Foundation](IDS-004_COMPONENT_FOUNDATION.md)
- [IDS-005 — Theme Engine](IDS-005_THEME_ENGINE.md)
- [IDS-006 — Cognitive Interaction](IDS-006_COGNITIVE_INTERACTION.md)
- [IDS-007 — Cognitive Components](IDS-007_COGNITIVE_COMPONENTS.md)
- [IDS-008 — Cognitive Shell](IDS-008_COGNITIVE_SHELL.md)

## Fronteira arquitetural

```text
Usuário
  ↓
Interfaces (CLI / Desktop / API)
  ↓
IDS e adaptadores de apresentação
  ↓
Contratos públicos da aplicação
  ↓
Kernel / Mission Engine / Core Apps / PKB
```

As dependências fluem para os contratos públicos. Kernel, Mission Engine, PKB,
Providers, Constitution e Core Apps nunca dependem de componentes visuais,
tokens ou estados de apresentação.

O pacote histórico `intent_kernel/ids` continua preservado por compatibilidade.
Ele é uma implementação de apresentação anterior a esta especificação e não
define, por si só, a linguagem canônica. Uma migração futura deverá ocorrer em
missão própria, com testes visuais e sem acoplamento ao Kernel.

## Implementação executável

A fundação canônica e independente está em `ui/ids`. Ela fornece tokens,
Theme Engine, resolver, tipografia, layout, motion, ícones, componentes
genéricos, validações de acessibilidade e showcase. O pacote não é uma interface
do produto e não substitui o Desktop atual nesta missão.

## Governança

- Estes documentos são a referência normativa do IDS.
- Tokens são contratos semânticos; valores concretos podem amadurecer sem
  alterar seus significados.
- Mudanças de identidade exigem justificativa, validação de acessibilidade e
  análise de continuidade visual.
- Adaptações contextuais devem ser determinísticas, explicáveis, reversíveis e
  subordinadas às preferências do usuário.
- Nenhum padrão visual pode sugerir consciência, emoção, diagnóstico,
  vigilância ou certeza inexistente.

## Fora de escopo desta fundação

- escolher biblioteca de interface;
- substituir interfaces atuais;
- implementar temas ou componentes;
- criar personalização automática;
- alterar rotas, contratos, dados ou comportamento do produto;
- inferir humor, saúde mental, personalidade ou estado psicológico.
