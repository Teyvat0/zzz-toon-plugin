"""Self-contained Goo 4.4 material backend for 仿ZZZ渲染.

The caller supplies appended, authorized algorithm groups through ``configure``.
This module only creates NEW material/image datablocks. It never changes the
supplied groups, meshes, UVs, weights, collections, lighting, view layers or
compositor. Those dependencies, profile state overrides and independent outline
palettes belong to the workflow. No model, resource path or .blend asset is bundled.

Typed RGB values are converted from extended sRGB once; alpha and data vectors
are not gamma converted. Body D.alpha is NOT promoted to opacity. The rendering
limits in the returned diagnostics are part of this backend's public contract.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
import math
from pathlib import Path

import bpy

from . import resources, toon_outline, toon_surface


BACKEND_VERSION = "0.1.0"
DOMAIN_SOCKET = "1: Face, 2: Eye, 3: Body"
ROLES = frozenset((
    "face", "body", "hair", "wing", "eye", "eyebrow", "eye_shadow",
    "eye_shadow_texture", "eye_highlight", "mouth",
))
ROLE_DOMAIN = {
    "face": 1, "body": 3, "hair": 3, "wing": 3,
    "eye": 2, "eyebrow": 2, "eye_shadow": 2,
    "eye_shadow_texture": 2, "eye_highlight": 2, "mouth": 2,
}
_BODY_ROLES = frozenset(("body", "hair", "wing"))
_EYE_AOV_ROLES = frozenset((
    "eye", "eye_shadow", "eye_shadow_texture", "eye_highlight",
))
_OPAQUE_DOUBLE_ROLES = frozenset(("eye", "mouth"))
_BLEND_DOUBLE_ROLES = frozenset((
    "eyebrow", "eye_shadow", "eye_shadow_texture", "eye_highlight",
))
_GROUP_KEYS = ()
_TEXTURE_INPUTS = frozenset((
    "MainTex", "MainAlpha", "LightTex", "LightAlpha", "OtherDataTex",
    "OtherDataAlpha", "OtherDataTex2", "OtherDataAlpha2",
))
_CONFIG = None
_GROUPS = {}
_CATALOG = {}
_TEXTURE_INDEX = None
_IMAGE_CACHE = {}


def _suffix(index):
    return str(index) if index > 1 else ""


def _interface_names(group, direction):
    return {
        item.name for item in group.interface.items_tree
        if getattr(item, "item_type", "") == "SOCKET"
        and getattr(item, "in_out", "") == direction
    }


def _validate_groups(groups):
    if not isinstance(groups, Mapping):
        raise TypeError("groups must map explicit algorithm keys to appended node groups")
    # The shading groups (ZZZ_Toon_*) are built by toon_surface, so no template group is required.
    chosen = {}
    return chosen


def configure(resource_root: str, groups: dict[str, bpy.types.NodeTree], owner: str):
    """Reset per-run caches and bind resources plus the (now empty) group map.

    Accept a resource root or its Materials directory through resources' own
    normalization API. No existing datablock is removed or repurposed. A failed
    configuration disarms the backend rather than keeping an earlier character's
    resource cache. Call once per workflow run; workflow owns idempotence.
    """
    global _CONFIG, _GROUPS, _CATALOG, _TEXTURE_INDEX, _IMAGE_CACHE
    _CONFIG = None
    _GROUPS = {}
    _CATALOG = {}
    _TEXTURE_INDEX = None
    _IMAGE_CACHE = {}
    if tuple(bpy.app.version[:2]) != (4, 4):
        raise RuntimeError("仿ZZZ渲染 material backend requires Blender 4.4 Goo")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("owner must be a non-empty workflow ownership token")
    chosen = _validate_groups(groups)
    root = Path(resources.normalize_root(resource_root)).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Resource directory does not exist: {root}")
    catalog = {}
    folded = {}
    resolved_catalog = resources.resolve_catalog(str(root))
    for md in resolved_catalog['materials']:
        stem = str(md.stem)
        if stem.casefold() in folded:
            raise ValueError(
                f"Ambiguous material JSON stem {stem!r}: "
                f"{folded[stem.casefold()]} and {md.path}"
            )
        folded[stem.casefold()] = str(md.path)
        catalog[stem] = md
    if not catalog:
        raise ValueError(f"No material JSON catalog entries found in: {root}")
    index = resources.TextureIndex()
    index.add_dir(str(root))
    _CONFIG = {"resource_root": str(root), "owner": owner, "version": BACKEND_VERSION}
    _GROUPS, _CATALOG, _TEXTURE_INDEX = chosen, catalog, index
    return {
        **_CONFIG,
        "catalog_count": len(catalog),
        "groups": {key: group.name for key, group in chosen.items()},
    }


def _material_data(stem):
    if _CONFIG is None:
        raise RuntimeError("Call materials.configure(resource_root, groups, owner) first")
    if not isinstance(stem, str):
        raise TypeError("resource_stem must be an explicit JSON stem")
    if stem.lower().endswith(".json"):
        stem = stem[:-5]
    if not stem or stem in (".", "..") or any(c in stem for c in ("/", "\\", ":")):
        raise ValueError("resource_stem must be an explicit JSON stem, not a path")
    md = _CATALOG.get(stem)
    if md is None:
        raise KeyError(f"Material JSON stem not present in configured catalog: {stem!r}")
    return md


def _finite(value, label):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite {label}")
    return number


def _srgb_component(value):
    number = _finite(value, "color component")
    # Extended sRGB: do not clip HDR or negative RGB. Alpha never passes here.
    return number / 12.92 if number <= 0.04045 else ((number + 0.055) / 1.055) ** 2.4


def _color(value):
    values = tuple(value)
    if len(values) not in (3, 4):
        raise ValueError("Typed RGB color must contain 3 or 4 components")
    return tuple(_srgb_component(x) for x in values[:3]) + (
        _finite(values[3], "color alpha") if len(values) == 4 else 1.0,
    )


def _plain(value):
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    return [float(x) for x in value]


def _set(node, socket_name, value, diagnostics, source="manual"):
    socket = node.inputs.get(socket_name)
    if socket is None:
        raise KeyError(f"{node.node_tree.name} is missing input {socket_name!r}")
    kind = socket.type
    if kind == "BOOLEAN":
        value = bool(_finite(value, socket_name))
    elif kind == "INT":
        value = int(round(_finite(value, socket_name)))
    elif kind == "VALUE":
        value = _finite(value, socket_name)
    elif kind in ("RGBA", "VECTOR"):
        values = tuple(_finite(x, socket_name) for x in value)
        expected = 4 if kind == "RGBA" else 3
        # Unity serializes data vectors in m_Colors as four components. Retain
        # XYZ without applying a color transform; W is not a vector socket input.
        if kind == "VECTOR" and len(values) == 4:
            values = values[:3]
        if len(values) != expected:
            raise ValueError(f"{socket_name}: expected {expected} components, got {len(values)}")
        value = values
    else:
        raise TypeError(f"Unsupported parameter socket type {kind!r}: {socket_name}")
    socket.default_value = value
    diagnostics["parameters"][node.name + "." + socket_name] = {
        "source": source, "value": _plain(socket.default_value),
    }



def _uv(tree, location=(-1200, 0)):
    node = tree.nodes.new("ShaderNodeUVMap")
    node.uv_map = "UVMap"
    node.name = "ZZZ UVMap"
    node.location = location
    return node.outputs["UV"]


def _resolve_texture(md, key, *, required=False):
    reference = md.textures.get(key)
    if not reference:
        if required:
            raise KeyError(f"{md.stem}: required texture property {key} is empty")
        return None
    # TextureIndex.find intentionally raises on ambiguity. Never choose a
    # similarly named atlas or silently keep another character's texture.
    path = _TEXTURE_INDEX.find(reference)
    if path is None or not Path(path).is_file():
        raise FileNotFoundError(f"{md.stem} {key}: {reference}")
    return str(Path(path).resolve())


def _preflight_paths(md, role):
    required = {"_MainTex"} if role != "eye_shadow" else set()
    if role in _BODY_ROLES:
        required.update(("_LightTex", "_OtherDataTex", "_OtherDataTex2"))
    elif role == "face":
        required.add("_LightTex")
    used = set(required)
    if role in _BODY_ROLES:
        used.update("_MatCapTex" + _suffix(i) for i in range(1, 6))
    paths = {key: _resolve_texture(md, key, required=key in required) for key in sorted(used)}
    # Record all remaining exact references without loading unused textures.
    # Missing/ambiguous referenced assets fail before new datablocks are made.
    unused = {
        key: {"reference": ref, "path": _resolve_texture(md, key)}
        for key, ref in md.textures.items() if key not in used
    }
    return paths, unused


def _tag(datablock):
    datablock["zzz_owned"] = True
    datablock["zzz_owner"] = _CONFIG["owner"]
    datablock["zzz_material_backend_version"] = BACKEND_VERSION


def _cached_image(path, colorspace, new_images):
    key = (path.casefold(), colorspace, "CHANNEL_PACKED")
    image = _IMAGE_CACHE.get(key)
    try:
        valid = image is not None and bpy.data.images.get(image.name) == image
    except ReferenceError:
        valid = False
    if not valid:
        # Never change color space/alpha of a user image through path
        # reuse. Only this run's NEW images may be shared between NEW materials.
        image = bpy.data.images.load(path, check_existing=False)
        new_images.append(image)
        image.name = "ZZZ::" + Path(path).name
        image.colorspace_settings.name = colorspace
        image.alpha_mode = "CHANNEL_PACKED"
        _tag(image)
        image["zzz_source_path"] = path
        image["zzz_resource_root"] = _CONFIG["resource_root"]
        _IMAGE_CACHE[key] = image
    return image


def _texture(tree, md, key, colorspace, uv, diagnostics, paths, new_images, location):
    path = paths.get(key)
    if path is None:
        return None
    image = _cached_image(path, colorspace, new_images)
    node = tree.nodes.new("ShaderNodeTexImage")
    node.name = key
    node.label = f"{key}: {md.textures[key]}"
    node.image = image
    node.interpolation = "Linear"
    node.extension = "REPEAT"
    node.location = location
    if uv is not None:
        tree.links.new(uv, node.inputs["Vector"])
    diagnostics["images"].append({
        "property": key, "reference": md.textures[key], "path": path,
        "image": image.name, "colorspace": colorspace,
        "alpha_mode": image.alpha_mode, "node": node.name,
        "owner": _CONFIG["owner"],
    })
    return node


def _core_params(md, diagnostics):
    """JSON overrides for the ZZZ_Toon parameters (key = "_" + name), else the defaults."""
    p = dict(toon_surface.DEFAULTS)
    for name, default in toon_surface.DEFAULTS.items():
        key = "_" + name
        value = md.get(key)
        if value is None:
            continue
        if name in toon_surface.COLORS:
            value = _color(value)
        elif isinstance(default, int):
            value = int(round(_finite(value, name)))
        else:
            value = _finite(value, name)
        p[name] = value
        diagnostics["parameters"]["ZZZ_Toon." + name] = {"source": key, "value": _plain(value)}
    return p

def _states(surface, md, role, alpha, diagnostics):
    diagnostics["source_states"] = {
        key: value for key, value in md.floats.items()
        if any(token in key.lower() for token in (
            "blend", "cull", "doublesided", "zwrite", "ztest", "render",
            "usealpha", "alphaclip", "cutoff", "stencil",
        ))
    }
    cull, double = md.get("_Cull"), md.get("_DoubleSided")
    # Audited MMD/Goo raster policy: an explicit backface request is not
    # cancelled by the separate double-sided/UV-lighting flag. This is NOT a
    # claim that every original-game or third-party Unity pass uses _Cull.
    surface.use_backface_culling = resources.preview_backface_culling(md, role)
    transparent = (alpha < 1.0 or md.get("_DstBlend") not in (None, 0.0)
                   or md.get("_RenderType") == 2.0)
    method = ("CLIP" if (md.get("_AlphaClip") or 0) > 0.5
              else "BLEND" if transparent else "HASHED")
    if role in _OPAQUE_DOUBLE_ROLES:
        method = "OPAQUE"
        surface.use_backface_culling = False
    elif role in _BLEND_DOUBLE_ROLES:
        method = "BLEND"
        surface.use_backface_culling = False
    if not hasattr(surface, "blend_method"):
        raise RuntimeError("Goo legacy EEVEE Material.blend_method is required")
    surface.blend_method = method
    if md.get("_Cutoff") is not None:
        surface.alpha_threshold = _finite(md.get("_Cutoff"), "alpha cutoff")
    surface.use_screen_refraction = False
    if hasattr(surface, "use_transparent_shadow"):
        surface.use_transparent_shadow = True
    diagnostics["preview_states"] = {
        "blend_method": surface.blend_method,
        "backface_culling": surface.use_backface_culling,
        "shader_alpha": alpha, "domain": ROLE_DOMAIN[role],
    }
    if role in _OPAQUE_DOUBLE_ROLES:
        diagnostics["limits"].append(
            "Eye/mouth base layers use OPAQUE double-sided depth-tested Goo "
            "states; transparent sorting is reserved for decals. "
            "Workflow may apply a separately audited explicit profile state."
        )
    if cull == 1:
        diagnostics["limits"].append(
            "Unity front-face culling cannot be represented by Goo's backface "
            "boolean; this source state needs explicit winding inspection."
        )
    if role in _BODY_ROLES:
        diagnostics["limits"].append(
            "Domain 3 opacity is Alpha only: D.alpha is NOT body/wing/hair opacity. "
            "Hair D.alpha is used by Hair AOV; JSON blend flags do not rewire alpha."
        )
    if any(key in md.floats for key in ("_SrcBlend", "_DstBlend", "_ZWrite", "_StencilComp")):
        diagnostics["limits"].append(
            "Unity blend factors/depth-write/stencil are preserved as metadata. "
            "Goo blend_method is an approximation, not exact Unity render-state translation."
        )


def _aov(tree, name, *, value=None, source=None, location=(0, -400)):
    node = tree.nodes.new("ShaderNodeOutputAOV")
    node.name = name
    node.aov_name = name  # Node UI name alone does NOT select the render AOV.
    node.label = name + " AOV"
    node.location = location
    if source is None:
        node.inputs["Value"].default_value = float(value)
    else:
        tree.links.new(source, node.inputs["Value"])
    return node


def _discard_failed_build(materials, new_images):
    # Only datablocks created by this build are eligible. Earlier successful
    # materials and user images are never removed.
    for material in reversed(materials):
        if bpy.data.materials.get(material.name) == material:
            bpy.data.materials.remove(material, do_unlink=True)
    for image in reversed(new_images):
        if bpy.data.images.get(image.name) == image and image.users == 0:
            for key, cached in list(_IMAGE_CACHE.items()):
                if cached == image:
                    del _IMAGE_CACHE[key]
            bpy.data.images.remove(image)


def build_material(resource_stem: str, role: str = "body", name: str | None = None,
                   color_override=None, alpha_override=None, texture_overrides=None,
                   transparent=False) -> tuple[bpy.types.Material, bpy.types.Material, dict]:
    """Build a fresh surface/outline pair from an exact JSON stem and role.

    ``color_override`` is display sRGB RGB(A); alpha_override is linear [0, 1].
    Semantic roles are explicit, never inferred from a shared diffuse atlas.
    Surface nose/OutlineColor inputs are left independent of workflow's outline
    palette. This function does not create shell geometry or configure AOV layers.
    """
    role = str(role).lower()
    if role not in ROLES:
        raise ValueError(f"role must be one of {sorted(ROLES)}, got {role!r}")
    if name is not None and (not isinstance(name, str) or not name):
        raise ValueError("name must be a non-empty material label or None")
    import copy
    md = copy.copy(_material_data(resource_stem))
    md.textures = dict(md.textures)
    if texture_overrides:
        md.textures.update(texture_overrides)
    alpha = _finite(alpha_override, "alpha override") if alpha_override is not None else (
        0.4 if role == "eye_shadow" else 1.0
    )
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha_override must be finite and in [0, 1]")
    override = _color(color_override) if color_override is not None else None
    paths, unused = _preflight_paths(md, role)
    diagnostics = {
        "backend_version": BACKEND_VERSION, "owner": _CONFIG["owner"],
        "resource_root": _CONFIG["resource_root"], "resource_stem": md.stem,
        "resource_json": str(md.path), "role": role, "domain": ROLE_DOMAIN[role],
        "images": [], "parameters": {}, "packed_matcap_parameters": {}, "limits": [],
        "color_policy": "Typed RGB: one extended sRGB-to-linear conversion; alpha/data unchanged; HDR not clipped",
        "original_groups_modified": False, "old_texture_groups_used": False,
        "unimplemented_texture_properties": unused,
    }
    created, new_images = [], []
    try:
        surface = bpy.data.materials.new(name or f"ZZZ::{role}::{md.stem}")
        created.append(surface)
        surface.use_nodes = True
        tree = surface.node_tree
        tree.nodes.clear()
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        output.location = (600, 200)
        core, maps = toon_surface.nodes(tree, _CONFIG["owner"], output, 200, 200)
        p = _core_params(md, diagnostics)
        domain = ROLE_DOMAIN[role]
        _set(core, "Domain", domain, diagnostics, "explicit semantic role")
        if role == "eye_shadow":
            color, source = override or (0.0, 0.0, 0.0, 1.0), "textureless PMX eye shadow / caller converted override"
        elif override is not None:
            color, source = override, "caller sRGB color override"
        else:
            color, source = p["Color"], "JSON _Color / built-in default"
        diagnostics["parameters"]["ZZZ_Toon.Color"] = {"source": source, "value": _plain(color)}
        diagnostics["parameters"]["ZZZ_Toon.Alpha"] = {
            "source": "caller alpha override" if alpha_override is not None else "explicit role alpha",
            "value": alpha,
        }
        surface.diffuse_color = tuple(color[:3]) + (alpha,)
        _states(surface, md, role, alpha, diagnostics)
        uv = _uv(tree, (-1400, 100))
        main = _texture(tree, md, "_MainTex", "sRGB", uv, diagnostics, paths,
                        new_images, (-1100, 500))
        tex = {"main": None if role == "eye_shadow" else main,
               "light": None, "data": None, "data2": None}
        caps = []
        if role == "eye_shadow":
            diagnostics["limits"].append(
                "eye_shadow is a textureless black PMX overlay with default Alpha=0.4; "
                "use eye_shadow_texture for the distinct textured base-layer variant."
            )
        if role == "eye_shadow_texture":
            diagnostics["limits"].append(
                "Textured eye-shadow uses its exact JSON MainTex and atlas alpha in "
                "Domain 2, with the audited BLEND double-sided decal state and default Alpha=1."
            )
        if role == "mouth":
            diagnostics["limits"].append(
                "Mouth uses Domain 2 and the exact face atlas with OPAQUE double-sided "
                "state; tooth/tongue shading remains a preview approximation."
            )
        data_m = None
        if role in _BODY_ROLES:
            normal = _texture(tree, md, "_LightTex", "Non-Color", uv, diagnostics,
                              paths, new_images, (-1100, 100))
            data_m = _texture(tree, md, "_OtherDataTex", "Non-Color", uv, diagnostics,
                              paths, new_images, (-1100, -250))
            data_a = _texture(tree, md, "_OtherDataTex2", "Non-Color", uv, diagnostics,
                              paths, new_images, (-1100, -600))
            tex.update(light=normal, data=data_m, data2=data_a)
            matcap_on = md.get("_MatCap")
            for i in range(1, 6):
                suffix = _suffix(i)
                mc = _texture(tree, md, "_MatCapTex" + suffix, "sRGB", maps.outputs["MatCap UV"],
                              diagnostics, paths, new_images, (-700, -950 - i * 280))
                if mc is None:
                    continue
                burst = p["MatCapColorBurst" + suffix]
                tint = [c * burst for c in p["MatCapColorTint" + suffix][:3]]
                amount = 0.0 if matcap_on == 0.0 else p["MatCapAlphaBurst" + suffix]
                caps.append((i, mc, tint, amount, p["MatCapBlendMode" + suffix]))
        elif role == "face":
            face = _texture(tree, md, "_LightTex", "Non-Color", uv, diagnostics,
                            paths, new_images, (-1100, 100))
            mirror = tree.nodes.new("ShaderNodeVectorMath")
            mirror.name = "Face mirrored UV: 1-u, v"
            mirror.operation = "MULTIPLY_ADD"
            mirror.location = (-1400, -300)
            mirror.inputs[1].default_value = (-1.0, 1.0, 1.0)
            mirror.inputs[2].default_value = (1.0, 0.0, 0.0)
            tree.links.new(uv, mirror.inputs[0])
            mirrored = _texture(tree, md, "_LightTex", "Non-Color", mirror.outputs["Vector"],
                                diagnostics, paths, new_images, (-1100, -300))
            mirrored.name = "Face mirrored lightmap"
            tex.update(light=face, data=mirrored)
            diagnostics["limits"].append(
                "Face uses the JSON-referenced lightmap at UVMap and (1-u,v); "
                "matching face UV and HeadCenter/HeadForward/HeadRight are workflow dependencies."
            )
        transparent = bool(transparent) and role in _BODY_ROLES and role != "hair"
        toon_surface.wire(tree, core, maps, role, tex, p, color, alpha, caps, transparent=transparent)
        diagnostics["transparent"] = transparent
        if transparent:
            diagnostics["limits"].append(
                "Transparent slot: opacity = live material Alpha x painted D.alpha "
                "(Mix of Transparent BSDF and the toon surface, HASHED); no refraction."
            )
        if role == "hair":
            inv = tree.nodes.new("ShaderNodeMath")
            inv.name = "Hair visibility = 1 - D.alpha"
            inv.operation = "SUBTRACT"
            inv.inputs[0].default_value = 1.0
            inv.location = (-700, 650)
            tree.links.new(main.outputs["Alpha"], inv.inputs[1])
            _aov(tree, "Hair", source=inv.outputs[0], location=(-400, 700))
        if role in _EYE_AOV_ROLES:
            _aov(tree, "Eye", value=1.0, location=(500, -300))
        diagnostics["aov"] = {
            "Hair": "1-D.alpha" if role == "hair" else None,
            "Eye": 1.0 if role in _EYE_AOV_ROLES else None,
            "written_by_wrapper": ["Normal", "Rim", "Avatar"],
        }
        if "_EyeColorMap" in md.textures:
            diagnostics["limits"].append(
                "Eye_E / _EyeColorMap is recorded, not implemented by the ZZZ_Toon core; "
                "the preview uses the exact Face D."
            )
        if role == "wing" or "_TransmissionTexture" in md.textures:
            diagnostics["limits"].append(
                "Wing transmission is a preview approximation: _TransmissionTexture "
                "is NOT opacity and is not implemented as physical transmission."
            )
        if unused:
            diagnostics["limits"].append(
                "Unconnected texture properties are recorded explicitly; alternate "
                "emission/effect features are not inferred from similarly named textures."
            )
        outline = bpy.data.materials.new(surface.name + "::Outline")
        created.append(outline)
        outline.use_nodes = True
        ot = outline.node_tree
        ot.nodes.clear()
        out = ot.nodes.new("ShaderNodeOutputMaterial")
        out.location = (350, 0)
        outline_shader = ot.nodes.new("ShaderNodeGroup")
        outline_shader.node_tree = toon_outline.shader_group(_CONFIG["owner"])
        outline_shader.name, outline_shader.label, outline_shader.location = "OutlineShader", "ZZZ_Toon_Outline", (0, 0)
        outline_shader.width = 250
        _set(outline_shader, "Domain", domain, diagnostics, "same semantic role as surface")
        for i in range(1, 6):
            socket = "OutlineColor" + _suffix(i)
            _set(outline_shader, socket, tuple(p[socket]),
                 diagnostics, "already-converted source color; NO second gamma conversion")
        if data_m is not None:
            outline_uv = _uv(ot, (-650, 0))
            om = _texture(ot, md, "_OtherDataTex", "Non-Color", outline_uv,
                          diagnostics, paths, new_images, (-400, 0))
            ot.links.new(om.outputs["Color"], outline_shader.inputs["OtherDataTex"])
        else:
            _set(outline_shader, "OtherDataTex", (1.0, 0.0, 0.0, 1.0), diagnostics,
                 "non-body fixed material id 0; no accidental Face SDF as M")
        ot.links.new(outline_shader.outputs["Shader"], out.inputs["Surface"])
        outline.use_backface_culling = True
        outline.blend_method = "OPAQUE"
        outline.use_screen_refraction = False
        diagnostics["outline_policy"] = {
            "independent_palette_applied": False,
            "surface_nose_colors_unchanged": True,
            "algorithm_color_multiplier": 1.0,
            "responsibility": "Workflow ONLY applies independent display-sRGB palette to the outline instance as final linear colour (no gain); never to surface nose color.",
        }
        diagnostics["surface"], diagnostics["outline"] = surface.name, outline.name
        diagnostics["limits"].append(
            "Material pair only: source-style Solidify/GN shell, geometry attributes, "
            "Sun/head bindings and Eye-layer/AOV compositor must be configured by workflow."
        )
        for material in (surface, outline):
            _tag(material)
            material["resource_stem"] = md.stem
            material["preview_role"] = role
            material["source_json"] = str(md.path)
            material["source_states_json"] = json.dumps(
                diagnostics["source_states"], ensure_ascii=False, sort_keys=True,
            )
        surface["preview_limits_json"] = json.dumps(diagnostics["limits"], ensure_ascii=False)
        json.dumps(diagnostics, ensure_ascii=False, allow_nan=False)
        return surface, outline, diagnostics
    except Exception:
        _discard_failed_build(created, new_images)
        raise
