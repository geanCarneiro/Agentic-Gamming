# Beta 4 — itens adiados

Este documento registra decisões de escopo tomadas durante a evolução do Beta 4.
O conteúdo é um backlog arquitetural, não uma instrução para executar todas as
mudanças imediatamente.

## Decisões atuais do Beta 4

- O Bridge continua genérico: captura a imagem inteira, transporta o frame e não
  conhece entidades ou regras do jogo.
- O Core continua sendo o host de execução: recebe o frame do Bridge e chama o
  entrypoint de observação do Game Pack. A compilação é iniciada por uma rota
  genérica do Core e delegada ao compilador opcional do pack.
- A implementação da visão pertence ao Game Pack. O Core conhece apenas o
  envelope do frame e o contrato `VisionState`; não conhece OpenCV, ROIs,
  assets, template matching, YOLO ou VLM.
- O Game Pack FNAF 1 usa exclusivamente assinaturas de diferença positiva /
  negativa limitadas por ROI.
- O FNAF separa `screen ROI` de `world ROI`. A primeira usa coordenadas fixas
  no frame live; a segunda faz registro exclusivamente horizontal da viewport
  antes de comparar positivo e negativo.
- Para o FNAF 1, YOLO, template matching e matching alinhado ficam desativados.
- `VisionEntity` permanece o contrato comum de saída, com bbox, confiança,
  evidências, origem e identificador do detector.
- O fluxo continua push de frame inteiro com descarte de frames antigos. Um
  protocolo pull ou captura seletiva ainda não faz parte deste incremento.

## Próximos itens, após validar o detector por diferença

### Preparar, sem implementar ainda

- consolidar versionamento e health-check da interface explícita de percepção
  do Game Pack;
- separar formalmente Fast Path determinístico e AI Path opcional;
- criar um plano de atenção/scheduling por cena, mantendo inicialmente o
  transporte de frames inteiros;
- representar observações/eventos de percepção separadamente do estado
  consolidado quando houver necessidade real;
- preparar os contratos de reação rápida e estratégia deliberativa;
- preparar prioridade, TTL e cancelamento de ações para o futuro Action Arbiter;
- formalizar uma Host API entre Game Pack e Bridge sem expor Win32 ao pack;
- avaliar `CaptureBatch` somente se a telemetria demonstrar que transportar o
  frame inteiro é o gargalo.

### Deixar para uma fase posterior

- Game Packs compilados em DLL C# com `AssemblyLoadContext`;
- contrato binário compartilhado em uma nova assembly .NET;
- migração do Runtime/Core Python para .NET;
- worker Python separado para modelos e IPC por memória compartilhada;
- remoção ou substituição do Docker;
- captura pull completa, `GetPixel` e captura seletiva controlada pelo pack;
- Action Arbiter em produção e separação completa entre loops reflexo e
  deliberativo;
- editor visual de Game Packs;
- generalização multiplataforma do Bridge;
- reintrodução de YOLO, VLM ou outro detector neural no FNAF 1.

## Critério para retomar os itens adiados

Nenhuma migração de runtime ou transporte deve ser iniciada apenas por hipótese.
Antes, a telemetria deve demonstrar que o gargalo está fora do operador de
diferença, das ROIs, do agendamento ou da fila de frames. A estabilização dos
contratos e do formato dos Game Packs também deve preceder um editor visual ou
plugins compilados.
