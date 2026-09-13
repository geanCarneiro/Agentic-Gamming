# Agentic Gaming Host Bridge

Aplicação C#/.NET executada diretamente no Windows host. O jogo permanece fora do Docker; o core Python continua dentro do Docker.

## Abrir no Visual Studio

Abra a solução:

```text
D:\work\AgenticGamming\host-bridge\AgenticGaming.HostBridge.sln
```

No Visual Studio, também é possível usar `File > Open > Project/Solution` e selecionar esse arquivo `.sln`.

## Executar

O core precisa estar em execução:

```powershell
docker compose up --build
```

Com o core em execução, abra `http://localhost:8000` para usar o Control Room.
A seção Beta 2 mostra o estado do Bridge, o perfil e a janela selecionados, o
último frame recebido e os eventos de conexão/captura. O restante da página
continua sendo o laboratório Alpha de simulação.

Em outro PowerShell, na raiz do projeto:

```powershell
& 'C:\Program Files\dotnet\dotnet.exe' run --project .\host-bridge\src\AgenticGaming.HostBridge
```

O Bridge usa estas configurações:

| Variável | Padrão | Finalidade |
| --- | --- | --- |
| `AGENTIC_CORE_WS` | `ws://localhost:8000/ws/host-bridge` | endpoint WebSocket do core |
| `HOST_BRIDGE_TOKEN` | `dev-only-change-me` | token local de autenticação |
| `BRIDGE_CAPTURE_INTERVAL_MS` | `500` | intervalo entre frames |
| `BRIDGE_MAX_CAPTURE_WIDTH` | `1280` | largura máxima do frame enviado |
| `BRIDGE_MAX_CAPTURE_HEIGHT` | `720` | altura máxima do frame enviado |
| `BRIDGE_PROFILES_DIR` | `host-bridge/profiles` | perfis externos para localizar jogos |
| `BRIDGE_SELECTION_PATH` | `data/bridge/selection.json` | última seleção persistida |
| `BRIDGE_SAFE_CAPTURE` | `false` | oculta o overlay durante a captura |
| `BRIDGE_DRY_RUN` | `true` | impede ações físicas por padrão |
| `BRIDGE_LOG_PATH` | `data/logs/host-bridge.jsonl` | log estruturado do Bridge |
| `BRIDGE_PREVIEW_PATH` | `data/bridge/preview.png` | último frame capturado |

O projeto já inclui um perfil de execução para o Visual Studio. Com o core em execução, selecione `AgenticGaming.HostBridge` como projeto de inicialização e pressione `F5`.

Na inicialização, o Bridge lista os Game Profiles e as janelas visíveis do Windows. Pressione `Enter` para aceitar a primeira opção ou informe o número da janela do jogo. A seleção fica registrada em `data/bridge/selection.json` e a captura passa a acompanhar a janela selecionada. Para executar somente o modo de captura da área de trabalho durante diagnósticos, use `--screen`; esse modo ativa automaticamente a captura segura. Em uma janela selecionada, o overlay permanece visível por padrão. Se ele aparecer no frame, use `--safe-capture` ou `BRIDGE_SAFE_CAPTURE=true`.

Para permitir futuramente a execução física de teclado/mouse, a sessão deverá ser iniciada explicitamente com `--live-input`. Essa opção ainda não executa programas motores nesta primeira fatia; ela apenas registra a intenção no handshake.

## Escopo desta primeira fatia

- conexão WebSocket autenticada em localhost;
- handshake versionado;
- seleção explícita de Game Profile e janela do Windows;
- captura da janela selecionada;
- captura da área de trabalho inteira somente com `--screen`;
- overlay nativo click-through com metadados do frame;
- envio de frames PNG em base64;
- gravação do último preview;
- logs JSONL locais;
- modo `dry-run` por padrão.

A seleção da janela e o overlay textual básico agora fazem parte do Beta 2. A captura de áudio, as anotações semânticas e a execução real de programas motores serão adicionadas sobre este protocolo, sem misturar a lógica de decisão do agente ao Bridge.
