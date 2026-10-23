/**
 * ScatterplotLayer subclass with four extra per-instance bytes (colour-by value, second value for blends,
 * category code, filter value), coloured by the shared cell colour rule in colorModule.ts.
 * LOD: rows are pre-shuffled, so drawing the first `drawCount` instances is a uniform subsample.
 */
import { ScatterplotLayer, type ScatterplotLayerProps } from "@deck.gl/layers";
import { CellColorTextures, cellColorAttributes, cellColorDefaultProps, cellColorModule, type CellColorProps } from "./colorModule";

export interface ExpressionScatterProps extends CellColorProps {
  drawCount: number;
}
export type ExpressionScatterLayerProps = ScatterplotLayerProps<unknown> & ExpressionScatterProps;

const defaultProps = {
  ...(ScatterplotLayer as any).defaultProps,
  ...cellColorDefaultProps,
  drawCount: { type: "number", value: Infinity, compare: false },
};

export class ExpressionScatterLayer extends ScatterplotLayer<unknown, ExpressionScatterProps> {
  static layerName = "ExpressionScatterLayer";
  static defaultProps = defaultProps as any;

  declare state: ScatterplotLayer["state"] & { colors: CellColorTextures };

  getShaders() {
    const shaders = super.getShaders();
    return {
      ...shaders,
      modules: [...shaders.modules, cellColorModule],
      inject: {
        ...(shaders as any).inject,
        "vs:#decl": /* glsl */ `
in float instanceValue;
in float instanceValue2;
in float instanceCategory;
in float instanceFilter;
`,
        "vs:#main-end": /* glsl */ `
{
  bool drop;
  vec4 sc = sscape_cellColor(instanceValue, instanceValue2, instanceCategory, instanceFilter, drop);
  vFillColor = vec4(sc.rgb, layer.opacity);
  if (drop) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
}
`,
      },
    };
  }

  initializeState() {
    super.initializeState();
    this.getAttributeManager()!.addInstanced(cellColorAttributes("instance") as any);
    this.setState({ colors: new CellColorTextures() });
  }

  updateState(params: any) {
    super.updateState(params);
    this.state.colors.update(this.context.device, params.props, params.oldProps);
  }

  finalizeState(context: any) {
    this.state.colors?.destroy();
    super.finalizeState(context);
  }

  draw(params: any) {
    const model = (this.state as any).model;
    if (!model) return;
    const p = this.props;
    this.state.colors.apply(model, p);
    const total = this.getNumInstances();
    model.setInstanceCount(Math.max(0, Math.min(total, Math.floor(p.drawCount ?? total))));
    super.draw(params);
  }
}
