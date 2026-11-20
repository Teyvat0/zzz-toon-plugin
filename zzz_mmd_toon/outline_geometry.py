"""Per-original-face shell, sharing the source material and live native Morph alpha.

No separation, source mesh attribute edits, material-slot insertion or rebind.
The evaluated FACE attribute distinguishes original and generated shell branches.
"""
import bpy
from .toon_outline import WIDTH_K, WELD, SMALL_ISLAND

SHELL_ATTRIBUTE = 'ZZZ_OutlineShell'


def _drive(ob, mod, tree, camera):
    """Frame Scale = sensor_width / lens (long frame side per unit distance), live from the camera."""
    ident = next(s.identifier for s in tree.interface.items_tree
                 if getattr(s, 'in_out', '') == 'INPUT' and s.name == 'Frame Scale')
    mod[ident] = 0.72
    driver = ob.driver_add('modifiers["%s"]["%s"]' % (mod.name, ident)).driver
    driver.type, driver.expression = 'SCRIPTED', 's / l'
    for name, path in (('s', 'sensor_width'), ('l', 'lens')):
        var = driver.variables.new()
        var.name, var.type = name, 'SINGLE_PROP'
        var.targets[0].id_type, var.targets[0].id, var.targets[0].data_path = 'CAMERA', camera.data, path


def _small_islands(nodes, links, frame):
    """Face field: True on faces of a connected piece whose total area is below (SMALL_ISLAND x frame)^2."""
    island = nodes.new('GeometryNodeInputMeshIsland')
    area = nodes.new('GeometryNodeInputMeshFaceArea')
    acc = nodes.new('GeometryNodeAccumulateField'); acc.data_type = 'FLOAT'; acc.domain = 'FACE'
    links.new(area.outputs['Area'], acc.inputs['Value'])
    links.new(island.outputs['Island Index'], acc.inputs['Group Index'])
    side = nodes.new('ShaderNodeMath'); side.operation = 'MULTIPLY'
    links.new(frame, side.inputs[0]); side.inputs[1].default_value = SMALL_ISLAND
    limit = nodes.new('ShaderNodeMath'); limit.operation = 'POWER'
    links.new(side.outputs[0], limit.inputs[0]); limit.inputs[1].default_value = 2.
    small = nodes.new('ShaderNodeMath'); small.operation = 'LESS_THAN'
    links.new(acc.outputs['Total'], small.inputs[0]); links.new(limit.outputs[0], small.inputs[1])
    return small.outputs[0]


def attach(ob, slot_specs, light_group, owner):
    tree = bpy.data.node_groups.new('ZZZ_PerFace_' + ob.name, 'GeometryNodeTree')
    tree['zzz_owner'] = owner
    tree['zzz_outline_policy'] = 'per original face material index; same material/live Morph alpha'
    tree.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    tree.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    tree.interface.new_socket(name='Frame Scale', in_out='INPUT', socket_type='NodeSocketFloat').default_value = .72
    nodes, links = tree.nodes, tree.links
    src = nodes.new('NodeGroupInput'); out = nodes.new('NodeGroupOutput')
    base = nodes.new('GeometryNodeGroup'); base.node_tree = light_group   # writes light / head attributes
    links.new(src.outputs['Geometry'], base.inputs['Geometry'])

    def mark(geometry, value):
        store = nodes.new('GeometryNodeStoreNamedAttribute')
        store.data_type = 'BOOLEAN'; store.domain = 'FACE'
        store.inputs['Name'].default_value = SHELL_ATTRIBUTE
        store.inputs['Value'].default_value = bool(value)
        links.new(geometry, store.inputs['Geometry'])
        return store.outputs['Geometry']

    original = mark(base.outputs['Geometry'], False)
    join = nodes.new('GeometryNodeJoinGeometry'); links.new(original, join.inputs['Geometry'])
    material_index = nodes.new('GeometryNodeInputMaterialIndex')
    pos = nodes.new('GeometryNodeInputPosition')
    camera = nodes.new('GeometryNodeObjectInfo'); camera.transform_space = 'RELATIVE'
    camera.inputs['Object'].default_value = bpy.context.scene.camera
    distance = nodes.new('ShaderNodeVectorMath'); distance.operation = 'DISTANCE'
    links.new(pos.outputs['Position'], distance.inputs[0]); links.new(camera.outputs['Location'], distance.inputs[1])
    frame = nodes.new('ShaderNodeMath'); frame.operation = 'MULTIPLY'   # world size of the whole frame at this vertex
    links.new(distance.outputs['Value'], frame.inputs[0]); links.new(src.outputs['Frame Scale'], frame.inputs[1])
    emitted = []
    for slot, spec in sorted(slot_specs.items()):
        # Generate shells even when initial native alpha is zero: a later native
        # MaterialMorph can reveal the surface, and its outline must then exist.
        if not spec['enabled'] or spec['width'] <= 0:
            continue
        choose = nodes.new('FunctionNodeCompare'); choose.data_type = 'INT'; choose.operation = 'EQUAL'
        links.new(material_index.outputs['Material Index'], choose.inputs[2]); choose.inputs[3].default_value = int(slot)
        separate = nodes.new('GeometryNodeSeparateGeometry'); separate.domain = 'FACE'
        links.new(original, separate.inputs['Geometry']); links.new(choose.outputs['Result'], separate.inputs['Selection'])
        weld = nodes.new('GeometryNodeMergeByDistance'); weld.inputs['Distance'].default_value = WELD
        links.new(separate.outputs['Selection'], weld.inputs['Geometry'])
        drop = nodes.new('GeometryNodeDeleteGeometry'); drop.domain = 'FACE'; drop.mode = 'ALL'
        links.new(weld.outputs['Geometry'], drop.inputs['Geometry'])
        links.new(_small_islands(nodes, links, frame.outputs[0]), drop.inputs['Selection'])
        flip = nodes.new('GeometryNodeFlipFaces'); links.new(drop.outputs['Geometry'], flip.inputs['Mesh'])
        normal = nodes.new('GeometryNodeInputNormal')
        width = nodes.new('ShaderNodeMath'); width.operation = 'MULTIPLY'
        links.new(frame.outputs[0], width.inputs[0]); width.inputs[1].default_value = -float(spec['width']) * WIDTH_K
        offset = nodes.new('ShaderNodeVectorMath'); offset.operation = 'SCALE'
        links.new(normal.outputs['Normal'], offset.inputs[0]); links.new(width.outputs[0], offset.inputs['Scale'])
        setpos = nodes.new('GeometryNodeSetPosition')
        links.new(flip.outputs['Mesh'], setpos.inputs['Geometry']); links.new(offset.outputs['Vector'], setpos.inputs['Offset'])
        # Retain the selected faces' ORIGINAL material index and SAME material ID.
        links.new(mark(setpos.outputs['Geometry'], True), join.inputs['Geometry'])
        emitted.append({'slot': int(slot), 'material': spec['material'].name,
                        'width': float(spec['width']), 'role': spec['role'], 'live_alpha': True})
    links.new(join.outputs['Geometry'], out.inputs['Geometry'])
    mod = ob.modifiers.new('仿ZZZ渲染_逐面描边与灯光', 'NODES'); mod.node_group = tree
    _drive(ob, mod, tree, bpy.context.scene.camera)
    ob['zzz_outline'] = bool(emitted)
    return {'source_mesh_unchanged': True, 'source_material_slots_unchanged': True,
            'shell_attribute': SHELL_ATTRIBUTE, 'slots': emitted,
            'limit': 'width is a fixed fraction of the frame (camera distance and focal length compensated); hull welded at 1e-5'}
