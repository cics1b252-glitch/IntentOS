# IDS-002 — Color System

## 1. Objetivo

O sistema de cores organiza identidade, ambiente, ação, significado e dados.
Cores não são decoração nem substituem texto, forma, ícone ou posição.

Esta fundação define contratos semânticos. Valores finais devem ser validados
em protótipos e testes de contraste antes de se tornarem tokens distribuíveis.

## 2. Camadas de cor

| Camada | Responsabilidade | Exemplos |
|---|---|---|
| identidade | reconhecimento contínuo | lavanda cognitiva, aço calmo |
| ambiente | atmosfera dos espaços | off-white, cinza frio, creme |
| ação | controles interativos e foco | ação primária, foco |
| semântica | sucesso, aviso, erro e informação | estados explícitos |
| estado | seleção, hover, indisponibilidade, espera | superfícies |
| dados | séries e categorias | paleta ordenada e acessível |

Uma cor de identidade não herda significado de sucesso ou erro. Uma cor
semântica não deve se tornar o fundo predominante de um espaço.

## 3. Cores semânticas

- **Sucesso**: conclusão ou validação positiva confirmada.
- **Aviso**: atenção necessária, sem bloqueio definitivo.
- **Erro**: falha, dado inválido ou ação não concluída.
- **Informação**: contexto útil sem julgamento positivo ou negativo.

Verde e vermelho não são a identidade base do Atlas e não devem dominar
gráficos financeiros. São reservados a significados explícitos como variação,
limite, risco ou estado — sempre acompanhados por sinal adicional.

## 4. Tokens canônicos iniciais

### Cor

| Token | Função |
|---|---|
| `color.background` | plano mais distante da aplicação |
| `color.surface` | superfície padrão de conteúdo |
| `color.surface.elevated` | superfície temporária ou sobreposta |
| `color.border.subtle` | separação de baixa ênfase |
| `color.text.primary` | conteúdo principal |
| `color.text.secondary` | metadado e explicação |
| `color.action.primary` | ação principal e foco contextual |
| `color.semantic.success` | sucesso confirmado |
| `color.semantic.warning` | atenção ou risco não bloqueante |
| `color.semantic.error` | falha ou bloqueio |
| `color.semantic.info` | informação contextual |
| `color.cognitive.lavender` | Cognitive Shell |
| `color.cognitive.steel` | missão, operação e engenharia |
| `color.cognitive.cream` | leitura, documento e conhecimento |

### Espaçamento, forma, tipo e movimento

| Família | Tokens |
|---|---|
| espaçamento | `spacing.xs`, `spacing.sm`, `spacing.md`, `spacing.lg`, `spacing.xl` |
| raio | `radius.sm`, `radius.md`, `radius.lg` |
| sombra | `shadow.soft`, `shadow.elevated` |
| tipografia | `typography.body`, `typography.label`, `typography.title`, `typography.display` |
| movimento | `motion.fast`, `motion.normal`, `motion.slow` |

Os valores concretos devem existir futuramente em um artefato versionado de
tokens, gerado para plataformas de apresentação. Eles não residem no Kernel
nem são importados por contratos de domínio.

## 5. Atmosfera por espaço

| Espaço | Base ambiental | Identidade de apoio |
|---|---|---|
| Cognitive Shell | off-white neutro | lavanda radial discreta |
| Mission Workspace | cinza frio | azul-aço |
| Knowledge | creme/papel | sépia suave |
| Atlas | neutro editorial | cor somente em dados e estados |

## 6. Visualização de dados

- usar poucas séries simultâneas;
- manter ordem cromática consistente;
- diferenciar por rótulo, símbolo ou padrão além da cor;
- evitar arco-íris sem semântica e gradientes que distorçam magnitude;
- não usar 3D;
- manter a mesma categoria com a mesma cor;
- expor valores e unidades por texto.

## 7. Contraste e estados

Meta mínima: WCAG 2.2 AA.

- texto normal: contraste mínimo de 4,5:1;
- texto grande: mínimo de 3:1;
- componentes e indicadores de foco: mínimo de 3:1;
- estados disabled permanecem legíveis;
- hover não é o único indicador de interatividade;
- foco é visível em qualquer superfície;
- temas futuros preservam a mesma semântica.

## 8. Validação

Antes de promover valores concretos: validar contraste automático e manual,
testar daltonismo e monocromia, alto contraste e escala, confirmar gráficos sem
legenda cromática implícita e registrar o impacto de continuidade de qualquer
mudança.

