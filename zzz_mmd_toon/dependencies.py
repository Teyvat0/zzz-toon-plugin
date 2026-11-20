"""Separate currently required render inputs from retained source-image provenance."""
import hashlib
from pathlib import Path


def retained_images(parts):
    """All source/game image references, including hidden and disconnected branches.

    This is NOT a render admission walk: missing unused native Toon/Sphere inputs
    remain diagnostic only. Valid images are packed and hashed for preservation.
    """
    images={};seen=set()
    def visit(tree):
        if tree is None or tree.as_pointer() in seen:return
        seen.add(tree.as_pointer())
        for node in tree.nodes:
            image=getattr(node,'image',None)
            if image is not None:images[image.as_pointer()]=image
            # Geometry nodes may retain a Material ID only through an input
            # socket, without that material being in any object material slot.
            for socket in node.inputs:
                value=getattr(socket,'default_value',None)
                if getattr(value,'bl_rna',None) and value.bl_rna.identifier=='Material' and value.use_nodes:
                    visit(value.node_tree)
            child=getattr(node,'node_tree',None)
            if child is not None:visit(child)
    for ob in parts.values():
        for mat in ob.data.materials:
            if mat is not None and mat.use_nodes:visit(mat.node_tree)
        for mod in ob.modifiers:
            if mod.type=='NODES' and mod.node_group:visit(mod.node_group)
    return list(images.values())


def _packed_hashes(image):
    files=list(image.packed_files)
    return [hashlib.sha256(bytes(item.packed_file.data)).hexdigest() for item in files]


def pack_retained_images(parts):
    """Pack valid retained images; keep broken unused inputs out of admission.

    File hashes record source provenance, packed hashes guard actual saved bytes.
    Hashes of disconnected/native images never become required game-file hashes.
    """
    import bpy
    from .validation import file_hash
    required={im.as_pointer() for im in active_images(parts)}
    result=[]
    for image in sorted(retained_images(parts),key=lambda x:x.name_full):
        path=str(Path(bpy.path.abspath(image.filepath,library=image.library)).resolve()) if image.filepath else ''
        needed=image.as_pointer() in required
        row={'name':image.name_full,'source_path':path,'required_for_current_render':needed,
             'source_file_sha256':None,'packed_sha256':[]}
        valid=image.size[0]>0 and image.size[1]>0 and len(image.pixels)>0
        if not valid or image.source not in {'FILE','GENERATED'}:
            row.update(status='skipped_unusable_disconnected',reason='undecodable or unsupported image source: '+image.source)
            if needed:raise RuntimeError('实际参与渲染的贴图无法解码/打包: '+image.name)
            result.append(row);continue
        if path and Path(path).is_file():row['source_file_sha256']=file_hash(path)
        if not image.packed_file:
            try:image.pack()
            except RuntimeError as exc:raise RuntimeError('有效保留贴图打包失败: '+image.name) from exc
        row['packed_sha256']=_packed_hashes(image)
        if not row['packed_sha256']:raise RuntimeError('有效保留贴图没有实际打包数据: '+image.name)
        row['status']='packed_retained';result.append(row)
    return result


def verify_retained_images(records):
    """Verify saved bytes even for currently hidden/disconnected retained images."""
    import bpy
    for record in records:
        if record['status']!='packed_retained':continue
        image=bpy.data.images.get(record['name'])
        if image is None or _packed_hashes(image)!=record['packed_sha256']:
            raise RuntimeError('保留源贴图丢失或打包字节已修改，请文件回退: '+record['name'])


def material_dependencies(parts, *, include_hidden=False):
    """Current render dependencies, or every retained part when explicitly asked."""
    materials, geometry = {}, {}
    def visit_geometry(tree):
        key=tree.as_pointer()
        if key in geometry:return
        geometry[key]=tree
        for node in tree.nodes:
            if node.bl_idname=='NodeUndefined':raise RuntimeError('存在无法识别的Goo几何节点')
            for socket in node.inputs:
                value=getattr(socket,'default_value',None)
                if getattr(value,'bl_rna',None) and value.bl_rna.identifier=='Material':
                    materials[value.as_pointer()]=value
            child=getattr(node,'node_tree',None)
            if child is not None:visit_geometry(child)
    for ob in parts.values():
        if ob.hide_render and not include_hidden:continue
        for mat in ob.data.materials:
            if mat is not None:materials[mat.as_pointer()]=mat
        for mod in ob.modifiers:
            if mod.type=='NODES' and mod.node_group and mod.node_group.get('zzz_owner'):
                visit_geometry(mod.node_group)
    return list(materials.values()),list(geometry.values())


def active_images(parts):
    """Walk only sockets that contribute to Surface/AOVs, across group boundaries.

    Unlike 'all linked texture nodes', native unused Toon/Sphere branches must not
    require old PMX assets when only native Diffuse/Alpha inputs are now exposed.
    """
    materials,_=material_dependencies(parts)
    images={};seen=set()
    def identifier_index(collection,socket):
        return list(collection).index(socket)
    def enter_aovs(tree,stack):
        for node in tree.nodes:
            if node.type=='OUTPUT_AOV':
                for socket in node.inputs:walk_input(tree,socket,stack)
    # `socket.links` scans every link of the tree on each access (quadratic on big
    # trees). Index each tree's links once; the result order is the same.
    link_index={}
    def incoming(tree,socket):
        table=link_index.get(tree.as_pointer())
        if table is None:
            table={}
            for link in tree.links:
                table.setdefault(link.to_socket.as_pointer(),[]).append(link)
            link_index[tree.as_pointer()]=table
        return table.get(socket.as_pointer(),())
    def walk_input(tree,socket,stack):
        for link in incoming(tree,socket):walk_output(tree,link.from_socket,stack)
    def walk_output(tree,socket,stack):
        key=(tree.as_pointer(),socket.as_pointer(),tuple(n.as_pointer() for t,n in stack))
        if key in seen:return
        seen.add(key);node=socket.node
        if node.bl_idname=='NodeUndefined':raise RuntimeError('存在无法识别的Goo着色节点')
        im=getattr(node,'image',None)
        if im is not None:images[im.as_pointer()]=im
        if node.type=='GROUP' and node.node_tree:
            child=node.node_tree
            output=next((n for n in child.nodes if n.type=='GROUP_OUTPUT' and n.is_active_output),None)
            if output is None:raise RuntimeError('着色组缺少活动输出: '+child.name)
            index=identifier_index(node.outputs,socket)
            if index>=len(output.inputs):raise RuntimeError('着色组接口不匹配: '+child.name)
            walk_input(child,output.inputs[index],stack+[(tree,node)])
            enter_aovs(child,stack+[(tree,node)])
            return
        if node.type=='GROUP_INPUT':
            if stack:
                parent,instance=stack[-1]
                index=identifier_index(node.outputs,socket)
                if index<len(instance.inputs):walk_input(parent,instance.inputs[index],stack[:-1])
            return
        for inp in node.inputs:walk_input(tree,inp,stack)
    for mat in materials:
        if not mat.use_nodes or not mat.node_tree:continue
        tree=mat.node_tree
        for node in tree.nodes:
            if node.type=='OUTPUT_MATERIAL' and node.is_active_output:
                walk_input(tree,node.inputs['Surface'],[])
                walk_input(tree,node.inputs['Displacement'],[])
        enter_aovs(tree,[])
    return list(images.values())
