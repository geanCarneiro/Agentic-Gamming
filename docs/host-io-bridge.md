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
