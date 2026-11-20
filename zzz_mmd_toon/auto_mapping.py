"""Character-independent ZZZ material association.

A required JSON/texture directory supplies game parameters. Image similarity
identifies an atlas, NEVER a material identity: each PMX material is resolved
independently by semantic domain and render state. No character profiles.
"""
from __future__ import annotations
import hashlib
import math
import os
from pathlib import Path
import re
import sys
import unicodedata
from collections import Counter
from . import resources

ROLES = {'body','face','hair','wing','eye','eyebrow','eye_shadow','eye_shadow_texture','eye_highlight','mouth'}
NO_EDGE = {'eye','eyebrow','eye_shadow','eye_shadow_texture','eye_highlight','mouth'}
FACE_ROLES = {'face','eye','eyebrow','eye_shadow','eye_shadow_texture','eye_highlight','mouth'}


def _text(value):
    return unicodedata.normalize('NFKC',str(value or '')).casefold()


def classify_name(name):
    t = _text(name)
    word = lambda s: any(x in t for x in s)
    if word(('发带','髪飾','髮飾','发饰','髪飾り','头饰','頭飾','hair accessory','hair_accessory','hairband')):return 'body'
    if word(('目光','目ハイライト','瞳ハイライト','眼高光','eye_highlight','eyehighlight')):return 'eye_highlight'
    if word(('眼影','目影','eyeshadow','eye_shadow')):return 'eye_shadow'
    if word(('眉','睫','二重','口线','口線','痣','brow','lash','decal')):return 'eyebrow'
    if word(('目','瞳','眼','虹彩','iris','sclera','pupil','eyewhite','eye_white')) or re.search(r'(^|[_\s])eyes?([_\s]|$)',t):return 'eye'
    if word(('口','舌','齿','齒','歯','牙','mouth','tongue','tooth','teeth')):return 'mouth'
    if word(('髪','髮','头发','頭髮','头髮','前发','侧发','后发','发','hair','bangs','fringe')):return 'hair'
    if word(('翅','翼','wing','feather')):return 'wing'
    if word(('颜','顔','脸','臉','face')):return 'face'
    return 'body'


def _role_is_explicit(name, role):
    # classify_name's catch-all body is NOT independent semantic evidence. A
    # nameless/general overlay must compete across all proven donor domains.
    return role!='body' or bool(re.search(r'body|torso|cloth|skin|身体|身體|躯|軀|肌|衣|服|肉|皮肤|皮膚|^体[0-9]*$',_text(name)))


def _base_image(mat):
    n = mat.node_tree.nodes.get('mmd_base_tex') if getattr(mat,'node_tree',None) else None
    return getattr(n,'image',None)


def _image_path(im):
    if im is None:return ''
    raw = im.filepath
    bpy = sys.modules.get('bpy')
    return str(Path(bpy.path.abspath(raw,library=im.library) if bpy else raw).resolve()) if raw else ''


def _thumbnail(im, cache):
    """Blender image copy is scaled, never the user's image or color space."""
    if im is None:return None
    key = im.as_pointer()
    if key in cache:return cache[key]
    bpy = sys.modules.get('bpy')
    try:
        if not bpy or im.size[0] == 0:return None
        cp = im.copy()
        try:
            cp.scale(32,32)
            pixels = list(cp.pixels)
            result = (tuple(im.size),[pixels[i] for i in range(len(pixels)) if i%4 != 3])
        finally:bpy.data.images.remove(cp)
        cache[key] = result
        return result
    except (RuntimeError,ValueError,OSError):return None


def _static_image(image):
    # Current-frame pixels cannot prove a low-alpha layer stays low-alpha. Do not
    # admit movies, sequences, tiled/viewer images, or animated image datablocks.
    return (image is not None and getattr(image,'source',None) in {'FILE','GENERATED'}
            and not getattr(image,'animation_data',None))


def _alpha_range(image):
    """Read all static source alpha without scaling or altering the source image."""
    if not _static_image(image) or min(image.size) <= 0:
        return None
    try:
        pixels = image.pixels
        # A truncated buffer, alpha-less image, or out-of-range alpha is not
        # evidence for a genuinely low-alpha source. Do not sample a thumbnail.
        if len(pixels) != int(image.size[0]) * int(image.size[1]) * 4:
            return None
        if int(getattr(image, 'channels', 4)) != 4:
            return None
        from array import array
        values = array('f', [0.]) * len(pixels)
        if hasattr(pixels, 'foreach_get'):
            pixels.foreach_get(values)
        else:
            values[:] = array('f', pixels)
        alpha = values[3::4]
        if not alpha or not all(math.isfinite(x) and 0. <= x <= 1. for x in alpha):
            return None
        return [float(min(alpha)), float(max(alpha))]
    except (RuntimeError, ValueError, TypeError):
        return None


def _distance(a,b):
    if not a or not b:return math.inf
    wa,ha=a[0];wb,hb=b[0]
    if abs(wa/ha-wb/hb)>.01:return math.inf
    return sum(abs(x-y) for x,y in zip(a[1],b[1]))/len(a[1])


def _json_role(md):
    # Token semantics only. Prefix character identity is never examined.
    token = _text(md.stem)
    if re.search(r'hair_?shadow', token):
        return 'hair_shadow'  # Separate effect pass, never the hair surface.
    role=classify_name(re.sub(r'^mat_','',md.stem,flags=re.I))
    # Props/effects (weapon, FX, halo, back, accessory part, items) are not the
    # character surface; they must not compete for body slots. Wings keep role.
    if role!='wing' and re.search(r'(^|_)(weapon\d*|fx\d*|halo|back|part|item)(_|$)',token):
        return 'prop'
    return role


def _state_score(md,mat,role):
    mmd=mat.mmd_material
    name=_text(mmd.name_j or mat.name)
    transparent = bool(re.search(r'(^|_)t(_|$)',_text(md.stem))) or float(md.get('_DstBlend',0) or 0)==10
    score=0.
    if role in {'eye','eye_highlight','eyebrow','mouth','eye_shadow','eye_shadow_texture'}:return score
    # Opaque native surface is not evidence for an alternate transparent pass.
    score += 0. if not transparent else .06
    if float(mmd.alpha)<.999:score += .04 if not transparent else 0.
    if any(x in name for x in ('透','透明','薄纱','sheer','transparent')):score += -.10 if transparent else .1
    ds=md.get('_DoubleSided')
    if ds is not None and bool(ds) != bool(mmd.is_double_sided):score+=.005
    return score


def _required(role):
    return {'_MainTex','_LightTex','_OtherDataTex','_OtherDataTex2'} if role in {'body','hair','wing'} else {'_MainTex','_LightTex'} if role=='face' else {'_MainTex'}


def _family(path, index):
    p=Path(path)
    if not re.search(r'_d$',p.stem,re.I):return {}
    result={'_MainTex':str(p)}
    for prop,suffix in (('_LightTex','N'),('_OtherDataTex','M'),('_OtherDataTex2','A')):
        ref=p.stem[:-1]+suffix
        try:target=index.find(ref)
        except (ValueError,OSError):target=None
        if target:result[prop]=target
    return result


def _choices(row, entries, index):
    """User-selectable JSON identities for one slot (explicit choice, never a guess).

    A JSON whose texture references are missing is completed only for the missing
    required maps, from the slot's nearest atlas family; that is reported to the
    user as a choice, not recorded as binding evidence.
    """
    role=row['role'];target='eye' if role in {'eye_highlight','eye_shadow','eye_shadow_texture'} else 'face' if role=='mouth' else role
    fill_path=row.get('atlas_path') or next((c['path'] for c in row.get('atlas_candidates',[])),'')
    family=_family(fill_path,index) if fill_path else {}
    result=[]
    for md in entries:
        jr=_json_role(md)
        if jr=='hair_shadow':continue
        overrides={}
        merged=dict(md.textures)
        for prop in _required(role):
            if merged.get(prop):continue
            if family.get(prop):overrides[prop]=family[prop];merged[prop]=family[prop]
        if any(not merged.get(prop) for prop in _required(role)):continue
        result.append({'stem':md.stem,'texture_overrides':overrides,'same_role':jr==target})
    result.sort(key=lambda c:(not c['same_role'],c['stem']))
    return result


def _exact_vector(value, size):
    result=tuple(map(float,value))
    if len(result)!=size or not all(map(math.isfinite,result)):
        raise ValueError('non-finite or incomplete geometry vector')
    return result


def _normal_corners(me, vertex_keys):
    """Normal-space proof without comparing Blender's decoded runtime cache.

    Flat polygons have a geometry-defined space. Smooth fans use *the same source
    point and connected fan*, not a claimed isomorphism of separate smooth fans:
    equal INT16_2D values alone do not prove equal normal spaces. This admits real
    shared-topology duplicates with custom normals but fails closed on unproved
    separately authored fan equivalence, including coincident split points.
    """
    attributes=me.attributes
    def values(name, data_type, domain, length, default):
        attribute=attributes.get(name)
        if attribute is None:return [default]*length
        if (attribute.data_type,attribute.domain,len(attribute.data))!=(data_type,domain,length):
            raise ValueError('unsupported normal attribute '+name)
        if data_type=='INT16_2D':
            result=[tuple(int(v) for v in item.value) for item in attribute.data]
            if any(len(v)!=2 or any(x < -32768 or x > 32767 for x in v) for v in result):
                raise ValueError('invalid authored signed-short2 normal')
            return result
        return [bool(item.value) for item in attribute.data]
    custom=values('custom_normal','INT16_2D','CORNER',len(me.loops),None)
    if bool(me.has_custom_normals)!=any(v is not None for v in custom):
        raise ValueError('incomplete authored custom-normal evidence')
    sharp_edge=values('sharp_edge','BOOLEAN','EDGE',len(me.edges),False)
    sharp_face=values('sharp_face','BOOLEAN','FACE',len(me.polygons),False)
    incident={};edge_users={};corners={};smooth={}
    for pi,polygon in enumerate(me.polygons):
        loops=tuple(polygon.loop_indices)
        if len(loops)<3:raise ValueError('invalid polygon normal topology')
        smooth[pi]=bool(polygon.use_smooth) and not sharp_face[pi]
        for n,li in enumerate(loops):
            loop=me.loops[li];vi=loop.vertex_index;next_vi=me.loops[loops[(n+1)%len(loops)]].vertex_index
            if set(me.edges[loop.edge_index].vertices)!={vi,next_vi}:
                raise ValueError('invalid edge/corner normal provenance')
            edge_users.setdefault(loop.edge_index,[]).append((pi,li))
            incident.setdefault(vi,[]).append((pi,li))
            # A full oriented polygon (not just a tessellation triangle) defines
            # a flat corner's normal space under later deformation as well.
            polygon_key=tuple(vertex_keys[me.loops[q].vertex_index] for q in loops[n:]+loops[:n])
            corners[li]=('flat',polygon_key,custom[li])
    for vi,uses in incident.items():
        remaining={pi:li for pi,li in uses if smooth[pi]}
        while remaining:
            first=next(iter(remaining));stack=[first];component={}
            while stack:
                pi=stack.pop()
                if pi not in remaining:continue
                li=remaining.pop(pi);component[pi]=li
                loops=tuple(me.polygons[pi].loop_indices);n=loops.index(li)
                for ei in (me.loops[li].edge_index,me.loops[loops[n-1]].edge_index):
                    # Nonmanifold edges are split normal boundaries in Blender;
                    # do not invent a connection across their coincident faces.
                    users=edge_users[ei]
                    if not sharp_edge[ei] and len(users)==2:
                        stack.extend(p for p,_ in users if p in remaining)
            fan=min(component.values())
            for li in component.values():corners[li]=('smooth-source-fan',vi,fan,custom[li])
    if len(corners)!=len(me.loops):raise ValueError('incomplete normal corner provenance')
    return corners


def _material_geometry(meshes, *, binding_only=False):
    """Exact oriented CORNER multisets, scoped to the SAME original object.

    binding_only proves a source position/UV-to-data-family association, NOT
    animation-equivalent duplicate surfaces and NEVER permission to hide a layer.

    No rounding, welding, reverse-winding match, or set conversion. All UV layers,
    weights (including native UV/SDEF groups) and every shape-key coordinate and
    relation participate. A different object is deliberately not a proven donor:
    rest-world coincidence cannot prove equal parents/modifiers/drivers over time.
    Unsupported/incomplete reads invalidate the whole material, never just the bad
    triangle. This is evidence for a conservative policy, not an MME emulator.
    """
    bymat={};vertex_ids={}
    for object_index,ob in enumerate(meshes):
        me=ob.data
        pointers={m.as_pointer() for m in me.materials if m is not None}
        for pointer in pointers:
            bymat.setdefault(pointer,{'triangles':Counter(),'blockers':[]})
        try:
            # Arbitrary mesh/key drivers, evaluated GN, and non-native deformers
            # can distinguish coincident vertices. Their semantics are not proved.
            if not binding_only:
                if any(getattr(data,'animation_data',None) for data in (me,getattr(me,'shape_keys',None))):
                    raise ValueError('mesh/key animation or drivers not proved')
                if any(mod.type!='ARMATURE' for mod in ob.modifiers):
                    raise ValueError('non-armature modifier semantics not proved')
            uv_layers=list(me.uv_layers)
            if not uv_layers:
                raise ValueError('no complete UV layer evidence')
            uv_meta=(me.uv_layers.active_index,tuple((u.name,bool(u.active_render)) for u in uv_layers))
            if any(len(u.data)!=len(me.loops) for u in uv_layers):
                raise ValueError('incomplete UV corner data')
            keys=me.shape_keys if not binding_only else None;blocks=list(keys.key_blocks) if keys else []
            if keys:
                shape_meta=(bool(keys.use_relative),float(keys.eval_time),tuple(
                    (k.name,k.relative_key.name if k.relative_key else None,k.vertex_group,
                     k.interpolation,float(k.frame),bool(k.mute),float(k.value),
                     float(k.slider_min),float(k.slider_max)) for k in blocks))
                if any(len(k.data)!=len(me.vertices) for k in blocks):
                    raise ValueError('incomplete shape-key vertex data')
            else:shape_meta=None
            vertex_keys=[]
            for vi,v in enumerate(me.vertices):
                weights=tuple(sorted((ob.vertex_groups[g.group].name,float(g.weight)) for g in v.groups)) if not binding_only else ()
                if not all(math.isfinite(w) and 0.<=w<=1. for _,w in weights):
                    raise ValueError('invalid vertex-group weight')
                value=(_exact_vector(v.co,3),weights,tuple(_exact_vector(k.data[vi].co,3) for k in blocks))
                # Intern full exact tuples, rather than hash rounded coordinates.
                vertex_keys.append(vertex_ids.setdefault(value,len(vertex_ids)))
            normals=_normal_corners(me,vertex_keys) if not binding_only else {li:None for li in range(len(me.loops))}
            me.calc_loop_triangles()
            pending={pointer:Counter() for pointer in pointers}
            for tri in me.loop_triangles:
                mat=me.materials[tri.material_index]
                if mat is None:continue
                loops=tuple(tri.loops);vertices=tuple(tri.vertices)
                if len(loops)!=3 or len(vertices)!=3 or any(me.loops[li].vertex_index!=vi for li,vi in zip(loops,vertices)):
                    raise ValueError('incomplete triangle corner provenance')
                corners=tuple((vertex_keys[vi],tuple(_exact_vector(u.data[li].uv,2) for u in uv_layers),normals[li])
                              for vi,li in zip(vertices,loops))
                # Cyclic rotations are equal; reversed winding is NOT equal.
                oriented=min(corners[n:]+corners[:n] for n in range(3))
                key=(object_index,uv_meta,shape_meta,oriented)
                pending[mat.as_pointer()][key]+=1
            for pointer,triangles in pending.items():bymat[pointer]['triangles'].update(triangles)
        except (AttributeError,IndexError,KeyError,RuntimeError,TypeError,ValueError,OverflowError) as exc:
            for pointer in pointers:bymat[pointer]['blockers'].append(str(exc))
    return bymat


def _json_identity(md, overrides):
    # Paths, not stems: two separate JSON files with the same basename are still
    # two independent states. Overrides are part of the binding identity too.
    return (str(Path(md.path).resolve()),tuple(sorted(overrides.items())))


def _duplicate_families(own, families, *, geometry_field='geometry'):
    """Consider ALL pre-ranking compatible JSON bindings, not just chosen rows.

    The overlay must be a nonempty exact multiset subset of ONE family. Donor
    surplus is OK (a pass may cover a subset); overlay surplus is never OK. Each
    original material is counted once per family even if its slot is repeated.
    """
    matches=[]
    if not own or own['blockers'] or not own['triangles']:return matches
    for identity,entry in families.items():
        covered=Counter()
        for geometry in entry[geometry_field].values():
            if not geometry['blockers']:covered.update(geometry['triangles'])
        if not (own['triangles']-covered):
            matches.append((identity,entry))
    return matches


def _prefer_base_variant(matches):
    """Collapse a base JSON and its `_T` transparent-pass twin to the base.

    Data basis: the twin carries the same D/N/M/A textures and differs only in render
    state (blend/render-type fields). When the exact binding covers both, the base JSON
    is the surface; the twin is never preferred. Different texture families never collapse.
    """
    if len(matches)<2:return matches
    stems={entry['md'].stem:(identity,entry) for identity,entry in matches}
    drop=set()
    for stem in stems:
        for suffix in ('_T_UI','_T'):
            if stem.endswith(suffix):
                base=stem[:-len(suffix)]+suffix[2:] if suffix=='_T_UI' else stem[:-2]
                if base in stems and stems[base][0][1:]==stems[stem][0][1:]:
                    drop.add(stem)
    return [(i,e) for i,e in matches if e['md'].stem not in drop]


def _mme_morph_blockers(arm, material):
    """Do not hide an author-controlled material/legacy UV effect by default.

    Shape coordinates and vertex-group UV Morphs are in the corner proof. Native
    material Morphs can deliberately reveal an effect with no donor equivalent;
    DATA UV Morphs have separate indices and are not proved here. Missing native
    metadata also fails closed, rather than assuming there are no Morphs.
    """
    blockers=[]
    try:
        root=getattr(arm,'parent',None);seen=set()
        while root is not None and getattr(root,'mmd_type',None)!='ROOT':
            pointer=id(root)
            if pointer in seen:raise ValueError('cyclic MMD parent chain')
            seen.add(pointer);root=root.parent
        if root is None:raise ValueError('native MMD Morph metadata unavailable')
        metadata=root.mmd_root
        if any(getattr(m,'data_type',None)!='VERTEX_GROUP' for m in metadata.uv_morphs):
            blockers.append('legacy/unknown UV Morph storage not proved')
        for morph in metadata.material_morphs:
            for offset in morph.data:
                target=offset.material_data;numeric=int(offset.material_id)
                if numeric<0 or target is None or target==material:
                    blockers.append('material Morph can control this effect: '+morph.name)
    except (AttributeError,TypeError,ValueError) as exc:
        blockers.append(str(exc))
    if getattr(material,'animation_data',None) or getattr(getattr(material,'node_tree',None),'animation_data',None):
        blockers.append('animated/driven source material not proved')
    return list(dict.fromkeys(blockers))


def _mme_sphere_image(material):
    nodes=getattr(getattr(material,'node_tree',None),'nodes',None)
    node=nodes.get('mmd_sphere_tex') if nodes is not None else None
    image=getattr(node,'image',None)
    # The numeric ADD flag alone may be stale; require an actual decodable sphere
    # source as well. No filename/character/suffix is an admission criterion.
    try:
        if _static_image(image) and min(image.size)>0 and len(image.pixels)==int(image.size[0])*int(image.size[1])*4:
            return image
    except (AttributeError,RuntimeError,TypeError,ValueError):pass
    return None


def plan(materials, meshes, arm, resource_dir='') -> dict:
    mats=list(materials);warnings=[];errors=[];slot_errors=[]
    result={'profile':None,'rows':[],'errors':errors,'slot_errors':slot_errors,'warnings':warnings,'resource_dir':'',
            'material_names':[m.mmd_material.name_j or m.name for m in mats],
            'original_bones':len(arm.data.bones),'catalog':[],'resource_hashes':{}}
    if not str(resource_dir or '').strip():
        errors.append('必须选择包含对应角色 JSON 与贴图的资源目录。');return result
    try:root=resources.normalize_root(resource_dir);catalog=resources.resolve_catalog(root)
    except (OSError,ValueError,TypeError,RuntimeError) as exc:
        errors.append('资源目录无法解析: '+str(exc));return result
    result['resource_dir']=root
    warnings.extend(catalog.get('warnings',[]))
    # Broken/unreferenced catalogue entries stay visible in diagnostics; selected
    # material bindings are checked below and cannot bypass required maps.
    warnings.extend('资源目录诊断: '+str(e) for e in catalog.get('errors',[]))
    entries=list(catalog['materials']);index=catalog['index']
    result['catalog']=[{'stem':m.stem,'path':str(m.path),'textures':dict(m.textures),
                        'resolution':getattr(m,'resolution',{}),'unresolved':getattr(m,'unresolved',{})} for m in entries]
    if not entries:errors.append('目录没有可解析的游戏材质 JSON。');return result
    bpy=sys.modules.get('bpy');cache={};loaded=[];thumbs={};binding_candidates={}
    # Candidate textures include nameless-reference structural families. Loading
    # them is read-only and temporary; no image ownership is assigned here.
    paths=set()
    for md in entries:
        ref=md.textures.get('_MainTex')
        if ref:
            try:p=index.find(ref)
            except (ValueError,OSError):p=None
            if p:paths.add(str(Path(p).resolve()))
    for p in Path(root).rglob('*'):
        if p.is_file() and p.suffix.lower() in {'.png','.tga','.dds','.bmp','.jpg','.jpeg'} and re.search(r'_d$',p.stem,re.I):paths.add(str(p.resolve()))
    try:
        for path in sorted(paths):
            try:
                im=bpy.data.images.load(path,check_existing=False);loaded.append(im);thumbs[path]=_thumbnail(im,cache)
            except (RuntimeError,OSError):warnings.append('无法解码候选贴图: '+path)
        for slot,mat in enumerate(mats):
            name=result['material_names'][slot];role=classify_name(name);mmd=mat.mmd_material
            row={'slot':slot,'name':name,'stem':'','role':role,'role_evidence':'name-token' if _role_is_explicit(name,role) else 'default-unconstrained',
                 'state':'AUTO','alpha':float(mmd.alpha),
                 'sourceAlpha':float(mmd.alpha),'outline':0. if role in NO_EDGE else .30 if role=='face' else .34 if role=='hair' else .38,
                 'palette':None,'archive':False,'backend':'GAME_JSON','confidence':0.,'evidence':[],'warnings':[],
                 'texture_overrides':{},'preserve_source_texture':False,'keep_original':False,'choices':[]}
            result['rows'].append(row)
            source=_thumbnail(_base_image(mat),cache)
            candidates=sorted(((_distance(source,t),p) for p,t in thumbs.items()),key=lambda x:(x[0],x[1]))
            row['atlas_candidates']=[{'distance':d,'path':p} for d,p in candidates[:4] if math.isfinite(d)]
            atlas=''
            if candidates and candidates[0][0]<=.06 and (len(candidates)==1 or candidates[1][0]-candidates[0][0]>.012):
                atlas=candidates[0][1];row['evidence'].append('32px线性RGB图像关联 MAE=%.7f'%candidates[0][0])
            elif candidates and candidates[0][0]<=.25 and (len(candidates)==1 or (candidates[1][0]>candidates[0][0]+1e-6 and candidates[1][0]>=candidates[0][0]*1.4)) and source and source[0]==thumbs[candidates[0][1]][0]:
                atlas=candidates[0][1];row['warnings'].append('图像关联为较低置信度，已记录');row['evidence'].append('loose-MAE=%.7f'%candidates[0][0])
            if role=='eye_shadow':
                # A solid black PMX overlay must not be replaced by a face-atlas
                # sample. Still use the selected game's Eye JSON parameters.
                if source is None or max(source[1])-min(source[1])<.015:
                    row['role']='eye_shadow';atlas=''
                else:row['role']=role='eye_shadow_texture'
            if role=='face' and not bool(mmd.enabled_toon_edge):
                row['role']=role='eyebrow';row['outline']=0.;row['evidence'].append('Face命名但无描边的小面片，按脸部贴花域处理')
            row['atlas_path']=atlas
            source_role=role
            target_role='eye' if role in {'eye_highlight','eye_shadow','eye_shadow_texture'} else 'face' if role=='mouth' else role
            compatible=[]
            # Freeze EVERY atlas-compatible catalog identity before state ranking
            # or specialized source-preserving inference. The latter must never
            # become evidence for automatic MME suppression.
            atlas_proven=bool(atlas)
            for md in entries:
                jr=_json_role(md)
                # A prop JSON (weapon/FX/...) may serve a body-domain slot only when
                # its own named _MainTex is the proven atlas; it never wins over a
                # character JSON (dropped below).
                if jr=='prop' and target_role=='body' and atlas:jr='body'
                if jr != target_role:continue
                ref=md.textures.get('_MainTex')
                try:main=str(Path(index.find(ref)).resolve()) if ref and index.find(ref) else ''
                except (ValueError,OSError):main=''
                overrides={}
                if atlas and main and main!=atlas:continue
                if atlas and not main:
                    # Only an actual non-null serialized reference can be resolved
                    # from independent PMX atlas evidence. A deliberately textureless
                    # material is not a missing-reference candidate.
                    if '_MainTex' not in getattr(md, 'references', {}):continue
                    overrides=_family(atlas,index) if role in {'body','hair','wing'} else {'_MainTex':atlas}
                if not atlas and source_role not in {'eye_shadow'}:continue
                merged={**md.textures,**overrides}
                if any(not merged.get(prop) for prop in _required(role) if role!='eye_shadow'):continue
                compatible.append((_state_score(md,mat,role),md,overrides))
            # Explicit evidence beats inference: with a proven atlas, a JSON that
            # names that atlas itself outranks JSONs whose empty _MainTex was only
            # filled from the atlas family (e.g. Weapon/FX/Back with null names).
            if len(compatible)>1:
                chars=[c for c in compatible if _json_role(c[1])!='prop']
                if chars:compatible=chars
            if atlas and len(compatible)>1:
                explicit=[c for c in compatible if not c[2]]
                if explicit and len(explicit)<len(compatible):compatible=explicit
            # A body/accessory section may share a hair-only data atlas. Reuse its
            # JSON data parameters but explicitly keep the body shader domain.
            # Hair sharing the body atlas (no Hair JSON in the character) takes the
            # same route: JSON data from the atlas owner, hair domain kept.
            # Face decals (brow/lash/eyelid) with a proven face atlas but no Eyebrow
            # JSON use the face JSON that owns that same atlas.
            if not compatible and atlas and role=='eyebrow':
                for md in entries:
                    if _json_role(md)!='face':continue
                    ref=md.textures.get('_MainTex')
                    try:main=str(Path(index.find(ref)).resolve()) if ref and index.find(ref) else ''
                    except (ValueError,OSError):continue
                    if main==atlas and all(md.textures.get(p) for p in _required('face')):
                        compatible.append((_state_score(md,mat,role)+.12,md,{}))
                if compatible:row['warnings'].append('贴花使用同atlas的Face JSON参数（无独立Eyebrow JSON）')
            if not compatible and atlas and role in {'body','hair'}:
                for md in entries:
                    if _json_role(md) not in {'body','hair','wing'}:continue
                    if any(not md.textures.get(prop) for prop in _required(role)):continue
                    ref=md.textures.get('_MainTex')
                    try:main=str(Path(index.find(ref)).resolve()) if ref and index.find(ref) else ''
                    except (ValueError,OSError):continue
                    if main==atlas:compatible.append((_state_score(md,mat,role)+.12,md,{}))
                if compatible:row['warnings'].append('附件共用数据族：使用该atlas的JSON参数，保留身体域')
            if atlas_proven and role in {'body','hair','wing'}:
                binding_candidates[mat.as_pointer()]=list(compatible)
            # A unique specialized wing domain can identify its parameter set
            # even when a PMX author repainted the wing atlas. Never use the
            # nearest unrelated body/weapon atlas; preserve that source colour.
            # Multiple complete wing JSONs remain unresolved, irrespective of score.
            if not compatible and role=='wing' and source is not None:
                specialized=[md for md in entries if _json_role(md)=='wing'
                             and all(md.textures.get(prop) for prop in _required(role))]
                if len(specialized)==1:
                    compatible=[(_state_score(specialized[0],mat,role),specialized[0],{})]
                    row['preserve_source_texture']=True
                    row['warnings'].append('INFERRED：唯一翅膀语义JSON；源贴图经过编辑，保留原D/Alpha。非原游戏绑定证明。')
                    row['evidence'].append('unique specialized wing domain; no nearest-atlas substitution')
            compatible.sort(key=lambda x:(x[0],x[1].stem))
            if compatible and (len(compatible)==1 or compatible[1][0]-compatible[0][0]>.009):
                score,md,overrides=compatible[0]
                row.update(stem=md.stem,json_path=str(md.path),texture_overrides=overrides,confidence=.98 if atlas else .82)
                row['evidence'] += ['独立JSON身份 '+md.stem,'语义域 '+role,'源透明度/双面与JSON状态排序']
                if overrides:row['warnings'].append('无Name引用以源atlas证据推断同族DNMA；不是PathID原样还原')
                row['resolution']=getattr(md,'resolution',{})
                row['unresolved']=getattr(md,'unresolved',{})
                if role=='eye_shadow':row['color_override']=[0.,0.,0.,1.]
            else:
                row['unresolved_reason']='无法唯一关联材质JSON/atlas/state'
        # Build once from the complete PRE-RANKING catalog binding space. A
        # recovered overlay must never become a donor for a subsequent overlay.
        geometry=_material_geometry(meshes);bindings=_material_geometry(meshes,binding_only=True);families={}
        for source_row,source_mat in zip(result['rows'],mats):
            pointer=source_mat.as_pointer()
            if source_row.get('preserve_source_texture'):continue
            for _,md,overrides in binding_candidates.get(pointer,[]):
                identity=(*_json_identity(md,overrides),source_row['role'])
                entry=families.setdefault(identity,{'md':md,'overrides':dict(overrides),'rows':[], 'geometry':{},'binding':{}})
                entry['rows'].append(source_row)
                if pointer in geometry:entry['geometry'][pointer]=geometry[pointer]
                if pointer in bindings:entry['binding'][pointer]=bindings[pointer]
        duplicate_proofs={}
        for row,mat in zip(result['rows'],mats):
            if row['stem']:continue
            pointer=mat.as_pointer();own=bindings.get(pointer)
            eligible={identity:entry for identity,entry in families.items()
                      if row['role_evidence']=='default-unconstrained' or identity[2]==row['role']}
            matches=_duplicate_families(own,eligible,geometry_field='binding')
            matches=_prefer_base_variant(matches)
            diagnostic={'schema':'exact-source-position-uv-binding.v1','role_evidence':row['role_evidence'],
                'pre_ranking_families':len(eligible),'candidate_families':[
                {'json_path':identity[0],'stem':entry['md'].stem,'role':identity[2],
                 'donor_slots':sorted({r['slot'] for r in entry['rows']})} for identity,entry in matches],
                'blockers':list(own['blockers']) if own else ['no source triangle evidence']}
            row['binding_evidence']=diagnostic
            if len(matches)==1:
                identity,entry=matches[0];md=entry['md']
                # Scores may select just one of several catalog bindings. Require
                # actual selected donors for this exact path + overrides, not
                # hypothetical/unresolved donors or inferred overlay chains.
                donors=[r for r in entry['rows'] if r.get('json_path')==identity[0]
                        and tuple(sorted(r['texture_overrides'].items()))==identity[1]
                        and not r.get('preserve_source_texture')]
                selected={m.as_pointer():bindings[m.as_pointer()] for r,m in zip(result['rows'],mats)
                          if r in donors and m.as_pointer() in bindings and m!=mat}
                if _duplicate_families(own,{identity:{'geometry':selected}}):
                    role=identity[2]
                    row.update(stem=md.stem,json_path=str(md.path),texture_overrides=dict(entry['overrides']),
                               preserve_source_texture=True,confidence=.90,role=role,
                               resolution=getattr(md,'resolution',{}),unresolved=getattr(md,'unresolved',{}))
                    diagnostic.update(triangles=sum(own['triangles'].values()),unmatched_triangles=0)
                    row['evidence'].append('100%精确同绕序源位置/全部UV三角多重集被全局唯一JSON/语义族覆盖；仅数据绑定，不证明动画重复')
                    row['warnings'].append('借用底层JSON数据参数；保留源D/Alpha及可见性，不证明权重/动画重复或原MME效果等价')
                    row.pop('unresolved_reason',None)
                    strict_own=geometry.get(pointer)
                    strict_matches=_duplicate_families(strict_own,eligible)
                    strict_selected={p:geometry[p] for p in selected if p in geometry}
                    complete=_duplicate_families(strict_own,{identity:{'geometry':strict_selected}})
                    covered=Counter()
                    for g in strict_selected.values():
                        if not g['blockers']:covered.update(g['triangles'])
                    duplicate={'schema':'exact-oriented-corners.v1','pre_ranking_families':len(eligible),
                        'global_candidate_families':len(strict_matches),
                        'triangles':sum(strict_own['triangles'].values()) if strict_own else 0,
                        'unmatched_triangles':sum((strict_own['triangles']-covered).values()) if strict_own else None,
                        'blockers':list(strict_own['blockers']) if strict_own else ['no exact geometry evidence']}
                    row['duplicate_evidence']=duplicate
                    if len(strict_matches)==1 and strict_matches[0][0]==identity and complete:
                        duplicate_proofs[pointer]=(identity,donors)
                    else:duplicate['blockers'].append('full weights/ShapeKeys/normal-space duplicate coverage or global uniqueness not proved')
                else:diagnostic['blockers'].append('no complete selected donor family')
            else:
                diagnostic['blockers'].append('global exact JSON family count is %d, not 1'%len(matches))
            if not row['stem']:
                # Never guessed: the slot keeps its native MMD material until the
                # user picks a JSON (row['choices']) or confirms keeping it.
                row['keep_original']=True
                row['warnings'].append('精确数据绑定证据不足：默认保留MMD原材质（可在映射表手动选择JSON）；详见binding_evidence')
                message='%02d %s: %s'%(row['slot'],row['name'],row.get('unresolved_reason','无法关联'))
                errors.append(message);slot_errors.append(message)
        for row,mat in zip(result['rows'],mats):
            if not row.get('preserve_source_texture') or not row.get('stem'):continue
            proof=duplicate_proofs.get(mat.as_pointer());blockers=[]
            if proof is None:blockers.append('no globally unique exact duplicate proof; specialized inference is not proof')
            blockers.extend(_mme_morph_blockers(arm,mat))
            raster_evidence=[]
            if proof:
                identity=proof[0]
                md=next((m for m in entries if _json_identity(m,row['texture_overrides'])[0]==identity[0]),None)
                detached=resources.preview_backface_culling(md,row['role']) if md is not None else None
                effect_cull=resources.native_preview_culling(mat,detached,preserve_source_texture=True)
                for donor_row,donor_mat in zip(result['rows'],mats):
                    if donor_row in proof[1]:
                        blockers.extend('donor slot %d: %s'%(donor_row['slot'],reason)
                                        for reason in _mme_morph_blockers(arm,donor_mat))
                        donor_sides=getattr(donor_mat.mmd_material,'is_double_sided',None)
                        effect_sides=getattr(mat.mmd_material,'is_double_sided',None)
                        if donor_sides is None or effect_sides is None or bool(donor_sides)!=bool(effect_sides):
                            blockers.append('donor/effect double-sided coverage differs or is unavailable')
                        donor_cull=resources.native_preview_culling(donor_mat,detached,preserve_source_texture=False) if detached is not None else None
                        raster_evidence.append({'donor_slot':donor_row['slot'],'donor_backface_culling':donor_cull,
                                                'effect_backface_culling':effect_cull})
                        if donor_cull is None or effect_cull is None or donor_cull!=effect_cull:
                            blockers.append('final donor/effect raster culling differs or is unavailable')
            base_image=_base_image(mat)
            if not _static_image(base_image):blockers.append('base source is not a static FILE/GENERATED image')
            sphere_image=_mme_sphere_image(mat)
            alpha=_alpha_range(base_image)
            additive=str(getattr(mat.mmd_material,'sphere_texture_type',''))=='2'
            if not additive:blockers.append('source sphere mode is not ADD')
            if sphere_image is None:blockers.append('no readable static native sphere source')
            if alpha is None or alpha[1]>.35:blockers.append('complete source alpha is not proven within [0, .35]')
            if blockers:
                row['effect_diagnostic']={'policy':'PRESERVE','blockers':blockers}
                row['warnings'].append('未默认关闭：MME重复效果证明不足；保留分部。手动恢复也不等于原MME效果复现。')
                continue
            identity,donors=proof
            own=geometry[mat.as_pointer()]['triangles']
            row['effect_policy']='MME_DUPLICATE_OFF'
            row['effect_evidence']={'schema':'exact-oriented-corners.v1','source_alpha_range':alpha,
                                    'sphere_texture_type':'2','sphere_source_readable':True,
                                     'static_source_images':True,'donor_effect_sidedness_equal':True,
                                     'final_raster_culling_equal':True,'raster_coverage':raster_evidence,
                                    'triangle_overlap':1.,'triangles':sum(own.values()),'unmatched_triangles':0,
                                    'comparison':'exact same-object oriented corner multiset, all UV/weights/ShapeKeys',
                                    'global_candidate_families':1,'json_path':identity[0],
                                    'donor_slots':sorted({r['slot'] for r in donors}),
                                    'material_morph_control':False}
            row['archive']=True
            row['warnings'].append('精确重复、全局唯一JSON族、无独立材质Morph的低Alpha加算源层：本渲染器默认关闭并归组保留。不是删除、原发色修正或原MME效果等效认证。')
        for row in result['rows']:row['choices']=_choices(row,entries,index)
        result['summary']={'materials':len(mats),'mapped':sum(bool(r['stem']) for r in result['rows']),
                           'unresolved':sum(not r['stem'] for r in result['rows'])}
    finally:
        for im in loaded:
            if bpy.data.images.get(im.name)==im:bpy.data.images.remove(im)
    return result
