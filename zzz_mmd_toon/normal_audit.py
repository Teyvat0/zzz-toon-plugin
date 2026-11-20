"""Read-only audit: kept-original materials whose custom normals face inward.

Native MMD shading uses the shading normal, so such a material renders black
under any light. The ZZZ path is unaffected, so the user is told to map the slot.
"""
import numpy as np

THRESHOLD = 0.5   # fraction of loops opposing the polygon normal
MIN_LOOPS = 30


def reversed_fractions(meshes, materials):
    """{material pointer: (opposing loops, total loops)} for the given materials."""
    wanted = {m.as_pointer() for m in materials}
    found = {}
    for ob in meshes:
        me = ob.data
        if not me.polygons or not me.loops:
            continue
        slots = [m.as_pointer() if m else 0 for m in me.materials]
        nloop = len(me.loops)
        nrm = np.empty(nloop * 3, np.float32)
        me.corner_normals.foreach_get('vector', nrm)
        nrm = nrm.reshape(-1, 3)
        pn = np.empty(len(me.polygons) * 3, np.float32)
        me.polygons.foreach_get('normal', pn)
        pn = pn.reshape(-1, 3)
        mi = np.empty(len(me.polygons), np.int32)
        me.polygons.foreach_get('material_index', mi)
        ls = np.empty(len(me.polygons), np.int32)
        lt = np.empty(len(me.polygons), np.int32)
        me.polygons.foreach_get('loop_start', ls)
        me.polygons.foreach_get('loop_total', lt)
        poly_of_loop = np.repeat(np.arange(len(me.polygons)), lt)
        loops = np.concatenate([np.arange(s, s + t) for s, t in zip(ls, lt)]) if len(ls) else ls
        dots = np.einsum('ij,ij->i', nrm[loops], pn[poly_of_loop])
        mat_of_loop = mi[poly_of_loop]
        for index, pointer in enumerate(slots):
            if pointer not in wanted:
                continue
            sel = mat_of_loop == index
            bad, total = found.get(pointer, (0, 0))
            found[pointer] = (bad + int((dots[sel] < 0).sum()), total + int(sel.sum()))
    return found


def audit(meshes, source, rows):
    """Flag unmapped rows; returns the warning lines that were added."""
    pending = [(i, r) for i, r in enumerate(rows) if r.get('keep_original') and not r.get('user_selected')]
    if not pending:
        return []
    stats = reversed_fractions(meshes, [source[i] for i, _ in pending if i < len(source)])
    lines = []
    for i, row in pending:
        bad, total = stats.get(source[i].as_pointer(), (0, 0)) if i < len(source) else (0, 0)
        if total >= MIN_LOOPS and bad / total > THRESHOLD:
            row['reversed_normals'] = round(bad / total, 3)
            text = '法线朝内（%d%%）：MMD原材质会渲染成黑色；已改用几何法线渲染，仍建议在映射表为它选择ZZZ JSON' % round(100 * bad / total)
            row.setdefault('warnings', []).append(text)
            lines.append('%02d %s：%s' % (row['slot'], row['name'], text))
    return lines


REPAIR_NODE = 'ZZZ_TrueNormal'


def repair(material):
    """Feed the geometric normal to the native shader's Diffuse/Glossy nodes.

    Only the private mmd_shader group of this material is touched (copied first
    when shared); nothing else of the original material changes. Returns True
    when a link was added.
    """
    node = material.node_tree.nodes.get('mmd_shader') if material.use_nodes else None
    if node is None or node.type != 'GROUP' or node.node_tree is None:
        return False
    if node.node_tree.users > 1:
        node.node_tree = node.node_tree.copy()
    tree = node.node_tree
    if tree.nodes.get(REPAIR_NODE):
        return False
    targets = [n for n in tree.nodes if n.bl_idname in {'ShaderNodeBsdfDiffuse', 'ShaderNodeBsdfAnisotropic', 'ShaderNodeBsdfGlossy'}
               and 'Normal' in n.inputs and not n.inputs['Normal'].is_linked]
    if not targets:
        return False
    geo = tree.nodes.new('ShaderNodeNewGeometry')
    geo.name, geo.label = REPAIR_NODE, 'ZZZ 几何法线（原法线朝内）'
    geo.location = (min(n.location.x for n in targets) - 220, targets[0].location.y)
    for n in targets:
        tree.links.new(geo.outputs['True Normal'], n.inputs['Normal'])
    return True
