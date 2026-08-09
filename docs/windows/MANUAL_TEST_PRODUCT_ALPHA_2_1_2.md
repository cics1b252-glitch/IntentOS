# Teste manual — Product Alpha 2.1.2

## Instalação e atualização

1. Feche o Intent OS.
2. Execute `IntentOS-Product-Alpha-2.1.2-Setup.exe` sobre a versão 0.4.1.
3. Abra pelo atalho e confirme `0.4.2-alpha` em **Sobre**.
4. Confirme que Provider, chave protegida, preferências e histórico permanecem disponíveis.
5. Para instalação limpa, use outra conta Windows ou máquina de teste sem `%LOCALAPPDATA%\Programs\IntentOS`.

## Bridge e recuperação

1. Abra o Intent OS e confirme **Núcleo: pronto**.
2. Envie uma intenção simples e confirme a resposta.
3. No Gerenciador de Tarefas, encerre `IntentOS.Bridge.exe`.
4. Envie outra intenção.
5. Confirme que o loading termina e a mensagem informa que o núcleo foi reiniciado.
6. Clique **Tentar novamente** e confirme a nova resposta.
7. Repita a queda e confirme que não existe loop de reinicialização.
8. Teste **Copiar diagnóstico** e **Abrir diagnóstico**; confirme que nenhuma chave, prompt ou resposta integral aparece.
9. Feche e reabra o aplicativo e confirme a restauração do histórico.

## Resultado esperado

A conversa só aceita envio com a bridge em `ready`; quedas nunca exibem exceção bruta, nunca deixam loading infinito e permitem recuperação controlada.

