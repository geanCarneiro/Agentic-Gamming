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
| `BRIDGE_AUDIO_ENABLED` | `true` | habilita a captura PCM do Beta 3 |
| `BRIDGE_AUDIO_MODE` | `process_loopback` | captura pelo PID selecionado ou pelo mix do dispositivo |
| `BRIDGE_AUDIO_DEVICE_ID` | vazio | endpoint de renderização usado no `system_loopback` |
| `BRIDGE_AUDIO_CHUNK_MS` | `40` | duração nominal dos chunks PCM |
| `BRIDGE_AUDIO_BUFFER_MS` | `100` | buffer interno solicitado ao WASAPI |
| `BRIDGE_AUDIO_LATEST_PATH` | `data/bridge/host-latest-audio.pcm` | último chunk PCM local do Bridge |
| `BRIDGE_RUN_ID` | vazio | identificação opcional da execução live |

O projeto já inclui um perfil de execução para o Visual Studio. Com o core em execução, selecione `AgenticGaming.HostBridge` como projeto de inicialização e pressione `F5`.

Na inicialização, o Bridge lista os Game Profiles e as janelas visíveis do Windows. Pressione `Enter` para aceitar a primeira opção ou informe o número da janela do jogo. A seleção fica registrada em `data/bridge/selection.json` e a captura passa a acompanhar a janela selecionada. Para executar somente o modo de captura da área de trabalho durante diagnósticos, use `--screen`; esse modo ativa automaticamente a captura segura. Em uma janela selecionada, o overlay permanece visível por padrão. Se ele aparecer no frame, use `--safe-capture` ou `BRIDGE_SAFE_CAPTURE=true`.

Para listar os dispositivos de saída disponíveis:

```powershell
& 'C:\Program Files\dotnet\dotnet.exe' run --project .\host-bridge\src\AgenticGaming.HostBridge -- --list-audio-devices
```

O modo padrão do Beta 3 é `process_loopback`: o FNAF precisa estar aberto para
que a janela selecionada forneça o PID do jogo. Para testar o mix de um
endpoint específico, use `BRIDGE_AUDIO_MODE=system_loopback` e informe
`BRIDGE_AUDIO_DEVICE_ID`.

Esta fatia ainda não detecta eventos, chama VLM/LLM ou executa programas
motores. O modo `dry-run` permanece padrão.

## Escopo desta primeira fatia

- conexão WebSocket autenticada em localhost;
- handshake versionado;
- seleção explícita de Game Profile e janela do Windows;
- captura da janela selecionada;
- captura da área de trabalho inteira somente com `--screen`;
- overlay nativo click-through com metadados do frame;
- envio de frames PNG em base64;
- gravação do último preview;
- captura de áudio PCM por process loopback ou system loopback;
- envio de chunks de áudio nominais de 40 ms;
- gravação somente do último chunk de áudio;
- logs JSONL locais;
- modo `dry-run` por padrão.

A seleção da janela e o overlay textual básico fazem parte do Beta 2. A captura
de áudio operacional é a primeira fatia do Beta 3. As anotações semânticas, a
detecção auditiva e a execução real de programas motores continuam fora do
Bridge e serão adicionadas em etapas posteriores.
