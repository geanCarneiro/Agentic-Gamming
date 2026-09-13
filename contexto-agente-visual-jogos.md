# Contexto do projeto: agente de IA para jogos visuais

**Versão do snapshot:** 0.1  
**Data:** 13 de setembro de 2026  
**Status:** base conceitual para o primeiro protótipo

## 1. Objetivo

Desenvolver um agente de IA capaz de jogar usando apenas informações sensoriais equivalentes às disponíveis para uma pessoa: imagem da tela, áudio e comandos de teclado/mouse. O sistema não deve depender de leitura da memória do processo, APIs internas, variáveis ocultas do jogo ou acesso direto ao estado verdadeiro da partida.

O projeto não busca apenas maximizar desempenho. Um dos seus eixos é o **ajuste humano**: impor latência, incerteza perceptiva, atenção limitada e compromisso motor para que o agente não tenha reflexos ou monitoramento sobre-humanos apenas por ser software.

## 2. Princípios já definidos

1. **Conhecimento pode ser perfeito; estado atual precisa ser percebido.** O agente pode conhecer profundamente as mecânicas públicas de um jogo, mas só pode saber o que está acontecendo na partida atual por visão, áudio e memória das próprias observações.
2. **Percepção, decisão e execução são subsistemas distintos.** Eles operam em frequências diferentes e se comunicam por estados estruturados.
3. **A LLM não é a IA inteira.** Ela funciona como cérebro deliberativo, apoiada por classificadores locais, memória temporal e um executor determinístico.
4. **Ações podem ser comprometidas.** O agente pode enviar uma sequência pré-definida com delays. Depois de iniciada, ela pode não ser totalmente cancelável, reproduzindo antecipação e erro humano.
5. **Conhecimento não implica acompanhamento perfeito.** Mesmo conhecendo fórmulas, intervalos e probabilidades, o agente deve ter limitações para contar muitos relógios e eventos simultaneamente.
6. **O protótipo inicial será feito em ambiente single-player/offline.** FNAF 1 é o candidato inicial.
7. **O estudo de anti-cheat será limitado à compatibilidade e observabilidade em ambientes autorizados.** Não faz parte do escopo criar ocultação ou técnicas para burlar detecção.

## 3. Arquitetura conceitual

```text
JOGO
 ├─ imagem ─> percepção visual ─┐
 └─ áudio  ─> percepção sonora ├─> world state + memória ─> agente deliberativo
                               │                              │
                               └──────────────────────────────┘
                                                              v
                                                   intenção/ação de alto nível
                                                              v
                                              controlador motor determinístico
                                                              v
                                              teclado/mouse + delays + reflexos
                                                              v
                                                             JOGO
```

### 3.1 Percepção visual

Uma aplicação própria observa continuamente a tela, detecta elementos relevantes, calcula suas posições e mantém uma representação estruturada e atualizada. A saída não deve ser uma descrição textual longa a cada ciclo; deve usar IDs estáveis, campos compactos e preferencialmente deltas.

Exemplo provisório:

```text
VISION_STATE ts=184293.450 scene=office
power=63 usage=2 camera_panel=CLOSED
left_door=CLOSED right_door=OPEN
changed=[power,left_door]
```

A visão pode operar a 20, 30 ou 60 Hz, sem obrigar a LLM a raciocinar nessa mesma frequência. Eventos curtos ou mudanças relevantes devem permanecer registrados até serem consumidos.

### 3.2 Percepção auditiva

O subsistema auditivo deve ser separado da LLM e provavelmente será um modelo local determinístico ou classificador treinado sobre um conjunto fechado de sons possíveis. Ele processa buffers curtos, identifica eventos e estima atributos como distância e, quando o áudio permitir, direção.

Saída esperada:

```text
AUDIO_STATE ts=184293.450
- type=FOOTSTEP confidence=.94 distance=NEAR direction=LEFT age_ms=82
- type=UNKNOWN confidence=.38 age_ms=214
```

Requisitos iniciais:

- possuir uma classe `UNKNOWN` ou mecanismo de rejeição por confiança;
- não inferir distância somente pelo volume;
- treinar/validar sons em diferentes distâncias, com oclusão, reverberação e sons simultâneos;
- registrar eventos breves até que o ciclo deliberativo os consuma;
- representar direção em classes discretas inicialmente, em vez de exigir azimute preciso;
- permitir degradação de confiança em ambientes sonoros congestionados.

### 3.3 World state e memória

O `world state` consolida percepção visual, percepção sonora, ações em execução e memória. Deve distinguir claramente:

- fato observado agora;
- última observação conhecida;
- inferência sobre o estado atual;
- conhecimento estático da mecânica;
- estado real usado apenas para avaliação, se disponível no laboratório.

Exemplo:

```text
bonnie:
  last_seen_location: CAM_2B
  observed_at_ms: 82400
  observation_confidence: 0.96
  current_state: UNKNOWN
```

A confiança deve degradar com o tempo de maneira configurável. Uma observação antiga não desaparece imediatamente, mas também não permanece sendo tratada como verdade atual.

### 3.4 Agente deliberativo

Recebe snapshots compactos do estado, deltas recentes, memória relevante, conhecimento técnico e informação sobre ações já comprometidas. A cadência inicial considerada é aproximadamente um ciclo a cada 500 ms, mas esse valor é uma hipótese a medir, não uma constante definida.

O agente deve produzir saída estruturada, por exemplo:

```json
{
  "intent": "check_camera",
  "target": "CAM_1C",
  "urgency": "high",
  "confidence": 0.81,
  "reason_code": "FOXY_CHECK_OVERDUE",
  "motor_program": "OPEN_PANEL_SELECT_1C"
}
```

Evitar gerar scripts arbitrários de entrada em toda inferência. O ideal é selecionar programas motores conhecidos e parametrizados, o que reduz tokens, latência e ações inválidas.

### 3.5 Controlador motor e reflexos

Transforma intenção em eventos de teclado/mouse. Suporta sequências temporizadas pré-definidas, como pressionar, manter, aguardar e soltar. Uma sequência pode continuar enquanto uma nova percepção já está sendo produzida.

O chamado **reflexo** é uma ação antecipatória ou programa motor escolhido sem contexto futuro completo. Ele pode estar errado e ter uma janela limitada de cancelamento. Essa característica é parte deliberada do ajuste humano, não apenas uma restrição técnica.

Cada programa motor deve declarar:

- precondições conhecidas;
- duração estimada;
- pontos canceláveis e não canceláveis;
- ação compensatória possível;
- efeito esperado;
- timeout e estado seguro após falha.

## 4. Modelo de ajuste humano

O ajuste humano não será apenas um `sleep` fixo. Deve combinar:

- **latência sensorial:** demora entre evento físico e percepção disponível;
- **latência decisória:** varia com complexidade, ambiguidade e carga de atenção;
- **latência motora:** demora entre decisão e primeiro comando;
- **jitter:** variação probabilística dentro de limites configuráveis;
- **incerteza:** falsos negativos, confusão entre classes e estimativas imprecisas;
- **atenção limitada:** alguns eventos podem perder prioridade ou ser esquecidos;
- **compromisso de ação:** uma sequência já iniciada pode não ser interrompida a tempo;
- **temporização cognitiva imperfeita:** o sistema interno mede precisamente, mas o agente recebe representações aproximadas quando apropriado.

Temporizadores devem ter níveis distintos:

- `CLOCK_EXACT`: somente infraestrutura, métricas e sincronização;
- `AGENT_TIMER`: valor arredondado ou aproximado disponível ao agente;
- `ATTENTION_TIMER`: contagem que pode sofrer desvio ou ser esquecida;
- `EVENT_MEMORY`: categorias como “recente”, “há algum tempo” e “atrasado”.

Uma parametrização futura pode criar perfis como casual, experiente, expert humano e sobre-humano.

## 5. Três escalas temporais

1. **Percepção/reflexo local (dezenas de milissegundos):** captura, classificação e execução de programas já autorizados.
2. **Reação (centenas de milissegundos):** consolidação do estado e decisão operacional.
3. **Planejamento (segundos):** estratégia, mudança de política e análise de risco.

Essas escalas não devem bloquear umas às outras. Visão e áudio continuam atualizando o estado enquanto o agente pensa ou enquanto o executor completa uma ação.

## 6. Primeiro benchmark: FNAF 1

FNAF 1 foi escolhido como candidato inicial por ser single-player, ter poucos elementos visuais relevantes, movimento de câmera limitado, ações discretas e forte dependência de memória e temporização. Isso permite escalar a complexidade sem começar por navegação 3D, mira ou controle contínuo.

### 6.1 Capacidades do protótipo mínimo

- reconhecer escritório, painel de câmeras, câmera selecionada, portas, luzes e energia;
- reconhecer estados/posições visíveis dos animatrônicos;
- registrar quando e onde cada animatrônico foi visto;
- detectar eventos sonoros úteis e armazená-los temporalmente;
- executar ações discretas por teclado/mouse;
- decidir quando consultar câmeras e quando operar portas/luzes;
- sobreviver e registrar uma partida completa;
- explicar decisões por códigos curtos e rastreáveis.

### 6.2 Conhecimento técnico permitido

O agente pode receber uma base técnica equivalente à de um jogador que estudou profundamente o jogo, incluindo:

- turnos/oportunidades de movimento dos animatrônicos;
- padrões e probabilidades de movimentação;
- funcionamento dos níveis de IA;
- relação entre câmeras e comportamento;
- custo de energia de ações;
- impacto dos ataques do Foxy na energia;
- estratégias conhecidas e seus riscos.

Entretanto, a base não pode entregar o estado oculto atual. Exemplo: é permitido informar a regra geral de movimento do Foxy; não é permitido fornecer `foxy_next_move_check_in=1.372s` se esse dado só puder ser obtido por relógio interno ou memória do jogo.

### 6.3 Separação epistemológica obrigatória

Para cada informação, registrar sua origem:

| Categoria | Exemplo | Pode orientar decisão? |
|---|---|---|
| Observação atual | “A porta esquerda aparece fechada” | Sim |
| Memória observada | “Bonnie foi visto na CAM_2B há cerca de 6 s” | Sim, com incerteza |
| Conhecimento técnico | “Bonnie segue determinadas regras de movimento” | Sim |
| Inferência | “Bonnie provavelmente se aproximou” | Sim, marcada como inferência |
| Estado oculto do jogo | posição lida da memória do processo | Não |
| Ground truth de avaliação | posição real usada depois para medir erro | Somente métricas, nunca decisão |

## 7. Latência e instrumentação

Medida fundamental:

```text
T_total = T_capture + T_vision + T_state + T_model + T_executor + T_humanization
```

Registrar em todos os ciclos:

- timestamp do frame/áudio original;
- início e fim de cada etapa de percepção;
- versão do world state fornecida ao agente;
- início e fim da inferência;
- tokens de entrada e saída, quando disponíveis;
- intenção decidida e confiança;
- programa motor selecionado;
- comandos planejados e efetivamente executados;
- cancelamentos, atrasos e falhas;
- observação posterior usada para verificar o resultado;
- estado que o agente acreditava existir versus ground truth de avaliação, quando disponível.

O objetivo é provar se a limitação dominante é realmente o tempo de reação configurado. Caso a inferência ocasionalmente dure 800 ms, por exemplo, isso deve aparecer como atraso do sistema, e não ser confundido com comportamento humano intencional.

## 8. Contexto eficiente para o modelo

Diretrizes iniciais:

- usar um schema estável e compacto;
- transmitir deltas e um snapshot resumido, não uma narrativa integral da tela;
- usar IDs persistentes para entidades;
- limitar casas decimais à precisão útil;
- colocar eventos em filas com `age`, confiança e consumo explícito;
- recuperar conhecimento técnico relevante por situação, evitando enviar a enciclopédia inteira a cada ciclo;
- separar prompt estático, estado dinâmico, memória e catálogo de ações;
- exigir resposta validável por schema;
- permitir fallback determinístico para resposta inválida ou timeout;
- medir custo de tokenização e serialização, além da inferência.

Uma possível divisão do contexto:

```text
SYSTEM_RULES       regras invariantes e limites
GAME_KNOWLEDGE     trechos recuperados conforme a situação
CURRENT_STATE      snapshot compacto
RECENT_DELTAS      mudanças desde a última decisão
EVENT_QUEUE        eventos ainda não consumidos
ACTIVE_ACTION      programa motor e ponto atual
WORKING_MEMORY     observações e hipóteses relevantes
ACTION_CATALOG     ações válidas no estado atual
```

## 9. Anti-cheat e isolamento

FNAF 1 será usado como laboratório sem foco em anti-cheat. Em fases futuras, considera-se isolar o agente e o jogo em VMs distintas, conectadas por uma interface de vídeo/áudio e entrada de teclado/mouse. Essa arquitetura pode ser estudada por segurança, reprodutibilidade e isolamento.

O escopo autorizado é:

- entender quais características de automação um anti-cheat pode observar;
- verificar compatibilidade em jogos, servidores ou ambientes que autorizem bots/testes;
- testar isolamento e interfaces de I/O;
- documentar riscos de bloqueio e requisitos legais/contratuais.

Fica fora do escopo:

- ocultar deliberadamente a automação;
- falsificar sinais para parecer um humano com o objetivo de evitar detecção;
- contornar ou desativar mecanismos de anti-cheat.

## 10. Fases sugeridas

### Fase 0 - Simulador e contratos

Definir schemas, relógio monotônico, event bus, programas motores e um simulador sem o jogo. Reproduzir estados e verificar decisões de forma determinística.

### Fase 1 - Instrumentação passiva no FNAF 1

Capturar tela e áudio, classificar eventos e gerar logs, sem controlar o jogo. Comparar a saída com anotações humanas.

### Fase 2 - Controle assistido

O agente recomenda ações e um humano confirma. Serve para validar raciocínio, catálogo de ações e sincronização.

### Fase 3 - Loop autônomo básico

Executar ações discretas, jogar uma noite inicial e registrar telemetria completa. Inicialmente sem degradações humanas além de limites de segurança.

### Fase 4 - Ajuste humano

Adicionar distribuições de latência, temporizadores cognitivos, incerteza, atenção limitada e compromisso motor. Comparar perfis.

### Fase 5 - Escalonamento

Avançar para noites mais difíceis e depois para outros jogos single-player, aumentando sucessivamente estados, movimento, controle contínuo e complexidade 3D.

## 11. Métricas de sucesso

- taxa de sobrevivência e progresso por noite;
- taxa de detecção, falso positivo e falso negativo por evento;
- erro de distância/direção no áudio;
- acurácia do estado visual;
- latência por etapa e percentis p50/p95/p99;
- tokens e custo por minuto de jogo;
- decisões inválidas ou não executáveis;
- ações canceladas tarde demais;
- diferença entre crença do agente e ground truth;
- quantidade de informação antiga tratada incorretamente como atual;
- desempenho com e sem ajuste humano;
- reprodutibilidade usando gravações e seeds.

## 12. Decisões ainda em aberto

- linguagem e stack do runtime em tempo real;
- modelo visual: regras/template matching, detector treinado ou solução híbrida;
- modelo auditivo e estratégia de criação/rotulagem do dataset;
- provedor/modelo deliberativo e requisitos de execução local;
- formato final do event bus e armazenamento temporal;
- frequência adaptativa ou fixa da deliberação;
- política exata de cancelamento dos programas motores;
- como construir o ground truth do FNAF 1 sem disponibilizá-lo ao agente;
- definição quantitativa dos perfis humanos;
- estratégia de replay determinístico;
- limites de orçamento, hardware e latência.

## 13. Próxima entrega recomendada

Antes de implementar integração completa com o jogo, criar uma especificação executável contendo:

1. schemas de `VisionState`, `AudioEvent`, `WorldState`, `AgentDecision` e `MotorProgram`;
2. diagrama de concorrência e filas;
3. relógios e semântica de timestamps;
4. catálogo mínimo de ações do FNAF 1;
5. formato de log/replay;
6. orçamento de latência por subsistema;
7. critérios de aceite da percepção passiva.

## 14. Instrução de continuidade para o Codex

Use este documento como snapshot conceitual, não como especificação imutável. Preserve os princípios e decisões explícitas, mas trate itens marcados como hipóteses, sugestões ou decisões em aberto como sujeitos a validação. Ao propor implementação:

- declare premissas;
- não misture percepção, conhecimento técnico, inferência e ground truth;
- priorize instrumentação e reprodutibilidade;
- evite otimização prematura antes de medir latência;
- mantenha o primeiro protótipo focado em FNAF 1 single-player;
- não implemente técnicas de evasão de anti-cheat;
- atualize este snapshot quando uma decisão arquitetural relevante mudar.

