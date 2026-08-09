# IDS-004 — Component Foundation

## 1. Propósito

Os componentes fundacionais transformam princípios em contratos de
apresentação. Recebem dados e comandos por interfaces públicas; não contêm
regra de negócio, não acessam Providers ou persistência e não decidem
permissões.

## 2. Componentes canônicos

| Componente | Responsabilidade | Estados mínimos | Acessibilidade |
|---|---|---|---|
| Mission Surface | objetivo, estado e próxima ação | vazio, ativo, aguardando, concluído, bloqueado | título semântico e atualização anunciada |
| Conversation Input | texto, voz e anexos autorizados | vazio, digitando, gravando, enviando, erro | rótulo, teclado, transcrição e cancelamento |
| Capability Chip | capacidade disponível ou escolhida | disponível, selecionada, indisponível | nome humano e motivo |
| Context Drawer | contexto sob demanda | fechado, aberto, carregando, erro | foco contido e fechamento previsível |
| Cognitive Pulse | atividade observável | conforme IDS-001 | texto e movimento reduzido |
| Mission Timeline | etapas e eventos | atual, concluído, futuro, bloqueado | lista ordenada e estado textual |
| Evidence Panel | fonte, confiança e proveniência | disponível, parcial, ausente, conflitante | links descritivos |
| Confirmation Panel | autorização antes de efeito | revisão, confirmado, cancelado, expirado | consequência explícita |
| Risk Signal | risco, limite ou bloqueio | informativo, aviso, crítico | ícone, texto e cor redundantes |
| Knowledge Card | conhecimento e relações | atual, candidato, obsoleto, conflitante | origem, data e ação nomeada |
| Connection Thread | relações entre conhecimentos | direto, inferido, conflitante | relação em linguagem |
| Document Canvas | documento protagonista | leitura, edição, revisão, comparação | estrutura semântica e zoom |
| Metric Hero | métrica essencial | estável, alta, baixa, indisponível | valor, unidade, período e tendência |
| Portfolio Summary | composição e renda | completo, parcial, desatualizado | tabela equivalente ao gráfico |

## 3. Anatomia comum

Todo componente pode conter identidade do objeto, conteúdo principal, estado,
evidência, ação primária, ações secundárias sob demanda e recuperação de erro.
Elementos ausentes não reservam ruído visual. A ordem é coerente entre tela,
teclado e tecnologia assistiva.

## 4. Estados de interação

Controles especificam default, hover, focus-visible, pressed/selected,
disabled, loading, success, warning e error. Nenhum estado depende apenas de
cor. Loading permite cancelamento quando suportado. Disabled não substitui
explicação de política ou permissão.

## 5. Regras de composição

- uma região possui no máximo uma ação primária;
- conteúdo protagonista vem antes de métricas auxiliares;
- painéis laterais não interrompem leitura ou conversa;
- confirmação aparece próxima à consequência;
- risco acompanha o objeto afetado;
- evidência não se mistura com recomendação;
- cartões agrupam; não envolvem cada fragmento;
- elevação indica relação espacial real;
- componentes técnicos aparecem somente quando solicitados.

## 6. Tokens

Componentes usam apenas tokens semânticos do IDS-002. É proibido codificar
cores diretamente, criar escalas locais incompatíveis, usar movimento fora dos
tokens, introduzir tipografia por módulo ou importar tokens no Kernel.

## 7. Responsividade e densidade

A ordem de importância permanece em qualquer tamanho; controles críticos não
desaparecem; tabelas oferecem alternativa aos gráficos; densidade varia por
espaço e nível cognitivo; alvos de toque são adequados; zoom não causa rolagem
bidimensional em tarefas básicas.

## 8. Baseline de acessibilidade

- WCAG 2.2 AA;
- operação integral por teclado;
- foco persistente e visível;
- landmarks, headings e nomes acessíveis;
- anúncios moderados de atualizações;
- descrição textual de dados;
- movimento reduzido e alto contraste;
- escala de texto sem perda funcional;
- erros explicados e recuperáveis;
- linguagem simples e reformulação;
- voz acompanhada de texto e controle explícito.

## 9. Promoção futura

Um componente só se torna implementação oficial quando demonstra necessidade,
possui contrato independente de infraestrutura, documenta todos os estados,
passa por testes de teclado, contraste, escala e leitor de tela, preserva
Silent UI e Attention Principle, não duplica componente e possui regressão
visual apropriada.

