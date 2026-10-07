# URL parameters

The viewer mirrors its state into the query string with `history.replaceState`, so the address bar is always shareable. Unknown keys are ignored.

| Key | Meaning | Example |
|---|---|---|
| `d` | dataset: registry id, or a bundle URL | `d=amygdala`, `d=https://host/bundle` |
| `s` | focused sample id | `s=vis_Br8325` |
| `c` | color: `g:<gene>`, `f:<field>`, or `b:<scheme>:<genesA>\|<genesB>` | `c=b:yb:GAD1,GAD2\|SLC17A7` |
| `cm` | colormap | `cm=magma` |
| `vr` | value range as fractions of the max | `vr=0.100,0.800` |
| `z` | hide zeros | `z=1` |
| `fl` | filter: `g:<gene>:<lo>,<hi>`, `f:<field>:<lo>,<hi>`, or `c:<field>:<codes>` | `fl=c:domain:2.5` |
| `h` | hidden categories per field | `h=domain:1.3;celltype:0` |
| `gf` | annotation for the expression-by-annotation panel | `gf=domain` |
| `o` | outlines: `<field>:<style>:<width>` | `o=domain:light:1.5` |
| `poly` | `0` disables cell polygons | `poly=0` |
| `img` | image opacity, `0` hides images | `img=0.6` |
| `l` | layout `grid` or `strip` | `l=strip` |
| `p` | visible platforms | `p=visium,xenium` |
| `hs` | hidden samples | `hs=vis_Br2743` |
| `ps` | point size multiplier, spatial view | `ps=1.5` |
| `pse` | point size multiplier, embedding view | `pse=0.5` |
| `sps` | `1`: scale gene colors per sample instead of one shared scale | `sps=1` |
| `debug` | `1`: show timing and frame-rate readouts in the status bar | `debug=1` |
| `sv` | embedding split: `0` off, or `l:<fraction>` / `r:<fraction>` | `sv=r:0.4` |
| `v` | camera: `x,y,zoom` in dataset microns and log2 scale (spatial view) | `v=24609,23505,-6.4` |

Blend scheme codes: `yb` yellow/blue → green, `cm` cyan/magenta → white, `rg` red/green → yellow. Gene lists use commas; a `+` would decode as a space.
