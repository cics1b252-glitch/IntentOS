# Sprint 0 — Baseline executável e de testes

- **Data:** 2026-07-29
- **Branch:** `feat/openai-integration`
- **Objetivo:** registrar o comportamento atual antes de consolidações
  arquiteturais
- **Política:** nenhuma falha existente foi corrigida e nenhuma resposta do
  sistema foi alterada para satisfazer testes

## 1. Ambiente utilizado

| Item | Valor |
|---|---|
| Sistema operacional | Windows 10 `10.0.19045`, AMD64 |
| Python | CPython 3.13.14 |
| pytest | 9.1.1 |
| pytest-asyncio | 1.4.0 |
| pytest-cov | 7.1.0 |
| FastAPI | 0.141.0 |
| HTTPX | 0.28.1 |
| Instalação | ambiente virtual local, pacote editável |

O projeto declara suporte a Python `>=3.11`. Nesta máquina somente Python 3.13
estava disponível. O CI usa Python 3.11 para validar o limite mínimo declarado.

## 2. Artefato arquitetural ausente

A missão referencia `docs/ArchitectureReview.md`, mas o arquivo não está presente
na branch remota `origin/feat/openai-integration` nem na cópia clonada. A ausência
não bloqueia a execução dos testes, porém impede relacionar esta baseline, linha a
linha, às conclusões dessa revisão.

## 3. Instalação reproduzível

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,server]"
```

As dependências necessárias já estavam quase integralmente declaradas no extra
`dev`. Foi acrescentado somente `pytest-cov`, necessário para identificar módulos
e linhas sem cobertura. O extra `server` é necessário para coletar e executar os
testes FastAPI.

Não existe lockfile de dependências. Portanto, a instalação é reproduzível quanto
ao procedimento, mas não fixa versões transitivas exatas.

## 4. Comandos de validação

```powershell
.\.venv\Scripts\python.exe -m compileall -q intent_kernel intent_os_desktop

.\.venv\Scripts\python.exe -m pytest -ra --tb=short `
  --junitxml=.artifacts\pytest-report.xml `
  --cov=intent_kernel `
  --cov=intent_os_desktop `
  --cov-report=term-missing `
  --cov-report=json:.artifacts\coverage.json
```

## 5. Resultado da suíte original

Executado antes da criação dos testes de caracterização:

| Métrica | Resultado |
|---|---:|
| Coletados | 441 |
| Aprovados | 438 |
| Falhos | 3 |
| Ignorados | 0 |
| Erros de coleta | 0 |
| Avisos | 3 |
| `compileall` | aprovado |

## 6. Resultado com a baseline de caracterização

| Métrica | Resultado |
|---|---:|
| Coletados | 452 |
| Aprovados | 449 |
| Falhos | 3 |
| Ignorados | 0 |
| Erros de coleta | 0 |
| Avisos | 3 |
| Novos testes de caracterização | 11 aprovados |
| Cobertura total | 75% |
| `compileall` | aprovado |

Os três testes falhos são os mesmos da suíte original. Os testes adicionados não
criaram regressões.

## 7. Falhas conhecidas preservadas

### 7.1 Leitura de fontes depende da codificação padrão do Windows

```text
tests/test_kernel_independence.py::test_kernel_no_external_imports
UnicodeDecodeError ao usar Path.read_text() sem encoding explícito
```

O teste tenta ler fonte UTF-8 usando a página de código `cp1252`. Não foi alterado
nesta missão.

### 7.2 Detecção de programas depende do ambiente hospedeiro

```text
tests/test_symbiotic.py::test_programs_detected
installed_programs == []
```

O teste pressupõe que a inspeção do sistema sempre retorna pelo menos um programa.
No ambiente utilizado a lista retornou vazia. O comportamento foi preservado.

### 7.3 Sincronização escreve no diretório pessoal real

```text
tests/test_symbiotic.py::test_sync_with_kernel
PermissionError em ~/.intent-os/pkb/events/
```

O teste instancia `Kernel()` sem injetar armazenamento temporário. Isso acopla o
teste ao diretório pessoal e às permissões da máquina. Não foi corrigido porque a
missão proíbe alteração comportamental e refatoração.

## 8. Avisos conhecidos

Três testes produzem:

```text
RuntimeWarning: coroutine 'KnowledgeManager.count' was never awaited
```

Origem observada:

```text
intent_kernel/monitor/__init__.py:76
```

Testes afetados:

- `tests/test_desktop.py::test_dashboard`;
- `tests/test_monitor.py::test_snapshot_structure`;
- `tests/test_monitor.py::test_user_summary`.

## 9. Caracterização adicionada

O arquivo `tests/test_sprint_0_characterization.py` fixa contratos atuais de:

- `Kernel.process`;
- `IntentEngine`;
- caminhos do `PipelineDAG`;
- roteamento atual do `ProviderManager`;
- template financeiro do `MockProvider`;
- Constitution ativa (`1.0.0`, quatro pilares);
- ingestão do `KnowledgeManager`;
- limiares do curator v1;
- persistência e índice do `JsonFileStore`;
- fluxo `/status` e `/quit` da CLI;
- contrato atual de status da FastAPI.

Esses testes documentam inclusive decisões imperfeitas, como:

- todos os modos serem roteados ao primeiro provider;
- o modo curto ser determinado por heurística de tamanho;
- o `MockProvider` retornar Markdown e uso de tokens igual a zero;
- a Constitution ativa ainda possuir exatamente quatro pilares.

## 10. Cobertura e módulos sem cobertura

Cobertura combinada: **75%**.

Módulos com **0%**:

- `intent_kernel/pkb/curator_v2.py`;
- `intent_kernel/pkb/store.py`;
- `intent_kernel/providers/openai_provider.py`.

Áreas com cobertura especialmente baixa:

- CLI (`intent_kernel/__main__.py`): 36%;
- Event Bus: 46%;
- Desktop: 48%;
- Guardian de simbiose: 52%;
- camada Symbiotic: 58%;
- Cognitive Map: 60%;
- Evolution v2: 64%;
- servidor FastAPI: 66%;
- Continuity: 66%;
- Evolution v3: 67%;
- persistence store: 70%.

O fato de um módulo ter 0% não significa que deva ser removido ou unificado. Essa
decisão pertence a uma etapa arquitetural posterior.

## 11. Dependências e configurações ausentes

- `docs/ArchitectureReview.md` ausente;
- nenhum lockfile;
- nenhuma política de versão Python além de `>=3.11`;
- CI inexistente antes desta missão;
- cobertura não configurada antes desta missão;
- testes Symbiotic dependem do computador real;
- testes e armazenamento ainda podem usar o diretório pessoal;
- não há marca registrada para testes que exigem integração ou ambiente Windows;
- não há fixture global que isole o diretório da PKB;
- não há execução confirmada nesta máquina com Python 3.11.

## 12. CI

Foi criado `.github/workflows/sprint-0-baseline.yml`, restrito a:

1. checkout;
2. Python 3.11;
3. instalação `.[dev,server]`;
4. `compileall`;
5. pytest com relatório resumido;
6. cobertura;
7. publicação de JUnit e cobertura como artefatos, inclusive após falha.

O workflow preserva as falhas: ele não usa `continue-on-error` e não mascara o
código de saída do pytest.

## 13. Riscos para migrações futuras

1. Corrigir codificação pode mudar testes que hoje dependem implicitamente do
   Windows.
2. Isolar o diretório pessoal pode revelar dependências ocultas de estado local.
3. Consolidar os dois Curators sem caracterizar o v2 pode mudar classificação e
   persistência.
4. Alterar Constitution ou Guardians pode invalidar contratos observados.
5. Substituir o `MockProvider` por OpenAI pode mudar texto, tokens, confiança e
   eventos.
6. Unificar stores pode modificar serialização, datas, índice e lifecycle.
7. Mudar a heurística do `IntentEngine` pode alterar domínio e modo em cascata.
8. Refatorar o Pipeline pode alterar ordem, eventos e metadados mesmo mantendo o
   texto final.

## 14. Limitações desta baseline

- mede comportamento automatizado, não adequação do produto;
- não valida provider real;
- não valida instalação Windows;
- não testa rede externa;
- não mede desempenho;
- não corrige as três falhas existentes;
- não cobre integralmente módulos legados;
- o CI ainda precisa ser executado no GitHub após eventual push.

## 15. Próxima etapa recomendada

Executar primeiro o CI desta branch e anexar o resultado a esta baseline. Depois,
em uma missão separada, corrigir exclusivamente a infraestrutura dos três testes
falhos e dos avisos assíncronos, sem iniciar consolidação arquitetural.

Somente após uma suíte verde e isolada deve começar a comparação entre
implementações duplicadas de Curator, Constitution, providers e persistence.

