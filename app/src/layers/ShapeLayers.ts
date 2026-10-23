/**
 * Cell shapes drawn from one decoded shape tile, coloured exactly like the cell dots: every vertex carries its
 * cell's colour-by value, second value, category and filter bytes (gathered from the per-cell arrays already in
 * memory), and the shared colour rule turns them into a colour or a drop.
 *
 * The four bytes travel packed in two attributes (packedCellAttributes): deck's PathLayer leaves only three of
 * WebGL's sixteen attribute slots free.
 *
 *   ShapeEdgeLayer  PathLayer with closed rings (the first vertex repeated); `shade` darkens the colour, so the
 *                   edges of filled shapes outline each cell in a deeper tone of its own colour
 *   ShapeFillLayer  SolidPolygonLayer over triangles computed in the worker, never tessellated on the main thread
 */
import { PathLayer, SolidPolygonLayer } from "@deck.gl/layers";
import { CellColorTextures, cellColorDefaultProps, cellColorModule, packedCellAttributes, packedCellDefaultProps, type CellColorProps } from "./colorModule";

const shapeEdgeModule = {
  name: "shapeEdge",
  vs: /* glsl */ `
uniform shapeEdgeUniforms {
  float shade;
} shapeEdge;
`,
  uniformTypes: { shade: "f32" },
} as const;

export interface ShapeEdgeProps extends CellColorProps {
  shade: number; // 1 = the cell's colour, lower = darker
}

export class ShapeEdgeLayer extends PathLayer<unknown, ShapeEdgeProps> {
  static layerName = "ShapeEdgeLayer";
  static defaultProps = { ...(PathLayer as any).defaultProps, ...cellColorDefaultProps, ...packedCellDefaultProps, shade: 1 } as any;

  declare state: PathLayer["state"] & { colors: CellColorTextures };

  getShaders() {
    const shaders = super.getShaders();
    return {
      ...shaders,
      modules: [...shaders.modules, cellColorModule, shapeEdgeModule],
      inject: {
        ...(shaders as any).inject,
        "vs:#decl": /* glsl */ `
in vec4 instanceCellBytes;
in float instanceCellCategory;
`,
        "vs:#main-end": /* glsl */ `
{
  bool drop;
  vec4 sc = sscape_cellColor(instanceCellBytes.x, instanceCellBytes.y, instanceCellCategory, instanceCellBytes.z, drop);
  vColor = vec4(sc.rgb * shapeEdge.shade, layer.opacity);
  if (drop) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
}
`,
      },
    };
  }

  initializeState() {
    super.initializeState();
    this.getAttributeManager()!.addInstanced(packedCellAttributes("instance") as any);
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
    this.state.colors.apply(model, this.props);
    model.shaderInputs.setProps({ shapeEdge: { shade: this.props.shade ?? 1 } });
    super.draw(params);
  }
}

export class ShapeFillLayer extends SolidPolygonLayer<unknown, CellColorProps> {
  static layerName = "ShapeFillLayer";
  static defaultProps = { ...(SolidPolygonLayer as any).defaultProps, ...cellColorDefaultProps, ...packedCellDefaultProps } as any;

  declare state: SolidPolygonLayer["state"] & { colors: CellColorTextures };

  getShaders(type: "top" | "side") {
    const shaders = super.getShaders(type);
    if (type !== "top") return shaders;
    return {
      ...shaders,
      modules: [...shaders.modules, cellColorModule],
      inject: {
        ...(shaders as any).inject,
        "vs:#decl": /* glsl */ `
in vec4 vertexCellBytes;
in float vertexCellCategory;
`,
        "vs:#main-end": /* glsl */ `
{
  bool drop;
  vec4 sc = sscape_cellColor(vertexCellBytes.x, vertexCellBytes.y, vertexCellCategory, vertexCellBytes.z, drop);
  vColor = vec4(sc.rgb, layer.opacity);
  if (drop) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
}
`,
      },
    };
  }

  initializeState() {
    super.initializeState();
    this.getAttributeManager()!.add(packedCellAttributes("vertex", "dynamic") as any);
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
    const top = (this.state as any).topModel;
    if (top) this.state.colors.apply(top, this.props);
    super.draw(params);
  }
}
