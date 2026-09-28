# Compilação visual do Game Pack — Beta 4

O Core expõe `POST /api/game-packs/{pack_id}/vision/compile`. A rota encaminha a compilação ao provedor de visão do Game Pack; o Core não conhece algoritmos de diff, entidades ou câmeras.

Para compilar o FNAF 1 com o Core em execução:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/game-packs/fnaf1/vision/compile
```

O resultado aponta para a pasta criada no volume `data` do projeto. Por padrão, os arquivos ficam em `data/diagnostics/gamepack-compile/fnaf1/<compile-id>/`. O `index.html` reúne visualmente as variações; cada variação tem sua própria pasta com:

- `positive.png` e `negative.png`: cópias dos inputs originais;
- `difference.png`: diff RGBA, com alpha nos pixels ativos;
- `difference-mask.png`: máscara binária usada para formar os componentes;
- `positive-with-bbox.png`: positivo com a bbox detectada desenhada;
- `metadata.json`: assets de origem, bbox, cor, dimensão e caminhos dos artefatos.

A compilação também atualiza `data/diagnostics/gamepack-compile/fnaf1/active-bboxes.json`. O runtime lê esse manifesto e usa a bbox por candidato, par positivo/negativo e entidade. Para candidatos em coordenadas `world`, a bbox permanece relativa ao asset de referência e é transformada pelo registro de pan; em coordenadas `screen`, ela é relativa ao frame positivo. A compilação salva também os pares sem componentes válidos para que seja possível inspecionar os inputs e o diff; esses pares não recebem bbox ativa.

As cores são configuradas em `game-packs/fnaf1/vision/pipeline.json`, no objeto `bbox_colors`, por identidade e no formato hexadecimal `#RRGGBB`. A cor acompanha a entidade na anotação do protocolo Beta 4 e é usada pelo overlay do Host Bridge. Ela não participa do cálculo da detecção.

`GAME_PACK_COMPILE_DIR` pode redirecionar a pasta de saída. Configure a mesma variável no Core antes de iniciar o processo, para que a compilação e o runtime usem o mesmo manifesto ativo. A rota cria uma nova pasta com identificador próprio e não altera os assets nem o `pipeline.json`.

Esta compilação produz uma bbox a partir da diferença configurada e aplica essa bbox nas avaliações seguintes. A validação com capturas live, incluindo alinhamento, pan, ruído e precisão de cada cor/caixa, ainda é necessária antes de tratar o resultado como calibrado.
