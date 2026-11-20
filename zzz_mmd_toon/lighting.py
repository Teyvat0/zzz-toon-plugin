"""User-selected main light for the plugin's own geometry light writer.

The ZZZ_LightHead group reads ONE sun object (direction) and four drivers
(colour r/g/b and strength). set_main_light retargets those to another sun light.
"""
import re
import bpy

KEY, DEFAULT_KEY = 'zzz_main_light', 'zzz_default_light'
CHANNELS = {'color.r', 'color.g', 'color.b', 'energy'}


def group_for(scene):
    """The owned 'ZZZ_LightHead' group of this ZZZ scene, or None for any other scene."""
    for tree in bpy.data.node_groups:
        owner = tree.get('zzz_owner')
        if owner and re.sub(r'\.\d{3}$', '', tree.name) == 'ZZZ_LightHead' and scene.name.endswith(owner[:8]):
            return tree
    return None


def current(gn, fallback):
    return gn.get(KEY) or fallback


def _objects(tree, seen=None):
    seen = set() if seen is None else seen
    if tree.as_pointer() in seen:
        return
    seen.add(tree.as_pointer())
    for node in tree.nodes:
        for sock in node.inputs:
            if getattr(sock, 'type', '') == 'OBJECT':
                yield sock
        if getattr(node, 'node_tree', None):
            yield from _objects(node.node_tree, seen)


def set_main_light(gn, light):
    """light: a SUN light object, or None to return to the scene's own sun."""
    if gn.get(DEFAULT_KEY) is None:
        sockets = [s for s in _objects(gn) if s.default_value and s.default_value.type == 'LIGHT']
        gn[DEFAULT_KEY] = sockets[0].default_value if sockets else None
    light = light or gn.get(DEFAULT_KEY)
    if light is None or light.type != 'LIGHT' or light.data.type != 'SUN':
        raise ValueError('主光必须是日光 (SUN) 灯')
    previous = gn.get(KEY) or gn.get(DEFAULT_KEY)
    for sock in _objects(gn):
        if sock.default_value == previous:
            sock.default_value = light
    drivers = list(gn.animation_data.drivers) if gn.animation_data else []
    for fcurve in drivers:
        for var in fcurve.driver.variables:
            for target in var.targets:
                if target.data_path in CHANNELS:
                    target.id = light.data
    gn[KEY] = light
    gn.update_tag()
    return light
