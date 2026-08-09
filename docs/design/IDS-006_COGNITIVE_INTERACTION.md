# IDS-006 — Cognitive Interaction

Status: especificação executável da apresentação cognitiva.

## Propósito e princípios

A interação cognitiva traduz estados públicos e observáveis em uma experiência
calma, compreensível e acessível. Ela não descreve processos privados, não
simula personalidade e não expõe arquitetura interna. A aplicação fornece os
dados; o IDS apenas normaliza e apresenta.

- **Living Interface:** estados mudam sem romper identidade.
- **Silent UI:** somente informação necessária recebe destaque.
- **Principle of Attention:** falha, confirmação e bloqueio têm prioridade.
- **Cognitive Spaces:** densidade e atmosfera vêm do Theme Engine.
- **Progressive Disclosure:** resumo primeiro, detalhes públicos sob demanda.
- **Observabilidade:** todo estado exibido vem de contrato público.

## Estados observáveis e Cognitive Pulse

Os significados compartilhados são sucesso, aviso, erro, informação, espera,
desabilitado, restrito e indisponível. Cada um combina texto, símbolo, estrutura
e token semântico.

O Pulse comunica `idle`, `preparing`, `processing`, `waiting`, `executing`,
`completed`, `warning` ou `failed`. Processing e executing significam somente
que uma operação pública foi iniciada. Não indicam consciência, hardware ou
etapas privadas.

## Processamento, espera, execução, confirmação e falha

- **Processing:** trabalho público em andamento.
- **Waiting:** dependência externa ou confirmação ainda não satisfeita.
- **Execution:** ação observável, com etapa ou executor somente se fornecidos.
- **Confirmation:** evento explícito; nunca inferido pelo IDS.
- **Failure:** resultado público de falha, acompanhado por texto.

## Confiança, provenance, agentes e decisões

Confiança só aparece quando valor, faixa ou texto são fornecidos. O IDS não
calcula nem completa precisão. Provenance apresenta origem, data, autor,
referência, versão e confiabilidade fornecida, sem validar a fonte.

Um agente é sempre descrito como componente de software. A Decision Timeline
ordena eventos públicos cronologicamente e expande apenas detalhes fornecidos.
Ela não apresenta justificativas privadas nem conteúdo de raciocínio interno.

## Restrições contra antropomorfização

Componentes não atribuem emoção, desejo, intenção própria, consciência,
personalidade ou certeza não fornecida. Animações comunicam transição
observável; não representam vida ou presença.

## Acessibilidade, motion e progressive disclosure

- nomes e estados textuais acessíveis;
- leitura linear, ordem cronológica e controles nativos para expansão;
- seleção e ações por teclado, foco visível e alvos baseados em tokens;
- texto quebrável a 200% de zoom e em painéis estreitos;
- significado independente de cor, ícone, posição ou animação;
- suporte a `prefers-reduced-motion` e `forced-colors`.

Somente preparação, processamento e execução podem animar. A preferência
reduzida do sistema e o eixo Reduced desativam a animação. Mission Card, Context
Card e Decision Timeline mostram resumo antes dos detalhes. A ausência de
detalhes não bloqueia a renderização.
