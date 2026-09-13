# Game Profiles do Host Bridge

Os perfis desta pasta descrevem como localizar uma janela de jogo no Windows. Eles não contêm a lógica de percepção nem a estratégia do agente.

Campos atuais:

- `id`: identificador estável do perfil;
- `display_name`: nome exibido no Bridge;
- `title_contains`: fragmentos aceitos no título da janela;
- `process_names`: nomes de processo aceitos, com ou sem `.exe`.

O usuário ainda confirma manualmente a janela encontrada. Isso evita que o Bridge envie captura ou futuramente input para uma aplicação errada.
