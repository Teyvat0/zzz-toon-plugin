"""TEST ONLY: component diagnostics for strict original-mesh persistence."""
import hashlib,json,struct
from pathlib import Path

def capture(parts, directory, label):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    rows={}
    def sha(data):return hashlib.sha256(data).hexdigest()
    for slot,ob in sorted(parts.items()):
        me=ob.data
        coords=b''.join(struct.pack('<3f',*v.co) for v in me.vertices)
        weights=json.dumps([sorted((ob.vertex_groups[g.group].name,float(g.weight)) for g in v.groups if ob.vertex_groups[g.group].name not in {'GN_Outline','OutlineMask'}) for v in me.vertices],ensure_ascii=False,separators=(',',':')).encode()
        polygons=b''.join(struct.pack('<%di'%len(p.vertices),*p.vertices)+struct.pack('<i',p.material_index) for p in me.polygons)
        # Diagnostic reads must not touch decoded corner_normals caches either.
        # Serialize authored signed-short2 and sharp masks, without normalization.
        normal_parts=[]
        for name,fmt in (('custom_normal','<2h'),('sharp_edge','<?'),('sharp_face','<?')):
            attribute=me.attributes.get(name)
            meta=None if attribute is None else (attribute.data_type,attribute.domain,len(attribute.data))
            header=json.dumps((name,meta),separators=(',',':')).encode('utf-8')
            normal_parts.append(struct.pack('<Q',len(header))+header)
            if attribute is not None:
                normal_parts.extend(struct.pack(fmt,*item.value) if fmt=='<2h' else struct.pack(fmt,item.value) for item in attribute.data)
        normals=b''.join(normal_parts)
        (directory/(label+'_'+str(slot)+'_authored_normals.bin')).write_bytes(normals)
        uvs={uv.name:sha(b''.join(struct.pack('<2f',*d.uv) for d in uv.data)) for uv in me.uv_layers}
        shapes={k.name:sha(b''.join(struct.pack('<3f',*v.co) for v in k.data)) for k in me.shape_keys.key_blocks} if me.shape_keys else {}
        rows[str(slot)]={'name':ob.name,'mesh':me.name,'coords':sha(coords),'weights':sha(weights),'polygons':sha(polygons),'normals':sha(normals),'uvs':uvs,'shapes':shapes,'custom_normals':bool(me.has_custom_normals),'vertices':len(me.vertices),'corners':len(me.loops)}
    (directory/(label+'.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    return rows
