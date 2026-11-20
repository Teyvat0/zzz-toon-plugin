"""Self-built geometry-node writer: sun direction / colour and head frame as point attributes.

The ZZZ_Toon shader reads these attributes, so a moved sun or head follows with no constants.
"""
import bpy

NAME = 'ZZZ_LightHead'
CHANNELS = ('color.r', 'color.g', 'color.b', 'energy')


def _store(tree, geometry, name, kind, value):
    node = tree.nodes.new('GeometryNodeStoreNamedAttribute')
    node.data_type, node.domain = kind, 'POINT'
    node.inputs['Name'].default_value = name
    tree.links.new(geometry, node.inputs['Geometry']); tree.links.new(value, node.inputs['Value'])
    return node.outputs['Geometry']


def _object(tree, ob):
    node = tree.nodes.new('GeometryNodeObjectInfo'); node.transform_space = 'ORIGINAL'
    node.inputs['Object'].default_value = ob
    return node


def build(owner, sun, head_center, head_forward, head_right):
    tree = bpy.data.node_groups.new(NAME, 'GeometryNodeTree')
    tree['zzz_owner'] = owner
    tree.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    tree.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    N, L = tree.nodes, tree.links
    gin, gout = N.new('NodeGroupInput'), N.new('NodeGroupOutput')
    rot = N.new('FunctionNodeRotateVector'); rot.inputs['Vector'].default_value = (0., 0., 1.)
    L.new(_object(tree, sun).outputs['Rotation'], rot.inputs['Rotation'])
    unit = N.new('ShaderNodeVectorMath'); unit.operation = 'NORMALIZE'; L.new(rot.outputs[0], unit.inputs[0])
    rgb = N.new('FunctionNodeCombineColor'); rgb.name = 'Combine Color'
    energy = N.new('ShaderNodeValue'); energy.name = 'Value'
    mul = N.new('ShaderNodeMix'); mul.data_type = 'RGBA'; mul.blend_type = 'MULTIPLY'
    mul.inputs['Factor'].default_value = 1.
    L.new(rgb.outputs[0], mul.inputs['A']); L.new(energy.outputs[0], mul.inputs['B'])
    geo = gin.outputs['Geometry']
    geo = _store(tree, geo, 'LightDirectionWS', 'FLOAT_VECTOR', unit.outputs[0])
    geo = _store(tree, geo, 'LightColor', 'FLOAT_COLOR', mul.outputs['Result'])
    for key, ob in (('HeadCenter', head_center), ('HeadForward', head_forward), ('HeadRight', head_right)):
        geo = _store(tree, geo, key, 'FLOAT_VECTOR', _object(tree, ob).outputs['Location'])
    L.new(geo, gout.inputs['Geometry'])
    for channel, path in zip(CHANNELS, ('nodes["Combine Color"].inputs[0].default_value',
                                        'nodes["Combine Color"].inputs[1].default_value',
                                        'nodes["Combine Color"].inputs[2].default_value',
                                        'nodes["Value"].outputs[0].default_value')):
        driver = tree.driver_add(path).driver
        driver.type, driver.expression = 'SCRIPTED', 'v'
        var = driver.variables.new(); var.name, var.type = 'v', 'SINGLE_PROP'
        target = var.targets[0]
        target.id_type, target.id, target.data_path = 'LIGHT', sun.data, channel
    tree.use_fake_user = True
    return tree
