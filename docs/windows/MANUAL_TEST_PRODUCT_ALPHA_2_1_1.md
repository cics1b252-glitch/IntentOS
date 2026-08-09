# Roteiro manual — Product Alpha 2.1.1

## Atualização

1. Feche o Intent OS.
2. Execute `IntentOS-Product-Alpha-2.1.1-Setup.exe`.
3. Confirme a atualização.
4. Abra pelo atalho existente.
5. Em **Sobre**, confirme `0.4.1-alpha`.

## Continuidade e Unicode

1. Confirme que o Google Gemini continua conectado; não recadastre a chave se o estado estiver conectado.
2. Envie: `Analise R$ 5.000 em FIIs em São Paulo: ç, ã, é, ô.`
3. Envie: `Mostre um resumo com 📊, € 10, £ 8, 日本語 e العربية.`
4. Confirme que a resposta aparece, inclusive Markdown, sem janela de exceção.
5. Feche e reabra o Intent OS.
6. Confirme que as duas mensagens e respostas foram restauradas.

## Recuperação de falha

1. Durante um teste, desconecte temporariamente a internet e envie uma mensagem.
2. Aguarde a resposta de erro/timeout.
3. Confirme que “Processando sua solicitação...” desaparece.
4. Confirme que o campo e o botão **Enviar** voltam a funcionar.
5. Use **Copiar diagnóstico** e confirme que nenhuma chave aparece.
6. Reconecte a internet e escolha **Tentar novamente**.

## Resultado esperado

O aplicativo não encerra a bridge por caracteres Unicode, nunca mantém loading infinito e preserva configuração, chave DPAPI, histórico, preferências e atalhos.

