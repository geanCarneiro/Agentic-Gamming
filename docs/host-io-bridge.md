# Host I/O Bridge

O jogo live roda no Windows host. O core roda em Docker.

A ponte Windows deverá ser uma aplicação C#/.NET executada na sessão interativa do usuário. Ela não conterá conhecimento de jogo nem lógica de decisão.

## Responsabilidades

- selecionar explicitamente a janela autorizada;
- capturar frames da janela;
- capturar áudio do sistema por loopback;
- enviar `InputFrame` e `AudioChunk` ao core;
- receber `MotorProgram` validado;
- executar teclado/mouse;
- retornar resultado de execução e falhas;
- interromper o envio se a janela-alvo perder validade.

## Não responsabilidades

- detectar entidades do jogo;
- montar world state;
- escolher ações;
- chamar a LLM;
- acessar memória do processo;
- realizar técnicas de evasão de anti-cheat.

O transporte inicial deverá ser um WebSocket autenticado apenas em `localhost`. Frames de preview devem ser enviados em baixa frequência; o fluxo de percepção e o fluxo de visualização não precisam ter a mesma taxa.

## Primeira implementação

A solução C# do Bridge fica dentro do repositório, mas é executada diretamente no Windows host:

```text
D:\work\AgenticGamming\host-bridge\AgenticGaming.HostBridge.sln
```

Esta primeira fatia implementa o handshake WebSocket, captura inicial da área de trabalho inteira, redução para um preview limitado, envio de PNG em base64, armazenamento somente do último preview, log JSONL local e um overlay WinForms básico click-through com metadados da captura. O core mantém o último frame em `data/bridge/latest.png`, também disponível em `GET /api/bridge/latest-frame`.

No Beta 2, quando uma janela é selecionada, a captura usa `PrintWindow` para evitar recapturar o overlay. A captura da área de trabalho inteira via `--screen` é apenas diagnóstica e pode ser indisponível em sessões sem um desktop interativo.

O dashboard mínimo em `http://localhost:8000` acompanha esse transporte pelos
endpoints `GET /api/bridge/status` e `GET /api/bridge/events?limit=30`. A imagem
do último frame é servida inline para que o navegador a exiba diretamente. O
dashboard informa telemetria do Bridge, mas não deve ser tratado como a camada
de percepção ou decisão do agente.

Por padrão, o overlay não é ocultado quando a captura está vinculada a uma janela específica. `--safe-capture` ou `BRIDGE_SAFE_CAPTURE=true` ativa a ocultação defensiva; `--screen` também ativa esse modo automaticamente.

O modo `dry-run` é padrão. A captura por janela, o overlay e a execução real de programas motores serão incrementados sobre os mesmos contratos.

## Beta 3.1 — primeira fatia de áudio

O primeiro corte do Beta 3 implementa somente a entrada operacional de áudio:

- captura por processo como modo padrão (`process_loopback`), incluindo a árvore
  de processos do PID da janela selecionada;
- `system_loopback` como modo explícito alternativo, com seleção de endpoint de
  renderização por `BRIDGE_AUDIO_DEVICE_ID`;
- chunks PCM nominais de `40 ms`;
- protocolo corrente de desenvolvimento identificado como `beta-3`;
- transporte WebSocket autenticado;
- validação de formato, tamanho, sequência e base64 no Core;
- persistência somente do último chunk em `latest-audio.pcm`;
- metadados do último chunk em `latest-audio.json`;
- telemetria em `/api/bridge/status` e `/api/bridge/events`.

Esta fatia não interpreta semanticamente o PCM. A Beta 3.2 adiciona apenas a
medição determinística descrita abaixo; classificação, VLM, `AudioEvent`,
decisão, replay integral e input físico continuam fora do escopo.

## Beta 3.2 — análise acústica e latência

O Core mantém um buffer circular curto do áudio estéreo e calcula, por chunk:

- RMS, pico e dBFS geral;
- RMS e pico por canal;
- baseline relativo ao histórico recente;
- loudness relativo e percentil;
- candidato acústico anônimo quando há energia acima do baseline.

O candidato não identifica a fonte do som e não é um evento semântico. Ele
serve como janela operacional para uma futura análise multimodal e pode ser
consultado em `GET /api/bridge/latest-audio-analysis`.

Cada chunk também recebe um trace de latência com as etapas de decodificação,
medição, histórico/buffer e geração do candidato. O status do Bridge expõe o
tempo de observação até a decisão dry-run, p50, p95, p99, máximo, orçamento e
quantidade de deadlines perdidos.

Os defaults são 5 segundos de buffer, 3 segundos de aquecimento do baseline e
200 ms de orçamento de decisão. Eles podem ser ajustados por `AUDIO_ANALYSIS_*`
ou sobrescritos pelo Game Pack em `audio.analysis`.

### Validação manual do loopback

O teste manual é necessário porque o Docker/Core consegue testar o protocolo com
PCM sintético, mas não substitui a confirmação de que o Windows e o driver de
áudio estão entregando dados reais.

1. Inicie o Core com `docker compose up --build`.
2. Abra o FNAF em uma sessão Windows interativa e deixe-o em uma tela que possa
   emitir áudio. Não é necessário que o Bridge envie input ao jogo.
3. Inicie o Bridge normalmente. Ele selecionará a janela e utilizará o PID para
   ativar o process loopback.
4. Confirme no log local `data/logs/host-bridge.jsonl` o evento
   `audio.capture_initialized`, com `mode=process_loopback`, PID, sample rate,
   canais e `chunk_duration_ms=40`.
5. Confirme que `audio.chunk_sent` aparece com sequência crescente.
6. Consulte `GET /api/bridge/status` e verifique `audio_status=RECEIVING`, a
   contagem de chunks e o PID do processo.
7. Verifique que `data/bridge/latest-audio.pcm` e
   `data/bridge/latest-audio.json` foram atualizados.
8. Para validar o isolamento, reproduza áudio de outra aplicação enquanto o
   FNAF estiver silencioso. Esse áudio não deve ser a fonte do process loopback.
9. Repita com `BRIDGE_AUDIO_MODE=system_loopback` e um endpoint explicitamente
   selecionado para validar o modo alternativo.

Esse teste comprova captura, fragmentação, transporte e armazenamento do último
chunk. Ele não comprova que o áudio foi entendido pelo agente nem que qualquer
ação será tomada.
