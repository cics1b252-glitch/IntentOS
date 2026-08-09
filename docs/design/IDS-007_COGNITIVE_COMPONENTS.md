# IDS-007 — Cognitive Components

Status: catálogo canônico de componentes cognitivos de apresentação.

## Catálogo e contratos

| Elemento | Dados de apresentação | Estados ou tipos |
|---|---|---|
| `ids-cognitive-pulse` | state, label, detail, updatedAt | idle a failed |
| `ids-mission-card` | title, objective, status, progress, metadata, actions | draft a cancelled |
| `ids-context-card` | type, source, availability, relevance, sensitive | seis contextos |
| `ids-capability-badge` | name, category, description, origin, state | available a failed |
| `ids-decision-timeline` | label e eventos públicos | onze eventos |
| `ids-confidence-indicator` | mode, valor/faixa/texto, source, method | quatro modos |
| `ids-execution-indicator` | state, etapa, duração e executor fornecidos | queued a cancelled |
| `ids-provenance-card` | type, source, referência e disponibilidade | sete origens |
| `ids-agent-status` | software component, state, capability | available a failed |
| `ids-knowledge-relationship-card` | source, relationship, target | oito relações |

Os normalizadores em `ui/ids/cognitive/contracts.js` aceitam e retornam objetos
simples serializáveis. Campos inválidos recebem fallback seguro. Ausência de
confiança, relevância ou sensibilidade continua ausência: nada é inferido.
Elementos recebem dados pela propriedade `data` ou pelo atributo `data-json`;
JSON inválido produz um contrato vazio seguro.

```js
document.querySelector("ids-mission-card").data = {
  title: "Review public evidence",
  objective: "Validate the presentation",
  status: "running",
  progress: 60,
};
```

## Estados e composição

Sucesso, aviso, erro, informação, espera, desabilitado, restrito e indisponível
usam significado compartilhado. Texto e símbolo preservam significado sem cor.

- Mission Card compõe Cognitive Pulse e Capability Badge.
- Execution Indicator complementa a missão sem alterar seu estado.
- Timeline combina com Provenance Card e Agent Status.
- Context Card combina com Knowledge Relationship Card.

Contratos alimentam renderers; elementos registram renderers. Não há
dependências circulares.

## Interação e acessibilidade

Mission Card aceita foco; Enter ou Espaço emite `ids-select`, enquanto controles
internos mantêm comportamento nativo. Ações emitem `ids-action`. Disclosures e
timeline usam controles nativos. Listeners são instalados ao conectar e removidos
ao desconectar.

Todos os estados têm texto e nomes acessíveis. O CSS usa tokens IDS, permite
quebra de texto, adapta-se a viewport estreito e não cria largura fixa. Reduced
Motion interrompe animações; Forced Colors preserva bordas.

## Restrições arquiteturais e integração futura

O pacote não importa Kernel, Mission Engine, Constitution, PKB, Providers, Core
Apps ou domínio. Não executa capabilities, persiste dados, chama serviços,
calcula confiança ou cria relações. Adaptadores futuros poderão traduzir
contratos públicos da aplicação fora do IDS.

## Registro Studio 1B

- origem: `feat/ids-foundation`;
- hash-base: `2278a9fd063763931052e3e591390e71f2ab34b8`;
- árvore inicial: limpa;
- divergência inicial de `origin/feat/openai-integration`: 12 commits à frente;
- cenários previstos: Light/Neutral/Comfortable/Full,
  Dark/Atlas/Compact/Reduced, Dark/Lavender, Light/Cream, viewport estreito,
  zoom 200% e console;
- Forced Colors: regra automatizada e inspeção manual quando suportada.

Validação real no navegador confirmou as quatro combinações de tema exigidas,
31 instâncias cognitivas compostas, troca determinística dos eixos, expansão de
detalhes e ausência de rolagem horizontal no viewport disponível. A sessão de
navegador não expôs emulação de Forced Colors, viewport ou zoom; por isso esses
três cenários permanecem cobertos por regras responsivas automatizadas, mas sem
alegação de validação manual nesta missão. Nenhuma falha de carregamento ou erro
visível ocorreu durante a inspeção.

Resultados numéricos finais ficam no relatório da missão, evitando transformar
esta especificação estável em log mutável.
