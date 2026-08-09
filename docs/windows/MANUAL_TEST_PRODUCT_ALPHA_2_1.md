# Manual Test — Product Alpha 2.1

1. Instale sobre a versão anterior e confirme que preferências e histórico foram preservados.
2. Abra Configurações > Providers de IA.
3. Conecte uma chave oficial do Google Gemini e execute **Testar**.
4. Confirme o estado **conectado** e selecione Gemini como Provider padrão.
5. Envie: `Explique qual é sua função.`
6. Confirme uma resposta real e a identificação **Google Gemini** no histórico.
7. Feche e reabra o aplicativo; confirme a mesma Mission e o histórico.
8. Teste uma chave inválida e confirme erro compreensível.
9. Se possuir OpenAI e Gemini conectados, mantenha fallback desligado e force uma falha.
10. Ative explicitamente o fallback, repita e confirme qual Provider respondeu.
11. Confirme que nenhuma chave aparece em diagnóstico ou logs.
12. Desinstale preservando dados, reinstale e confirme a restauração.

Não envie chaves, logs sensíveis ou capturas contendo credenciais.
