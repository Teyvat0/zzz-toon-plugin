"""Self-built compositor: screen-space rim group and the body / eye two-layer chain."""
import bpy

GROUP = 'ZZZ_ScreenSpaceRim'
RIM_WIDTH, RIM_FADEOUT = 6.0, 1.5   # soft ~3 px inner band
VERSION = '1'


def _math(tree, op, a=None, b=None, clamp=False):
    node = tree.nodes.new('CompositorNodeMath'); node.operation = op; node.use_clamp = clamp
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            node.inputs[i].default_value = v
        else:
            tree.links.new(v, node.inputs[i])
    return node.outputs[0]


def rim_group():
    """Depth-edge mask: displaces depth along the normal's screen direction and compares it."""
    tree = bpy.data.node_groups.get(GROUP)
    if tree is not None and tree.get('zzz_version') == VERSION:
        return tree
    if tree is not None:
        tree.name = GROUP + '.old'
    tree = bpy.data.node_groups.new(GROUP, 'CompositorNodeTree'); tree['zzz_version'] = VERSION
    spec = (('Normal', 'NodeSocketVector', 0, -10000, 10000), ('Width', 'NodeSocketFloat', 1, 0, 10),
            ('Threshold', 'NodeSocketFloat', .01, 0, 1), ('Fadeout', 'NodeSocketFloat', .2, 0, 10),
            ('Brightness', 'NodeSocketFloat', 1, 0, 10), ('Depth', 'NodeSocketFloat', 0, -3.4e38, 3.4e38))
    tree.interface.new_socket(name='Value', in_out='OUTPUT', socket_type='NodeSocketFloat')
    for name, kind, default, low, high in spec:
        item = tree.interface.new_socket(name=name, in_out='INPUT', socket_type=kind)
        item.min_value, item.max_value = low, high
        if kind == 'NodeSocketFloat':
            item.default_value = default
    nodes, links = tree.nodes, tree.links
    gin, gout = nodes.new('NodeGroupInput'), nodes.new('NodeGroupOutput')
    I = gin.outputs
    M = lambda op, a=None, b=None, c=False: _math(tree, op, a, b, c)
    sep = nodes.new('CompositorNodeSeparateXYZ'); links.new(I['Normal'], sep.inputs[0])
    x, y = sep.outputs[0], sep.outputs[1]
    length = M('SQRT', M('MAXIMUM', M('ADD', M('MULTIPLY', x, x), M('MULTIPLY', y, y)), 0.0))
    dx = M('DIVIDE', M('MULTIPLY', M('DIVIDE', x, length), I['Width']), I['Depth'])
    dy = M('DIVIDE', M('MULTIPLY', M('DIVIDE', y, length), I['Width']), I['Depth'])
    vec = nodes.new('CompositorNodeCombineXYZ'); vec.inputs[2].default_value = 0.
    links.new(dx, vec.inputs[0]); links.new(dy, vec.inputs[1])
    disp = nodes.new('CompositorNodeDisplace'); disp.inputs[2].default_value = -1.; disp.inputs[3].default_value = -1.
    links.new(I['Depth'], disp.inputs[0]); links.new(vec.outputs[0], disp.inputs[1])
    dot = nodes.new('CompositorNodeNormal'); dot.outputs[0].default_value = (-1., -1., -1.)
    links.new(disp.outputs[0], dot.inputs[0])
    lit = M('MULTIPLY', dot.outputs[1], 0.57735)
    edge = M('SUBTRACT', lit, M('ADD', I['Threshold'], I['Depth']))
    value = M('DIVIDE', M('MULTIPLY', edge, 10.), I['Fadeout'])
    links.new(M('MULTIPLY', M('MAXIMUM', M('MINIMUM', value, 1.), 0.), I['Brightness']), gout.inputs[0])
    return tree


def chain(scene):
    """Body layer + eye layer: eye over body by (Eye x Hair-free) mask, rim added, Avatar mask selects it."""
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    N, L = tree.nodes, tree.links
    def rl(name):
        node = N.new('CompositorNodeRLayers'); node.scene = scene; node.layer = name
        return node
    body, eye = rl('ViewLayer'), rl('Eye')
    group = N.new('CompositorNodeGroup'); group.node_tree = rim_group(); group.name = 'Group'
    group.inputs['Width'].default_value, group.inputs['Fadeout'].default_value = RIM_WIDTH, RIM_FADEOUT
    group.inputs['Threshold'].default_value, group.inputs['Brightness'].default_value = .01, 1.
    L.new(body.outputs['Normal'], group.inputs['Normal']); L.new(body.outputs['Depth'], group.inputs['Depth'])
    def mix(blend, fac, a, b):
        node = N.new('CompositorNodeMixRGB'); node.blend_type = blend; node.inputs[0].default_value = 1.
        if fac is not None:
            L.new(fac, node.inputs[0])
        L.new(a, node.inputs[1]); L.new(b, node.inputs[2])
        return node.outputs[0]
    rim = mix('MULTIPLY', None, group.outputs[0], body.outputs['Rim'])
    def clip(src):
        low = _math(tree, 'MINIMUM', src, 1.0)
        return _math(tree, 'MAXIMUM', low, 0.0)
    mask = _math(tree, 'MULTIPLY', clip(body.outputs['Hair']), clip(eye.outputs['Eye']), True)
    eyed = mix('MIX', mask, body.outputs['Image'], eye.outputs['Image'])
    lit = mix('ADD', None, eyed, rim)
    final = mix('MIX', body.outputs['Avatar'], body.outputs['Image'], lit)
    out, view = N.new('CompositorNodeComposite'), N.new('CompositorNodeViewer')
    out.use_alpha = view.use_alpha = False
    L.new(final, out.inputs['Image']); L.new(final, view.inputs['Image'])
    return tree
