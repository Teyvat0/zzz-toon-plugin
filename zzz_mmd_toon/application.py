"""Build/prehash all detached shaders before committing to any original material."""
from pathlib import Path
import bpy
from . import materials, validation, game_bridge, outline_geometry, normal_audit

NO_EDGE={'eye','eyebrow','eye_shadow','eye_shadow_texture','eye_highlight','mouth'}
PALETTES={'face':(.36,.16,.19),'hair':(.24,.12,.19),'body':(.22,.22,.29),'wing':(.30,.30,.37)}


def _palette(outline, color):
    linear=[(x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4) for x in color]
    shader=next(n for n in outline.node_tree.nodes if n.type=='GROUP')
    for i in range(1,6):shader.inputs['OutlineColor'+(str(i) if i>1 else '')].default_value=(*linear,1.)


def is_transparent(row):
    """ON/OFF are explicit user choices; AUTO follows the scan's glass/sheer evidence."""
    mode = row.get('transparency', 'AUTO')
    return mode == 'ON' or (mode == 'AUTO' and bool(row.get('transparent_auto')))


def apply(parts, source_materials, rows, groups, directory, owner, outline_scale, root):
    materials.configure(directory,groups,owner)
    pending=[];used_hashes={};diagnostics=[]
    # Nothing touches original materials until ALL selected JSON/data images have
    # decoded and ALL used file hashes are readable. No false generic fallback.
    try:
        for row,source in zip(rows,source_materials):
            if row.get('keep_original'):continue
            surface,outline,info=materials.build_material(row['stem'],row['role'],
                'ZZZ_Game_'+owner[:8]+'_'+str(row['slot']),alpha_override=1.,
                color_override=row.get('color_override'),texture_overrides=row.get('texture_overrides'),
                transparent=is_transparent(row))
            pending.append((row,source,surface,outline,info))
            _palette(outline,row.get('palette') or PALETTES.get(row['role'],PALETTES['body']))
            info['binding_resolution']=row.get('resolution',{})
            info['binding_unresolved']=row.get('unresolved',{})
            info['inferred_texture_overrides']=row.get('texture_overrides',{})
            paths={info['resource_json']}
            for item in info.get('images',[]):paths.add(item['path'])
            for path in sorted(paths):
                target=str(Path(path).resolve())
                if not Path(target).is_file():raise RuntimeError('必需游戏资源丢失: '+target)
                used_hashes[target]=validation.file_hash(target)
            for node in surface.node_tree.nodes:
                im=getattr(node,'image',None)
                if im is not None and (min(im.size)<=0 or not len(im.pixels)):
                    raise RuntimeError('游戏贴图解码失败: '+str(im.filepath))
            # Source overrides are deliberate PMX edited duplicate overlays. Record
            # their provenance too; original image colorspace/alpha are untouched.
            if row.get('preserve_source_texture'):
                node=source.node_tree.nodes.get('mmd_base_tex')
                im=getattr(node,'image',None)
                if im is None or min(im.size)<=0:raise RuntimeError('PMX叠层原图解码失败: '+source.name)
                path=bpy.path.abspath(im.filepath,library=im.library)
                if path and Path(path).is_file():used_hashes[str(Path(path).resolve())]=validation.file_hash(path)
        outlines={}
        for row,source,surface,outline,info in pending:
            info['bridge']=game_bridge.attach(source,surface,outline,owner,role=row['role'],
                preserve_source_texture=row.get('preserve_source_texture',False),cull=row.get('cull','AUTO'))
            source['zzz_source_slot']=row['slot'];source['source_json']=info['resource_json']
            source['zzz_material_uid']=owner+':'+str(row['slot'])
            source['resource_stem']=row['stem'];source['preview_role']=row['role']
            info['backend']='GAME_JSON';row['applied_backend']='GAME_JSON'
            diagnostics.append(info);outlines[source.as_pointer()]=outline
        # Slots without a selected JSON keep their native MMD material untouched
        # (identity/slot tags only); the user has been told in the plan/report.
        for row,source in zip(rows,source_materials):
            if not row.get('keep_original'):continue
            source['zzz_source_slot']=row['slot'];source['zzz_material_uid']=owner+':'+str(row['slot'])
            source['preview_role']=row['role'];source['zzz_keep_original']=True
            repaired=bool(row.get('reversed_normals')) and normal_audit.repair(source)
            diagnostics.append({'slot':row['slot'],'backend':'MMD_ORIGINAL','material':source.name,'true_normal_repair':repaired})
        bymat={m.as_pointer():r for m,r in zip(source_materials,rows)}
        for ob in parts.values():
            specs={}
            for index,mat in enumerate(ob.data.materials):
                row=bymat[mat.as_pointer()]
                ob['zzz_material_ref_'+str(index)]=mat
                specs[index]={'material':mat,
                    'width':float(row['outline'])*outline_scale,'role':row['role'],
                    'enabled':bool(mat.mmd_material.enabled_toon_edge) and row['role'] not in NO_EDGE
                              and not row.get('keep_original') and not is_transparent(row)}
            info=outline_geometry.attach(ob,specs,groups['LightHead'],owner)
            diagnostics.append({'object':ob.name,'per_face_outline':info})
        return diagnostics,used_hashes
    finally:
        # Detached construction materials are NOT source IDs and no longer needed.
        # Owned groups retain every actual shader/image dependency after cloning.
        for row,source,surface,outline,info in pending:
            for construction in (surface,outline):
                if bpy.data.materials.get(construction.name)==construction and construction.users == 0:
                    bpy.data.materials.remove(construction)
