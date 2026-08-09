# Roteiro manual — Product Alpha 2.1.4

## Preparação

1. Instale a atualização sobre a versão anterior.
2. Confirme que configurações, credencial protegida e histórico continuam disponíveis.
3. Abra **Diagnóstico** e copie o diagnóstico inicial.

## Primeira intenção

1. Envie `Quero investir 23500`.
2. Confirme que uma Mission é criada e o sistema pergunta se o valor é único ou mensal.
3. Responda `É um investimento único`.
4. Confirme que nenhum valor anterior substituiu R$ 23.500.

Repita com `23.500`, `R$ 23.500` e `vinte e três mil e quinhentos reais`.

## Datas e continuidade

1. Confirme que nenhuma conversa mostra `Invalid Date`.
2. Feche e reabra o aplicativo.
3. Confirme que histórico e Mission foram restaurados com datas válidas.
4. Verifique em Diagnóstico o estado da migração e o último estágio concluído.

## Provider

1. Selecione Gemini e teste a conexão.
2. Envie uma intenção que exija geração do Provider.
3. Confirme que o diagnóstico registra início e conclusão da chamada Gemini.
4. Em resposta local do Atlas, confirme que a UI informa que Gemini não foi chamado.

## Falha e repetição

1. Desconecte temporariamente a rede durante uma solicitação ao Provider.
2. Confirme que o carregamento termina e um erro compreensível aparece.
3. Clique em **Tentar novamente** após restaurar a rede.
4. Confirme que a mesma Mission foi retomada, sem duplicação.

## Aprovação

Registre versão, resultado de cada etapa e diagnóstico. Provider real e instalação limpa são
validações manuais e não devem ser declarados aprovados sem evidência.
