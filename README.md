# Agentic Gaming

Núcleo inicial de uma aplicação genérica para agentes que jogam usando percepção audiovisual e entrada de teclado/mouse.

## Estado atual

Esta primeira implementação cobre a fundação da Alpha:

- contratos Pydantic para visão, áudio, world state, decisões e programas motores;
- Game Pack externo carregado a partir de JSON;
- barramento em memória e adaptador NATS;
- consolidação temporal de visão e áudio;
- gateway determinístico para testar o pipeline sem LLM;
- executor em `dry-run`;
- replay JSON Lines;
- API FastAPI;
- UI mínima para iniciar execução, injetar visão/áudio e observar o estado.
- logs estruturados JSONL em `data/logs/core.jsonl`, também disponíveis pela API.

O Game Pack FNAF 1 ainda é um contrato inicial. Ele não contém os detectores reais, calibração de tela ou a estratégia completa do jogo.

## Executar com Docker

```text
docker compose up --build
```

Abra `http://localhost:8000`.

Os logs da aplicação ficam em `data/logs/core.jsonl`. O endpoint de uma execução é `GET /api/runs/{run_id}/logs`.

## Host Bridge local

O adaptador C# que captura a área de trabalho do Windows fica dentro do repositório, mas não roda no container. Abra a solução abaixo no Visual Studio:

```text
D:\work\AgenticGamming\host-bridge\AgenticGaming.HostBridge.sln
```

Com o core em execução, o Bridge pode ser iniciado pela raiz do projeto:

```powershell
& 'C:\Program Files\dotnet\dotnet.exe' run --project .\host-bridge\src\AgenticGaming.HostBridge
```

O modo padrão é `dry-run`. O último frame recebido pelo core pode ser visualizado em `http://localhost:8000/api/bridge/latest-frame`, e os logs do Bridge ficam em `data/logs/host-bridge.jsonl`.

O dashboard em `http://localhost:8000` possui a seção Beta 2 `Visão ao vivo do agente`, que mostra a conexão do Bridge, o Game Profile, a janela/PID, o modo de captura, métricas do último frame e eventos recentes. A página também mantém o laboratório Alpha para simulações controladas.

### Beta 3.1 — captura de áudio

A primeira fatia do Beta 3 captura o áudio do jogo, mas ainda não faz detecção,
classificação, decisão ou reação. O modo padrão é `process_loopback`, associado
ao PID da janela selecionada, e o chunk nominal de transporte é fixo em `40 ms`.
O último chunk recebido fica em `data/bridge/latest-audio.pcm`, com metadados em
`data/bridge/latest-audio.json`.

Para listar os endpoints de saída ativos do Windows:

```powershell
& 'C:\Program Files\dotnet\dotnet.exe' run --project .\host-bridge\src\AgenticGaming.HostBridge -- --list-audio-devices
```

Para iniciar a captura do processo selecionado:

```powershell
$env:BRIDGE_AUDIO_MODE = 'process_loopback'
$env:BRIDGE_AUDIO_ENABLED = 'true'
$env:BRIDGE_DRY_RUN = 'true'
& 'C:\Program Files\dotnet\dotnet.exe' run --project .\host-bridge\src\AgenticGaming.HostBridge
```

O FNAF deve estar aberto antes do Bridge para que a janela selecionada forneça
o PID correto. O Bridge não controla o jogo durante este teste.

Para usar o fallback de captura do mix de um dispositivo específico:

```powershell
$env:BRIDGE_AUDIO_MODE = 'system_loopback'
$env:BRIDGE_AUDIO_DEVICE_ID = '<device-id-listado-no-comando-anterior>'
& 'C:\Program Files\dotnet\dotnet.exe' run --project .\host-bridge\src\AgenticGaming.HostBridge
```

O status fica disponível em `GET /api/bridge/status`; o último áudio pode ser
consultado em `GET /api/bridge/latest-audio` e seus metadados em
`GET /api/bridge/latest-audio/metadata`. Esta fase não grava uma sessão inteira
e não persiste um replay audiovisual.

### Beta 3.2 — análise acústica e latência

A segunda fatia mantém o PCM original e acrescenta análise determinística no
Core, sem VLM, classificação semântica ou input físico:

- buffer circular limitado aos últimos 5 segundos por padrão;
- medição de RMS, pico, dBFS e energia por canal;
- baseline aquecido após 3 segundos por padrão;
- loudness relativo e percentil no histórico recente;
- candidatos acústicos anônimos, sem afirmar a fonte do som;
- rastreamento de latência por chunk, com p50, p95, p99 e deadlines;
- orçamento padrão de decisão dry-run de 200 ms;
- último resultado em `GET /api/bridge/latest-audio-analysis`.

Os defaults podem ser ajustados por variáveis `AUDIO_ANALYSIS_*`. Um Game Pack
pode sobrescrever esses valores em `audio.analysis` no manifesto. O candidato
acústico é uma ocorrência operacional para uma futura interpretação multimodal;
ele ainda não é um `AudioEvent` semântico.

O padrão atual usa o barramento em memória para permitir iniciar o core mesmo sem depender do NATS. Para exercitar o adaptador NATS:

```text
EVENT_BUS_BACKEND=nats docker compose up --build
```

## Executar testes locais

```text
python -m pip install -e ".[dev]"
python -m pytest
```

## Próximos incrementos

1. substituir a UI de exemplo por upload de imagem/vídeo/áudio;
2. implementar replay audiovisual sincronizado;
3. adicionar detector visual configurável pelo Game Pack;
4. adicionar classificador auditivo e estimativa relativa de loudness;
5. implementar o protocolo da ponte Windows;
6. adicionar gateway de modelo local com seleção GPU/CPU;
7. evoluir o Game Pack FNAF 1 com calibração e programas motores reais.
