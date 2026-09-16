# Agentic Gaming — Especificação Técnica e Acordos do Projeto

Este documento descreve a arquitetura, os limites técnicos e o roadmap executável do Agentic Gaming. Ele é o contexto operacional do repositório para alterações futuras.

## Objetivo do produto

Construir um agente genérico capaz de jogar jogos de computador a partir de percepção audiovisual e entrada de teclado/mouse, mantendo o conhecimento específico de cada jogo fora do núcleo por meio de Game Packs.

O primeiro alvo live é Five Nights at Freddy's 1. A v1.0 deve conseguir operar o jogo em uma janela ou tela cheia no Windows, com comportamento coerente, mesmo que ainda não tenha como requisito vencer todas as partidas.

O projeto começa do zero, com a ideia inicial como único fundamento pré-existente. As decisões devem privilegiar contratos observáveis, replay, telemetria e evolução para outros jogos sem transformar o core em código específico de FNAF 1.

## Arquitetura de execução

O jogo live roda na máquina Windows host. O core de percepção, estado, decisão e telemetria roda dentro do Docker.

```text
Windows host
├── jogo alvo
├── Host Bridge C#/.NET
│   ├── seleção e validação da janela
│   ├── captura de vídeo
│   ├── captura de áudio
│   ├── overlay de depuração
│   └── execução de teclado/mouse
│
└── navegador do usuário
    ├── painel textual do core
    └── eventual painel local de configuração do Bridge

Docker Desktop / WSL2
├── core Python
│   ├── ingestão
│   ├── percepção
│   ├── world state
│   ├── decisão
│   ├── motor lógico
│   └── replay e telemetria
└── NATS opcional
```

O Bridge fica dentro desta pasta do projeto para organização e versionamento, mas não participa do build do Docker nem é executado dentro de container.

## Stack tecnológica

### Core no Docker

- Python 3.13 no container;
- FastAPI e Uvicorn para API HTTP/WebSocket;
- Pydantic 2 para contratos estritos;
- NATS JetStream como barramento opcional;
- barramento em memória para testes e desenvolvimento simples;
- JSON Lines para logs e replay;
- Game Packs externos em JSON;
- Docker Compose para orquestração local;
- Docker Desktop com backend WSL2 no Windows;
- `INFERENCE_DEVICE=auto` como padrão, com suporte planejado a GPU ou CPU.

O core não deve conhecer APIs específicas de captura do Windows. Ele recebe eventos e frames através de contratos.

### Host Bridge

- C#;
- .NET 10;
- `net10.0-windows`;
- aplicação console/worker para o processo principal;
- `ClientWebSocket` para comunicação local com o core;
- APIs Win32 para enumeração e validação de janelas;
- captura preferencial por `Windows.Graphics.Capture`, com suporte a janela por HWND e monitor por HMONITOR;
- fallback GDI/`Graphics.CopyFromScreen` apenas para diagnóstico de desktop e `PrintWindow` para compatibilidade de janelas;
- dependências de WinRT/Windows SDK restauráveis pelo projeto, sem exigir o Windows SDK instalado globalmente;
- captura de áudio prevista com NAudio e loopback do Windows;
- entrada prevista com `SendInput`;
- WinForms usado no overlay textual inicial, com possibilidade de WPF em uma UI futura;
- logs JSONL locais;
- `dry-run=true` por padrão.

O Bridge não decide o que fazer, não interpreta entidades do jogo e não acessa memória do processo do jogo. Ele executa captura, transporte, validação operacional e, após autorização explícita, ações motoras.

### Game Packs

Game Packs são extensões externas e versionadas por jogo. Devem conter, conforme a maturidade do pack:

- identidade e versão;
- ontologia de cenas, entidades e eventos;
- detectores ou referências visuais;
- pipeline auditivo;
- calibração de resolução e regiões de interesse;
- regras de interpretação;
- ações e programas motores;
- conhecimento de mecânicas;
- parâmetros e thresholds revisáveis.

O FNAF 1 é o primeiro pack, mas não deve obrigar o core a possuir nomes ou regras de FNAF hardcoded.

## Contratos principais

Os contratos do core estão em `src/agentic_gaming/contracts.py` e incluem:

- `VisionState` e `VisionEntity`;
- `AudioEvent`;
- `WorldState` e `ObservedFact`;
- `AgentDecision`;
- `MotorProgram` e `MotorStep`;
- `MotorExecution`;
- `EventEnvelope`;
- `CreateRunRequest` e `RunInfo`.

O protocolo inicial do Bridge usa WebSocket autenticado apenas em localhost:

- endpoint do core: `/ws/host-bridge`;
- token: `HOST_BRIDGE_TOKEN`;
- handshake versionado `1.0`;
- mensagens atuais: `hello`, `frame`, `heartbeat`;
- respostas atuais: `hello_ack`, `frame_ack`, `heartbeat_ack`, `error`;
- PNG de preview inicialmente enviado em base64;
- transporte binário e compressão ficam para uma etapa posterior.

Frames de preview não precisam ter a mesma taxa do fluxo de percepção. O primeiro Bridge reduz o frame para no máximo `1280x720` e mantém somente o último artefato no core.

## Configuração operacional do Bridge

A solução C# está em:

```text
host-bridge/AgenticGaming.HostBridge.sln
```

Perfis de localização de jogos ficam em:

```text
host-bridge/profiles/*.json
```

O perfil descreve título e processo candidatos. A seleção final da janela é sempre confirmada pelo usuário durante o Beta 2. A última seleção é salva em `data/bridge/selection.json`.

Variáveis relevantes:

- `AGENTIC_CORE_WS`;
- `HOST_BRIDGE_TOKEN`;
- `BRIDGE_CAPTURE_INTERVAL_MS`;
- `BRIDGE_MAX_CAPTURE_WIDTH`;
- `BRIDGE_MAX_CAPTURE_HEIGHT`;
- `BRIDGE_PROFILES_DIR`;
- `BRIDGE_SELECTION_PATH`;
- `BRIDGE_SAFE_CAPTURE`;
- `BRIDGE_DRY_RUN`;
- `BRIDGE_LOG_PATH`;
- `BRIDGE_PREVIEW_PATH`.

O modo `--screen` existe apenas para diagnóstico, captura o monitor primário
por `Windows.Graphics.Capture` e ativa automaticamente `safe-capture`. O modo
normal exige seleção explícita de janela e mantém o overlay visível;
`--safe-capture` pode ser usado se a captura específica ainda incorporar o
overlay. Suporte a composição de múltiplos monitores permanece evolução futura.

O dashboard do Core fica em `http://localhost:8000`. Durante o Beta 2, a seção
`Visão ao vivo do agente` consulta `/api/bridge/status`, `/api/bridge/events` e
`/api/bridge/latest-frame` para mostrar a conexão, o perfil, a janela, o PID, o
modo de captura, a resolução, a idade do frame e os eventos recentes. Essa
visualização é telemetria operacional; ela ainda não é uma percepção semântica
nem uma explicação de decisão.

## Roadmap de versões

As versões são cumulativas. Cada Beta preserva o comportamento validado anteriormente e acrescenta uma capacidade operacional.

### Alpha — contratos e pipeline simulado

Objetivo: validar o fundamento do sistema sem depender de jogo real, captura do Windows ou modelo neural.

Resultado esperado:

- contratos Pydantic validados;
- Game Pack externo carregado;
- ingestão de visão e áudio simulados;
- world state versionado;
- decisão determinística de teste;
- programas motores em `dry-run`;
- replay JSONL;
- API e painel mínimo;
- logs estruturados.

### Beta 1 — transporte real do Host Bridge

Objetivo: provar a comunicação entre um processo local Windows e o core Docker.

Resultado esperado:

- Bridge compilável em C#/.NET;
- conexão WebSocket autenticada;
- captura inicial da área de trabalho;
- envio de frames ao core;
- último preview visualizável;
- logs locais e no core;
- nenhum input físico.

### Beta 2 — configuração e seleção da janela

Objetivo: deixar de capturar a área de trabalho indiscriminadamente e vincular a sessão a um jogo escolhido.

Resultado esperado:

- catálogo de janelas visíveis do Windows;
- identificação por título, processo, PID e dimensões;
- Game Profiles externos;
- escolha explícita do perfil e da janela;
- persistência da seleção;
- validação contínua de existência, visibilidade e PID;
- captura limitada à janela selecionada;
- overlay nativo básico click-through com metadados do frame, janela, processo, resolução e modo;
- dashboard mínimo com estado do Bridge, último frame inline e eventos recentes;
- interrupção se a janela perder validade;
- nenhum input físico.

### Beta 3 — áudio e sincronização audiovisual

Objetivo: acrescentar áudio live e sincronização temporal.

Resultado esperado:

- captura loopback do Windows;
- seleção de dispositivo;
- buffers PCM e timestamps;
- baseline de ruído;
- loudness relativo à média e ao histórico;
- eventos auditivos com confiança e evidências;
- replay audiovisual sincronizado.

Volume não deve ser convertido deterministicamente em distância. Distância é hipótese inferida a partir de baseline, variação, contexto e evidência acumulada.

### Beta 4 — percepção configurável por Game Pack

Objetivo: identificar elementos visuais e auditivos sem hardcode no core.

Resultado esperado:

- regiões de interesse configuráveis;
- calibração por janela e resolução;
- templates, referências ou detectores especializados;
- entidades com bounding box, estado, confiança e origem;
- anotações disponíveis para o overlay;
- primeiro pipeline especializado para FNAF 1;
- core ainda reutilizável por outros jogos.

### Beta 5 — execução motora controlada

Objetivo: transformar decisões válidas em input real no jogo.

Resultado esperado:

- recebimento de `MotorProgram`;
- validação de precondições e timeout;
- execução de teclado e mouse;
- foco obrigatório na janela selecionada;
- cancelamento e ação de falha;
- logs de cada execução;
- barreira explícita entre `dry-run` e live;
- bloqueio se o alvo mudar ou desaparecer.

### Beta 6 — ciclo fechado live com FNAF 1

Objetivo: fazer o agente observar, decidir e agir no jogo real.

Resultado esperado:

- captura de tela e áudio live;
- percepção de elementos essenciais;
- atualização contínua do world state;
- decisões coerentes;
- execução de ações no FNAF 1;
- reação a consequências observadas;
- parada segura em falhas;
- métricas de latência e comportamento.

O objetivo não é exigir vitória imediata, mas demonstrar bom senso: não clicar aleatoriamente, verificar estados relevantes e reagir a ameaças observadas.

### Beta 7 — robustez e generalização

Objetivo: validar que a plataforma não é apenas um script de FNAF 1.

Resultado esperado:

- múltiplos Game Packs;
- perfis reutilizáveis;
- reconexão e recuperação;
- controle de backpressure;
- transporte binário/comprimido;
- gravação e replay de sessões;
- testes de longa duração;
- comparação live versus replay;
- overlay e painel mais completos;
- segundo jogo ou pack experimental.

### v1.0 — FNAF 1 live utilizável

Objetivo: entregar a primeira versão final operacional.

Resultado esperado:

- seleção do FNAF 1 pelo Bridge;
- captura da janela ou tela cheia;
- áudio integrado;
- percepção dos elementos relevantes;
- overlay de anotações;
- decisões e input reais;
- GPU como padrão e CPU como fallback;
- logs, replay e diagnóstico;
- comportamento coerente em uma sessão real;
- documentação de instalação, execução e recuperação.

## Princípios de implementação

- manter captura, transporte, percepção, decisão e execução em módulos distintos;
- preferir contratos versionados a payloads implícitos;
- manter conhecimento de jogo em Game Packs;
- não acessar memória do jogo nem implementar técnicas de evasão de anti-cheat;
- manter `dry-run` como padrão até uma validação explícita;
- registrar evidência, origem e confiança das observações;
- diferenciar fato observado, inferência e conhecimento técnico;
- permitir replay de entradas reais;
- usar GPU por padrão quando disponível e CPU como fallback configurável;
- evitar dependências distribuídas enquanto o processo local WebSocket for suficiente;
- não transformar o painel web em dependência de operação do agente em produção.
