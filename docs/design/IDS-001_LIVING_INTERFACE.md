# IDS-001 — Living Interface

## 1. Intenção

A Living Interface responde ao contexto sem parecer outro produto. Ela
amadurece como uma presença conhecida: muda ritmo, densidade e ênfase, mas
mantém linguagem, estrutura e personalidade reconhecíveis.

Adaptação visual não é personalização irrestrita. É uma variação limitada,
explicável e reversível da apresentação.

## 2. Identidade permanente e atmosfera dinâmica

| Identidade permanente | Atmosfera dinâmica |
|---|---|
| voz e tom | densidade de informação |
| hierarquia tipográfica | temperatura do fundo |
| famílias de espaçamento e raio | ênfase de um painel |
| comportamento de foco e confirmação | ritmo de transição |
| semântica das cores | quantidade de detalhe visível |
| posição dos controles essenciais | componente contextual em destaque |
| princípios de acessibilidade | nível cognitivo apresentado |

A atmosfera nunca pode:

- mudar a semântica de um controle;
- deslocar silenciosamente uma ação crítica;
- esconder confirmação, risco ou estado;
- substituir preferência explícita do usuário;
- transformar um espaço em uma identidade visual incompatível;
- usar cor ou movimento como única forma de comunicar informação.

## 3. Orquestração contextual

A apresentação pode considerar somente sinais legítimos e observáveis:

- tarefa ou missão ativa;
- espaço cognitivo escolhido;
- etapa do fluxo;
- volume e tipo de conteúdo;
- preferência explícita de densidade, contraste, tema e movimento;
- necessidade de acessibilidade declarada pelo usuário.

Esses sinais produzem ajustes delimitados por tokens e regras. A adaptação deve
ser determinística o suficiente para ser explicada: “o espaço está mais denso
porque você abriu o nível Técnico”, e não “porque o sistema acha que você está
ansioso”.

É proibido inferir humor, diagnóstico, capacidade cognitiva, saúde, emoção ou
personalidade a partir do uso da interface.

## 4. Silent UI

Silent UI é a disciplina de remover competição visual entre interface e
conteúdo.

- uma ação principal por momento;
- controles secundários permanecem disponíveis, mas discretos;
- movimento confirma mudança, não entretém;
- bordas e sombras organizam, não decoram;
- status técnico é traduzido para linguagem humana;
- detalhes internos aparecem somente quando solicitados;
- estados vazios orientam uma próxima ação concreta;
- notificações interrompem apenas diante de prazo, risco ou bloqueio real.

## 5. Attention Principle

> **A interface deve conduzir a atenção do usuário, nunca disputá-la.**

Ordem padrão de atenção:

1. missão, documento ou decisão atual;
2. próxima ação segura;
3. contexto necessário;
4. estado e evidência;
5. controles auxiliares;
6. detalhes técnicos sob demanda.

Não devem coexistir múltiplos elementos com máxima ênfase. Cor intensa,
movimento, tamanho e contraste não podem competir pelo mesmo primeiro plano.

## 6. Cognitive Pulse

O Cognitive Pulse comunica atividade observável do sistema sem personificá-lo.
Ele é um indicador de processo, nunca de consciência ou emoção.

| Estado | Significado observável | Apresentação |
|---|---|---|
| disponível | nenhuma operação em andamento | presença estática e discreta |
| preparando | validando contexto e requisitos | transição curta |
| processando | execução local ou de Provider em andamento | pulso regular |
| pesquisando | consulta autorizada a fontes | pulso com rótulo textual |
| coordenando | múltiplos executores autorizados | sequência moderada |
| concluindo | consolidando e auditando resultado | desaceleração |
| aguardando | falta confirmação ou informação | estado estático com pergunta |
| bloqueado | política, risco ou erro impediu avanço | ícone, texto e ação segura |

Regras:

- sempre oferecer um rótulo textual equivalente;
- respeitar movimento reduzido, substituindo animação por mudança estática;
- não representar raciocínio interno, cadeia de pensamento ou “sentimentos”;
- não prometer duração exata sem evidência;
- não usar o pulso para esconder espera indefinida;
- tornar cancelamento ou pausa visíveis quando tecnicamente possíveis.

## 7. Continuidade visual

Atualizações devem preservar localização das ações essenciais, vocabulário,
ordem lógica, atalhos, semântica de cor e reconhecimento dos espaços
cognitivos.

Mudanças graduais podem aprimorar contraste, proporção e ritmo. Mudanças
estruturais exigem migração assistida e uma explicação curta ao usuário.

## 8. Acessibilidade e segurança

- navegação integral por teclado;
- foco visível e previsível;
- ordem de leitura coerente;
- nomes acessíveis para ícones;
- zoom e redimensionamento sem perda de ação;
- linguagem clara, sem jargão interno;
- confirmação explícita antes de efeito externo relevante;
- opção de repetir, simplificar ou ler em voz alta;
- nenhum estado comunicado apenas por cor, som ou movimento.

## 9. Critérios de aceitação

Uma implementação está aderente quando continua reconhecível em todos os
espaços, explica por que mudou, funciona sem animação, preserva significado em
alto contraste e escala ampliada, não revela módulos internos sem solicitação,
não infere estado psicológico e permite reverter escolhas de apresentação.

