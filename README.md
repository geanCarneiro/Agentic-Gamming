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
