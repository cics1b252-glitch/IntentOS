# Teste manual — Product Alpha 2.1.3

1. Confirme o SHA-256 do instalador usando `CHECKSUMS.txt`.
2. Execute `IntentOS-Product-Alpha-2.1.3-Setup.exe` sobre a versão anterior.
3. Confirme que preferências, chaves protegidas e histórico continuam disponíveis.
4. Abra e confirme que “Preparando seu espaço…” aparece imediatamente.
5. Durante a abertura, pressione X; confirme encerramento sem tela branca ou processo órfão.
6. Em uma falha simulada, use **Tentar novamente**.
7. Teste **Modo seguro**; confirme demonstração sem restauração de histórico ou Provider.
8. Teste **Abrir diagnóstico** e verifique os eventos com timestamp.
9. Envie texto com acentos e emoji usando Gemini; confirme resposta e persistência.
10. Feche, reabra e confirme a continuidade da missão.

Se WebView2 falhar, teste **Limpar cache**. Caso o runtime não esteja instalado, instale o
Microsoft Edge WebView2 Runtime e tente novamente. Registre qualquer falha antes de repetir.
