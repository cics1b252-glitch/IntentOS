# Product Alpha 2.1.1 — Relatório técnico

Versão: `0.4.1-alpha`  
Escopo: correção Unicode da bridge Windows e recuperação da conversa.

## Causa raiz confirmada

`product_bridge.py` serializava a resposta com `ensure_ascii=False` e, na antiga linha 185, usava `print()` no `stdout`. No executável PyInstaller em Windows, esse stream herdou CP1252. Uma resposta financeira contendo `📊` (U+1F4CA) não era representável nessa code page; o `UnicodeEncodeError` ocorreu durante o próprio envio do JSON e encerrou a bridge. A UI aguardava a resposta sem um bloco de finalização e manteve `busy=true`.

## Correção

- stdin, stdout e stderr Python são reconfigurados explicitamente como UTF-8 com `errors="replace"`.
- stdout tornou-se canal exclusivo de JSON Lines válido, sem logs ou decoração.
- a escrita do protocolo possui fallback JSON ASCII (`ensure_ascii=True`) se o stream hospedeiro estiver incorreto.
- diagnósticos técnicos redigidos vão somente para stderr e log, sem conteúdo integral, prompts ou segredos.
- o host .NET define UTF-8 nas três pontas do processo e drena stderr sem bloquear o pipe.
- JSON de sessão, PKB, preferências e logs tocados pelo produto usam UTF-8 explícito.
- timeout, EOF, processo encerrado e JSON inválido geram erro estruturado e reinício limpo da bridge na próxima tentativa.
- a UI finaliza o loading em `finally`, reativa o compositor e oferece **Tentar novamente** e **Copiar diagnóstico**.

## Validação automatizada

- reprodução específica de U+1F4CA sob stdout CP1252;
- português e acentos (`ç`, `ã`, `é`, `ô`);
- `R$`, `€`, `£`, japonês e árabe;
- Markdown em resposta Gemini;
- JSON, persistência e logs UTF-8;
- caminho com espaços e acentos;
- política stdout/stderr;
- encerramento inesperado e timeout da bridge;
- recuperação real da máquina de estado da UI;
- smoke test do executável PyInstaller incluído no build.

Resultado focado antes do empacotamento: `44 passed`.  
Suíte Python integral: `595 passed`, `2 failed` por restrições ambientais já conhecidas e alheias a Unicode: descoberta de programas vazia no sandbox e bloqueio de escrita no legado `%USERPROFILE%\.intent-os`.  
Suíte JavaScript: `40 passed` (`38` existentes + `2` de recuperação).  
Compilação host/instalador: aprovada; permanece o aviso não bloqueante histórico de referência `WindowsBase` do WebView2.

Cobertura Python global observada: `80%` (`6.647` statements; `1.074` não cobertos). A bridge ficou em `61%`; os caminhos críticos Unicode e de persistência desta correção estão cobertos.

## Estado da antiga falha CP1252

Corrigida e transformada em teste obrigatório. `test_kernel_no_external_imports` também lê fontes explicitamente em UTF-8 e não é mais classificado como limitação histórica.

## Preservação na atualização

O instalador substitui somente `%LOCALAPPDATA%\Programs\IntentOS`. Dados, chaves protegidas por DPAPI, histórico e preferências permanecem em `%LOCALAPPDATA%\IntentOS\Data`. Atalhos e registro de desinstalação são recriados para a versão nova.

## Limites honestos

- O fluxo real Gemini precisa ser validado pelo usuário com sua chave já protegida na máquina instalada; nenhuma chave foi extraída ou incluída no build.
- A instalação e a atualização não foram executadas automaticamente neste computador.
- Os dois testes ambientais citados acima não representam regressão desta correção.
