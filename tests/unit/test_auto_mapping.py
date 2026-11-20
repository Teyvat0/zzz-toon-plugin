"""Required-resource matcher regressions, using only stdlib and in-memory doubles.

Run from the repository root with::

    python -B -m unittest discover -s tests/unit -p test_auto_mapping.py

No Blender process, image decoder, temporary file, bundled game asset, or add-on
registration is involved. The real resources parser/index/resolver is exercised
against a read-only virtual filesystem. Fake bpy implements only image loading,
copy/scale/removal and exact corner/weight/ShapeKey/native-Morph evidence read by
the matcher. They test proof logic, not Blender's actual UV/normal/deformation
implementation, resampling, color management, original MME effects or rendering.
Regression assertions include previously confirmed matcher defects; none rely
on obsolete no-JSON fallback behavior.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


_PACKAGE = "_zzz_required_mapping_unittest"
_SOURCE = Path(__file__).resolve().parents[2] / "zzz_mmd_toon"
package = types.ModuleType(_PACKAGE)
package.__path__ = [str(_SOURCE)]
sys.modules[_PACKAGE] = package
# Bypass bpy-dependent add-on registration and optional .pyc generation.
for _module_name in ("resources", "auto_mapping"):
    _full_name = _PACKAGE + "." + _module_name
    _spec = importlib.util.spec_from_file_location(_full_name, _SOURCE / (_module_name + ".py"))
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _module
    _path = _SOURCE / (_module_name + ".py")
    exec(compile(_path.read_text(encoding="utf-8"), str(_path), "exec"), _module.__dict__)
    setattr(package, _module_name, _module)

mapping = sys.modules[_PACKAGE + ".auto_mapping"]
resources = sys.modules[_PACKAGE + ".resources"]


class FakeImage:
    """Deterministic RGBA thumbnail source; never decodes an actual image."""

    def __init__(self, name, rgb=(0.2, 0.4, 0.6), *, size=(64, 64), alpha=1.0,
                 filepath="", collection=None):
        self.name = name
        self.filepath = self.filepath_raw = filepath
        self.library = None
        self.source = "FILE"
        self.size = tuple(size)
        self.rgb = tuple(rgb)
        self.alpha = alpha
        self.colorspace_settings = types.SimpleNamespace(name="sRGB")
        self.collection = collection
        self.scale_calls = []
        self.copy_count = 0
        self.is_copy = False

    def as_pointer(self):
        return id(self)

    @property
    def pixels(self):
        return list((*self.rgb, self.alpha)) * (self.size[0] * self.size[1])

    def copy(self):
        self.copy_count += 1
        collection = self.collection or sys.modules["bpy"].data.images
        copied = FakeImage(self.name + ".copy", self.rgb, size=self.size,
                           alpha=self.alpha, filepath=self.filepath,
                           collection=collection)
        copied.is_copy = True
        collection.add(copied)
        return copied

    def scale(self, width, height):
        self.scale_calls.append((width, height))
        self.size = (width, height)


class FakeImageCollection:
    def __init__(self, specifications):
        self.specifications = specifications
        self.active = {}
        self.loaded = []
        self.copies = []
        self.removed = []

    def add(self, image):
        if image.name in self.active:
            raise AssertionError("Fake image name collision: " + image.name)
        self.active[image.name] = image
        image.collection = self
        if image.is_copy:
            self.copies.append(image)

    def load(self, path, *, check_existing):
        if check_existing is not False:
            raise AssertionError("Matcher may remove only freshly loaded candidates")
        spec = self.specifications.get(str(Path(path)))
        if spec is None:
            raise OSError("No synthetic pixels registered for " + str(path))
        image = FakeImage("candidate_%d" % len(self.loaded), filepath=str(path),
                          collection=self, **spec)
        self.add(image)
        self.loaded.append(image)
        return image

    def get(self, name):
        return self.active.get(name)

    def remove(self, image):
        if self.active.get(image.name) is not image:
            raise AssertionError("Matcher attempted to remove an unowned image")
        self.removed.append(image)
        del self.active[image.name]


class FakeMaterial:
    def __init__(self, name, image=None, *, alpha=1.0, name_j="", name_e="",
                 double_sided=False, edge=True):
        self.name = name
        self.use_backface_culling = False
        self.mmd_material = types.SimpleNamespace(
            name_j=name_j, name_e=name_e, alpha=alpha,
            is_double_sided=double_sided, enabled_toon_edge=edge)
        self.node_tree = types.SimpleNamespace(nodes={
            "mmd_base_tex": types.SimpleNamespace(image=image)})

    def as_pointer(self):
        return id(self)


def material(name, rgb=(0.2, 0.4, 0.6), *, image_name="PMX_renamed.png",
             size=(64, 64), image_alpha=1.0, **kwargs):
    source = None if rgb is None else FakeImage(image_name, rgb, size=size, alpha=image_alpha)
    return FakeMaterial(name, source, **kwargs)


def armature(count=0, *, material_morphs=(), uv_morphs=()):
    root = types.SimpleNamespace(mmd_type='ROOT', mmd_root=types.SimpleNamespace(
        material_morphs=list(material_morphs), uv_morphs=list(uv_morphs)))
    return types.SimpleNamespace(data=types.SimpleNamespace(bones=[None] * count), parent=root)


def env(name=None, *, path_id=101):
    texture = {"m_FileID": 3, "m_PathID": path_id, "IsNull": False}
    if name is not None:
        texture["Name"] = name
    return {"m_Texture": texture}


def dump(stem, main="Atlas.png", *, role="body", floats=None, textures=None):
    refs = {"_MainTex": env(main)} if main else {}
    if role in {"body", "hair", "wing"}:
        refs.update({"_LightTex": env("Light.png"),
                     "_OtherDataTex": env("Other.png"),
                     "_OtherDataTex2": env("Other2.png")})
    elif role == "face":
        refs["_LightTex"] = env("FaceLight.png")
    refs.update(textures or {})
    return {"m_Name": stem, "m_Shader": {"Name": "Toon"}, "m_SavedProperties": {
        "m_Floats": floats or {}, "m_Colors": {}, "m_TexEnvs": refs}}


def nameless(stem):
    return dump(stem, main="", role="unknown", textures={
        prop: env(path_id=900 + i) for i, prop in enumerate(
            ("_MainTex", "_LightTex", "_OtherDataTex", "_OtherDataTex2"))})


@contextmanager
def virtual_resources(documents=None, *, pixels=None, extra_files=None,
                      default_auxiliaries=True):
    """Use the real parser/index without creating directories, JSON or images."""
    root = Path(os.path.abspath("__required_mapping_read_only_resources__"))
    files = {}
    for name, value in (documents or {}).items():
        payload = value if isinstance(value, str) else json.dumps(value)
        files[root / "Materials" / name] = payload.encode("utf-8")
    names = {"Light.png", "Other.png", "Other2.png", "FaceLight.png"} if default_auxiliaries else set()
    names.update(pixels or {})
    for name in names:
        files[root / "Textures" / name] = b"virtual image, never decoded"
    for name, content in (extra_files or {}).items():
        files[root / name] = content
    directories = {root}
    for path in files:
        parent = path.parent
        while parent == root or root in parent.parents:
            directories.add(parent)
            if parent == root:
                break
            parent = parent.parent

    specifications = {}
    for name, spec in (pixels or {}).items():
        specifications[str(root / "Textures" / name)] = (
            {"rgb": spec} if not isinstance(spec, dict) else dict(spec))
    images = FakeImageCollection(specifications)
    bpy = types.SimpleNamespace(data=types.SimpleNamespace(images=images),
                                path=types.SimpleNamespace(abspath=lambda raw, **kwargs: raw))

    def fake_open(path, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError("Resource planning attempted a write: " + str(path))
        path = Path(path)
        if path not in files:
            raise FileNotFoundError(str(path))
        data = files[path]
        return io.BytesIO(data) if "b" in mode else io.StringIO(
            data.decode(kwargs.get("encoding", "utf-8")))

    def fake_walk(path, **kwargs):
        path = Path(path)
        for directory in sorted(directories, key=str):
            if directory != path and path not in directory.parents:
                continue
            child_dirs = [item.name for item in directories
                          if item != directory and item.parent == directory]
            file_names = [item.name for item in files if item.parent == directory]
            yield str(directory), sorted(child_dirs), sorted(file_names)

    def fake_rglob(path, pattern):
        if pattern != "*":
            raise AssertionError("Unexpected candidate discovery pattern " + pattern)
        return iter(sorted((p for p in files if path in p.parents), key=str))

    with ExitStack() as stack:
        stack.enter_context(patch.object(resources, "normalize_root", return_value=str(root)))
        stack.enter_context(patch.object(Path, "resolve", lambda self, *a, **kw: self))
        stack.enter_context(patch.object(Path, "is_file", lambda self: self in files))
        stack.enter_context(patch.object(Path, "rglob", fake_rglob))
        stack.enter_context(patch("builtins.open", fake_open))
        stack.enter_context(patch.object(resources.os, "walk", fake_walk))
        stack.enter_context(patch.dict(sys.modules, {"bpy": bpy}))
        yield types.SimpleNamespace(root=root, files=files, images=images, bpy=bpy)


class IdentityMatrix:
    def __matmul__(self, coordinate):
        return coordinate


TRIANGLE = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))


class FakeUVLayers(list):
    active_index = 0


def triangle_mesh(material_triangles, *, share_points=False, smooth=False, custom_normals=None):
    """Each item is (material, coordinates[, corner UVs]); full proof inputs.

    Default flat triangles have separate points. share_points models the stronger
    same-source-point normal-fan witness; no fake world transform is evaluated.
    """
    materials, vertices, triangles, loops, edges, polygons, uv_data = [], [], [], [], [], [], []
    coordinate_ids = {}; edge_ids = {}
    for mat, coordinates, *uv in material_triangles:
        if mat not in materials:
            materials.append(mat)
        indices = []
        for co in coordinates:
            if not share_points or tuple(co) not in coordinate_ids:
                coordinate_ids[tuple(co)] = len(vertices)
                vertices.append(types.SimpleNamespace(co=tuple(co), groups=[]))
            indices.append(coordinate_ids[tuple(co)])
        first = len(loops)
        for n, vi in enumerate(indices):
            edge_key = tuple(sorted((vi, indices[(n + 1) % 3])))
            if edge_key not in edge_ids:
                edge_ids[edge_key] = len(edges)
                edges.append(types.SimpleNamespace(vertices=edge_key))
            loops.append(types.SimpleNamespace(vertex_index=vi, edge_index=edge_ids[edge_key]))
        lis = tuple(range(first, first + 3))
        polygons.append(types.SimpleNamespace(loop_indices=lis, use_smooth=smooth))
        triangles.append(types.SimpleNamespace(material_index=materials.index(mat),
                                               vertices=tuple(indices), loops=lis))
        uv_data.extend(types.SimpleNamespace(uv=tuple(q)) for q in
                       (uv[0] if uv else [(co[0], co[1]) for co in coordinates]))
    attributes = {}
    if custom_normals is not None:
        raw = custom_normals if isinstance(custom_normals, list) else [custom_normals] * len(loops)
        attributes['custom_normal'] = types.SimpleNamespace(data_type='INT16_2D', domain='CORNER',
            data=[types.SimpleNamespace(value=value) for value in raw])
    uv_layer = types.SimpleNamespace(name='UVMap', active_render=True, data=uv_data)
    mesh = types.SimpleNamespace(materials=materials, vertices=vertices, edges=edges, loops=loops,
        polygons=polygons, attributes=attributes, has_custom_normals=custom_normals is not None,
        uv_layers=FakeUVLayers([uv_layer]), shape_keys=None, animation_data=None,
        loop_triangles=triangles, calc_loop_triangles=lambda: None)
    return types.SimpleNamespace(data=mesh, matrix_world=IdentityMatrix(), vertex_groups=[], modifiers=[])


class MappingTestCase(unittest.TestCase):
    def assert_mapped(self, result, stems):
        self.assertEqual(result["errors"], [])
        self.assertIsNone(result["profile"])
        self.assertEqual([r["stem"] for r in result["rows"]], stems)
        self.assertTrue(all(r["backend"] == "GAME_JSON" for r in result["rows"]))
        self.assertEqual(result["summary"], {"materials": len(stems), "mapped": len(stems), "unresolved": 0})
        json.dumps(result)

    def assert_unresolved(self, result, slot=0):
        self.assertTrue(result["errors"])
        self.assertEqual(result["rows"][slot]["stem"], "")
        self.assertEqual(result["rows"][slot]["unresolved_reason"], "无法唯一关联材质JSON/atlas/state")
        self.assertTrue(any("%02d " % slot in value for value in result["errors"]))
        self.assertFalse(any(r["backend"] == "PMX_TOON" for r in result["rows"]))

    def body_plan(self, *, source_rgb=(0.2, 0.4, 0.6), candidate_rgb=(0.2, 0.4, 0.6),
                  source_size=(64, 64), candidate_size=(64, 64), extra_pixels=None,
                  name="Body"):
        pixels = {"Atlas.png": {"rgb": candidate_rgb, "size": candidate_size}}
        pixels.update(extra_pixels or {})
        with virtual_resources({"MAT_Unknown_Body.json": dump("MAT_Unknown_Body")}, pixels=pixels) as v:
            return mapping.plan([material(name, source_rgb, size=source_size)], [], armature(), v.root)


class RequiredResourceTests(MappingTestCase):
    def test_missing_resource_directory_is_error_not_no_json_fallback(self):
        for value in ("", None, "   "):
            with self.subTest(value=value):
                result = mapping.plan([material("Body")], [], armature(), value)
                self.assertTrue(any("必须选择" in error for error in result["errors"]))
                self.assertEqual(result["rows"], [])
                self.assertEqual(result["catalog"], [])
                self.assertEqual(result["resource_dir"], "")

    def test_invalid_resource_directory_reports_exception(self):
        with patch.object(resources, "normalize_root", side_effect=FileNotFoundError("missing-folder")):
            result = mapping.plan([material("Body")], [], armature(), "missing-folder")
        self.assertEqual(result["rows"], [])
        self.assertTrue(any("资源目录无法解析" in error and "missing-folder" in error for error in result["errors"]))

    def test_empty_resource_catalog_is_error(self):
        with virtual_resources(default_auxiliaries=False) as v:
            result = mapping.plan([material("Body")], [], armature(), v.root)
        self.assertEqual(result["catalog"], [])
        self.assertEqual(result["rows"], [])
        self.assertTrue(any("没有可解析" in error for error in result["errors"]))

    def test_missing_required_texture_properties_leave_slot_unresolved(self):
        cases = (("Hair", "hair", "_OtherDataTex2"), ("Face", "face", "_LightTex"),
                 ("Eye", "eye", "_MainTex"))
        for name, role, prop in cases:
            with self.subTest(role=role, prop=prop):
                stem = "MAT_Unknown_" + name
                data = dump(stem, role=role)
                del data["m_SavedProperties"]["m_TexEnvs"][prop]
                with virtual_resources({stem + ".json": data}, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
                    result = mapping.plan([material(name)], [], armature(), v.root)
                self.assert_unresolved(result)
                self.assertIn(prop, result["catalog"][0]["unresolved"])
                self.assertFalse(result["catalog"][0]["unresolved"][prop]["optional"])

    def test_broken_explicit_main_reference_is_not_a_pixel_identity(self):
        data = dump("MAT_X_Body", main="Absent.png")
        with virtual_resources({"MAT_X_Body.json": data}, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material("Body")], [], armature(), v.root)
        self.assert_unresolved(result)
        self.assertIn("explicit Name was not found", result["catalog"][0]["unresolved"]["_MainTex"]["reason"])

    def test_ambiguous_explicit_texture_name_keeps_all_candidates(self):
        with virtual_resources({"MAT_X_Body.json": dump("MAT_X_Body")},
                               pixels={"a/Atlas.png": (0.2, 0.4, 0.6),
                                       "b/Atlas.png": (0.7, 0.6, 0.5)}) as v:
            result = mapping.plan([material("Body")], [], armature(), v.root)
        self.assert_unresolved(result)
        entry = result["catalog"][0]["unresolved"]["_MainTex"]
        self.assertEqual(len(entry["candidates"]), 2)
        self.assertEqual(entry["reason"], "explicit Name is ambiguous")

    def test_required_resources_not_character_or_bone_counts_choose_mapping(self):
        for prefix, count in (("Unseen_3109", 0), ("陌生代号", 1), ("A9Q", 10000)):
            stem = "MAT_" + prefix + "_Body"
            with self.subTest(prefix=prefix, count=count):
                with virtual_resources({stem + ".json": dump(stem)}, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
                    result = mapping.plan([material("任意皮肤")], [], armature(count), v.root)
                self.assert_mapped(result, [stem])
                self.assertEqual(result["original_bones"], count)
                self.assertEqual(result["rows"][0]["role"], "body")

    def test_catalog_errors_are_not_silently_dropped_when_another_json_maps(self):
        # Bad unselected JSON remains diagnostic, not a reason to drop valid slots.
        with virtual_resources({"Bad.json": "{invalid-json", "MAT_X_Body.json": dump("MAT_X_Body")},
                               pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            resolved = resources.resolve_catalog(v.root)
            self.assertTrue(any("invalid material JSON" in e for e in resolved["errors"]))
            result = mapping.plan([material("Body")], [], armature(), v.root)
        self.assert_mapped(result, ["MAT_X_Body"])
        self.assertTrue(any("invalid material JSON" in e and "Bad.json" in e
                            for e in result["warnings"]))

    def test_body_fallback_cannot_reaccept_its_own_incomplete_json(self):
        # A second compatibility pass must not bypass the required-map gate,
        # even when retrying the same body JSON rather than borrowing another.
        for prop in ("_LightTex", "_OtherDataTex", "_OtherDataTex2"):
            with self.subTest(prop=prop):
                data = dump("MAT_X_Body")
                del data["m_SavedProperties"]["m_TexEnvs"][prop]
                with virtual_resources({"MAT_X_Body.json": data}, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
                    result = mapping.plan([material("Body")], [], armature(), v.root)
                self.assert_unresolved(result)

    def test_borrowed_hair_parameters_still_require_complete_dnma(self):
        # Accessory fallback may borrow parameters only from complete resources.
        data = dump("MAT_X_Hair", role="hair")
        del data["m_SavedProperties"]["m_TexEnvs"]["_OtherDataTex2"]
        with virtual_resources({"MAT_X_Hair.json": data}, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material("发带")], [], armature(), v.root)
        self.assert_unresolved(result)


class SemanticDomainTests(MappingTestCase):
    def test_cn_jp_en_semantics_and_precedence(self):
        cases = {
            "Body": "body", "皮肤": "body", "衣服": "body", "未命名947": "body",
            "Face": "face", "顔": "face", "脸": "face", "臉": "face", "Ｆａｃｅ": "face",
            "Eye": "eye", "Eyes": "eye", "瞳": "eye", "虹彩": "eye", "白目": "eye",
            "眼白": "eye", "iris": "eye", "sclera": "eye", "Face_Eye": "eye",
            "眉": "eyebrow", "睫毛": "eyebrow", "二重": "eyebrow", "Brow": "eyebrow",
            "Eyelash": "eyebrow", "Decal": "eyebrow", "口线": "eyebrow",
            "EyeShadow": "eye_shadow", "目影": "eye_shadow", "眼影": "eye_shadow",
            "Eye_Highlight": "eye_highlight", "瞳ハイライト": "eye_highlight", "眼高光": "eye_highlight",
            "Mouth": "mouth", "口": "mouth", "舌": "mouth", "歯": "mouth", "Teeth": "mouth",
            "Hair": "hair", "前髪": "hair", "头发": "hair", "髮": "hair", "Bangs": "hair",
            "Wing": "wing", "羽翼": "wing", "翅膀": "wing", "Feather": "wing",
            "Hair_Accessory": "body", "Hairband": "body", "髪飾り": "body", "发带": "body",
        }
        for name, role in cases.items():
            with self.subTest(name=name):
                self.assertEqual(mapping.classify_name(name), role)

    def test_original_japanese_display_name_preserves_identity_and_drives_role(self):
        mat = material("Body_datablock", name_j="顔　", name_e="Hair")
        with virtual_resources({"MAT_X_Face.json": dump("MAT_X_Face", role="face")},
                               pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([mat], [], armature(), v.root)
        self.assert_mapped(result, ["MAT_X_Face"])
        self.assertEqual(result["material_names"], ["顔　"])
        self.assertEqual(result["rows"][0]["name"], "顔　")
        self.assertEqual(result["rows"][0]["role"], "face")
        self.assertEqual(mat.name, "Body_datablock")
        self.assertEqual(mat.mmd_material.name_j, "顔　")

    def test_shared_face_eye_brow_atlas_keeps_each_slot_and_json_identity(self):
        stems = ["MAT_Unseen_Face", "MAT_Unseen_Eye", "MAT_Unseen_Eyebrow"]
        docs = {stem + ".json": dump(stem, main="Shared.png", role=role)
                for stem, role in zip(stems, ("face", "eye", "eyebrow"))}
        mats = [material("脸"), material("瞳"), material("眉")]
        with virtual_resources(docs, pixels={"Shared.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan(mats, [], armature(), v.root)
        self.assert_mapped(result, stems)
        self.assertEqual(len(result["catalog"]), 3)
        self.assertEqual([r["role"] for r in result["rows"]], ["face", "eye", "eyebrow"])
        self.assertEqual([r["outline"] for r in result["rows"]], [0.30, 0.0, 0.0])
        self.assertEqual([r["slot"] for r in result["rows"]], [0, 1, 2])
        self.assertEqual(len({r["atlas_candidates"][0]["path"] for r in result["rows"]}), 1)
        result["rows"][0]["texture_overrides"]["test-only"] = "one row only"
        self.assertNotIn("test-only", result["rows"][1]["texture_overrides"])
        self.assertNotIn("test-only", result["rows"][2]["texture_overrides"])

    def test_shared_atlas_with_unknown_json_does_not_collapse_known_face_identity(self):
        docs = {"MAT_X_Face.json": dump("MAT_X_Face", role="face"),
                "opaque_947.json": dump("opaque_947")}
        with virtual_resources(docs, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material("顔")], [], armature(), v.root)
        self.assert_mapped(result, ["MAT_X_Face"])
        self.assertEqual(len(result["catalog"]), 2)

    def test_hairshadow_json_is_effect_not_hair_surface_even_on_same_atlas(self):
        docs = {"MAT_X_Hair.json": dump("MAT_X_Hair", role="hair"),
                "MAT_X_HairShadow.json": dump("MAT_X_HairShadow", role="hair")}
        with virtual_resources(docs, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            catalog = resources.resolve_catalog(v.root)
            roles = {md.stem: mapping._json_role(md) for md in catalog["materials"]}
            result = mapping.plan([material("前髪")], [], armature(), v.root)
        self.assertEqual(roles["MAT_X_HairShadow"], "hair_shadow")
        self.assert_mapped(result, ["MAT_X_Hair"])
        self.assertEqual(len(result["catalog"]), 2)

    def test_hairshadow_only_catalog_cannot_supply_hair_surface(self):
        with virtual_resources({"MAT_X_Hair_Shadow.json": dump("MAT_X_Hair_Shadow", role="hair")},
                               pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material("Hair")], [], armature(), v.root)
        self.assert_unresolved(result)

    def test_body_accessory_can_borrow_complete_hair_data_without_becoming_hair(self):
        with virtual_resources({"MAT_X_Hair.json": dump("MAT_X_Hair", role="hair")},
                               pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material("发带")], [], armature(), v.root)
        self.assert_mapped(result, ["MAT_X_Hair"])
        self.assertEqual(result["rows"][0]["role"], "body")
        self.assertTrue(any("保留身体域" in warning for warning in result["rows"][0]["warnings"]))

    def test_no_edge_face_patch_uses_eyebrow_domain_json(self):
        docs = {"MAT_X_Face.json": dump("MAT_X_Face", role="face"),
                "MAT_X_Eyebrow.json": dump("MAT_X_Eyebrow", role="eyebrow")}
        with virtual_resources(docs, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material("Face", edge=False)], [], armature(), v.root)
        self.assert_mapped(result, ["MAT_X_Eyebrow"])
        self.assertEqual(result["rows"][0]["role"], "eyebrow")
        self.assertTrue(any("小面片" in evidence for evidence in result["rows"][0]["evidence"]))

    def test_solid_eye_shadow_uses_eye_parameters_but_preserves_black_domain(self):
        with virtual_resources({"MAT_X_Eye.json": dump("MAT_X_Eye", role="eye")},
                               pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material("眼影", rgb=(0.0, 0.0, 0.0))], [], armature(), v.root)
        self.assert_mapped(result, ["MAT_X_Eye"])
        row = result["rows"][0]
        self.assertEqual(row["role"], "eye_shadow")
        self.assertEqual(row["color_override"], [0.0, 0.0, 0.0, 1.0])
        self.assertEqual(row["confidence"], 0.82)
        self.assertEqual(row["outline"], 0.0)

    def test_textured_eye_shadow_uses_independent_shadow_texture_domain(self):
        with virtual_resources({"MAT_X_Eye.json": dump("MAT_X_Eye", role="eye")},
                               pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material("EyeShadow")], [], armature(), v.root)
        self.assert_mapped(result, ["MAT_X_Eye"])
        self.assertEqual(result["rows"][0]["role"], "eye_shadow_texture")
        self.assertNotIn("color_override", result["rows"][0])

    def test_bare_chinese_eye_and_unseparated_eye_white_keep_eye_domain(self):
        # Common bare CN and unseparated EN tokens must keep their eye domain.
        for name in ("眼", "EyeWhite"):
            with self.subTest(name=name):
                self.assertEqual(mapping.classify_name(name), "eye")


class PixelAssociationTests(MappingTestCase):
    def test_pixels_not_filename_or_character_prefix_choose_atlas(self):
        docs = {"MAT_NeverSeen_Body.json": dump("MAT_NeverSeen_Body", "GameAtlas.png")}
        with virtual_resources(docs, pixels={"GameAtlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material("Body", image_name="completely_different_name.dds")], [], armature(), v.root)
        self.assert_mapped(result, ["MAT_NeverSeen_Body"])
        self.assertEqual(result["rows"][0]["atlas_candidates"][0]["distance"], 0.0)
        self.assertTrue(any("32px" in evidence for evidence in result["rows"][0]["evidence"]))

    def test_matching_filename_with_contradictory_pixels_is_rejected(self):
        result = self.body_plan(source_rgb=(0.9, 0.9, 0.9), candidate_rgb=(0.0, 0.0, 0.0))
        self.assert_unresolved(result)
        self.assertAlmostEqual(result["rows"][0]["atlas_candidates"][0]["distance"], 0.9)

    def test_unrelated_texture_node_never_substitutes_for_mmd_base_texture(self):
        mat = material("Body", rgb=None)
        mat.node_tree.nodes["Unrelated image"] = types.SimpleNamespace(image=FakeImage("Atlas.png"))
        with virtual_resources({"MAT_X_Body.json": dump("MAT_X_Body")}, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([mat], [], armature(), v.root)
        self.assert_unresolved(result)
        self.assertEqual(result["rows"][0]["atlas_candidates"], [])

    def test_thumbnail_copies_only_and_removes_all_temporary_images(self):
        mat = material("Body", size=(128, 128), image_alpha=0.1)
        source = mat.node_tree.nodes["mmd_base_tex"].image
        source_state = (source.size, source.rgb, source.alpha, source.colorspace_settings.name)
        mat_state = vars(mat.mmd_material).copy()
        with virtual_resources({"MAT_X_Body.json": dump("MAT_X_Body")}, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            v.images.add(source)
            result = mapping.plan([mat], [], armature(), v.root)
            self.assertIs(v.images.get(source.name), source)
            self.assertEqual(set(v.images.active), {source.name})
            self.assertTrue(v.images.copies)
            self.assertTrue(all(im.scale_calls == [(32, 32)] for im in v.images.copies))
            self.assertTrue(all(im in v.images.removed for im in v.images.loaded + v.images.copies))
        self.assert_mapped(result, ["MAT_X_Body"])
        self.assertEqual((source.size, source.rgb, source.alpha, source.colorspace_settings.name), source_state)
        self.assertEqual(source.scale_calls, [])
        self.assertEqual(vars(mat.mmd_material), mat_state)

    def test_alpha_channel_is_not_used_to_merge_or_reject_atlas_pixels(self):
        with virtual_resources({"MAT_X_Body.json": dump("MAT_X_Body")},
                               pixels={"Atlas.png": {"rgb": (0.2, 0.4, 0.6), "alpha": 0.0}}) as v:
            result = mapping.plan([material("Body", image_alpha=1.0)], [], armature(), v.root)
        self.assert_mapped(result, ["MAT_X_Body"])
        self.assertEqual(result["rows"][0]["atlas_candidates"][0]["distance"], 0.0)

    def test_aspect_ratio_mismatch_is_not_an_atlas_match(self):
        result = self.body_plan(source_size=(64, 64), candidate_size=(128, 64))
        self.assert_unresolved(result)
        self.assertEqual(result["rows"][0]["atlas_candidates"], [])
        self.assertTrue(math.isinf(mapping._distance(((64, 64), [0.0]), ((128, 64), [0.0]))))

    def test_strong_threshold_can_match_same_aspect_different_resolution(self):
        result = self.body_plan(source_rgb=(0.0, 0.0, 0.0), candidate_rgb=(0.05, 0.05, 0.05),
                                source_size=(64, 64), candidate_size=(128, 128))
        self.assert_mapped(result, ["MAT_Unknown_Body"])
        self.assertTrue(any("32px" in e for e in result["rows"][0]["evidence"]))

    def test_loose_threshold_requires_same_source_resolution_and_emits_warning(self):
        result = self.body_plan(source_rgb=(0.0, 0.0, 0.0), candidate_rgb=(0.2, 0.2, 0.2))
        self.assert_mapped(result, ["MAT_Unknown_Body"])
        row = result["rows"][0]
        self.assertTrue(any("loose-MAE" in e for e in row["evidence"]))
        self.assertTrue(any("低置信度" in w for w in row["warnings"]))
        resized = self.body_plan(source_rgb=(0.0, 0.0, 0.0), candidate_rgb=(0.2, 0.2, 0.2),
                                 candidate_size=(128, 128))
        self.assert_unresolved(resized)

    def test_loose_threshold_accepts_exact_quarter_mae(self):
        result = self.body_plan(source_rgb=(0.0, 0.0, 0.0), candidate_rgb=(0.25, 0.25, 0.25))
        self.assert_mapped(result, ["MAT_Unknown_Body"])
        self.assertEqual(result["rows"][0]["atlas_candidates"][0]["distance"], 0.25)
        self.assertTrue(any("loose-MAE" in e for e in result["rows"][0]["evidence"]))

    def test_loose_threshold_needs_a_separated_second_candidate(self):
        docs = {"MAT_X_Body_1.json": dump("MAT_X_Body_1", "One.png"),
                "MAT_X_Body_2.json": dump("MAT_X_Body_2", "Two.png")}
        for second_distance, should_map in ((0.125, False), (0.2, True)):
            with self.subTest(second_distance=second_distance):
                with virtual_resources(docs, pixels={"One.png": (0.1, 0.1, 0.1),
                                                     "Two.png": (second_distance,) * 3}) as v:
                    result = mapping.plan([material("Body", rgb=(0.0, 0.0, 0.0))], [], armature(), v.root)
                if should_map:
                    self.assert_mapped(result, ["MAT_X_Body_1"])
                else:
                    self.assert_unresolved(result)
                self.assertEqual(len(result["rows"][0]["atlas_candidates"]), 2)

    def test_outside_loose_threshold_stays_unresolved_with_distance_diagnostic(self):
        result = self.body_plan(source_rgb=(0.0, 0.0, 0.0), candidate_rgb=(0.251, 0.251, 0.251))
        self.assert_unresolved(result)
        self.assertAlmostEqual(result["rows"][0]["atlas_candidates"][0]["distance"], 0.251)

    def test_nonzero_atlas_tie_is_rejected_and_candidates_are_reported(self):
        docs = {"MAT_X_Body_1.json": dump("MAT_X_Body_1", "One.png"),
                "MAT_X_Body_2.json": dump("MAT_X_Body_2", "Two.png")}
        with virtual_resources(docs, pixels={"One.png": (0.1, 0.1, 0.1), "Two.png": (0.1, 0.1, 0.1)}) as v:
            result = mapping.plan([material("Body", rgb=(0.0, 0.0, 0.0))], [], armature(), v.root)
        self.assert_unresolved(result)
        candidates = result["rows"][0]["atlas_candidates"]
        self.assertEqual(len(candidates), 2)
        self.assertAlmostEqual(candidates[0]["distance"], candidates[1]["distance"])

    def test_separated_best_atlas_wins_and_uses_its_own_json(self):
        docs = {"MAT_X_Body_1.json": dump("MAT_X_Body_1", "One.png"),
                "MAT_X_Body_2.json": dump("MAT_X_Body_2", "Two.png")}
        with virtual_resources(docs, pixels={"One.png": (0.02, 0.02, 0.02), "Two.png": (0.08, 0.08, 0.08)}) as v:
            result = mapping.plan([material("Body", rgb=(0.0, 0.0, 0.0))], [], armature(), v.root)
        self.assert_mapped(result, ["MAT_X_Body_1"])
        self.assertEqual(len(result["catalog"]), 2)

    def test_two_zero_distance_atlases_are_ambiguous_not_lexicographic_first(self):
        # A ratio alone is not separation at zero: 0 >= 0 * 1.4 is true.
        docs = {"MAT_X_Body_1.json": dump("MAT_X_Body_1", "A.png"),
                "MAT_X_Body_2.json": dump("MAT_X_Body_2", "B.png")}
        with virtual_resources(docs, pixels={"A.png": (0.2, 0.4, 0.6), "B.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material("Body")], [], armature(), v.root)
        self.assertEqual([c["distance"] for c in result["rows"][0]["atlas_candidates"]], [0.0, 0.0])
        self.assert_unresolved(result)


class RenderStateTests(MappingTestCase):
    def test_same_atlas_opaque_and_transparent_states_keep_independent_jsons(self):
        stems = ["MAT_Unseen_Body", "MAT_Unseen_Body_T"]
        docs = {stems[0] + ".json": dump(stems[0]),
                stems[1] + ".json": dump(stems[1], floats={"_DstBlend": 10})}
        mats = [material("Body opaque"), material("Body 透明薄纱", alpha=0.25)]
        with virtual_resources(docs, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan(mats, [], armature(), v.root)
        self.assert_mapped(result, stems)
        self.assertEqual(len(result["catalog"]), 2)
        self.assertEqual([r["alpha"] for r in result["rows"]], [1.0, 0.25])
        self.assertEqual([r["sourceAlpha"] for r in result["rows"]], [1.0, 0.25])
        self.assertEqual([r["state"] for r in result["rows"]], ["AUTO", "AUTO"])

    def test_dstblend_transparency_does_not_require_t_suffix(self):
        docs = {"MAT_X_Body_Opaque.json": dump("MAT_X_Body_Opaque"),
                "MAT_X_Body_Sheer.json": dump("MAT_X_Body_Sheer", floats={"_DstBlend": 10})}
        with virtual_resources(docs, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material("Body transparent", alpha=0.5)], [], armature(), v.root)
        self.assert_mapped(result, ["MAT_X_Body_Sheer"])

    def test_equal_json_semantic_and_state_scores_are_not_arbitrarily_selected(self):
        docs = {"MAT_A_Body.json": dump("MAT_A_Body"), "MAT_B_Body.json": dump("MAT_B_Body")}
        with virtual_resources(docs, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material("Body")], [], armature(), v.root)
        self.assert_unresolved(result)
        self.assertEqual(len(result["catalog"]), 2)

    def test_small_double_sided_difference_does_not_override_state_ambiguity(self):
        docs = {"MAT_A_Body.json": dump("MAT_A_Body", floats={"_DoubleSided": 0}),
                "MAT_B_Body.json": dump("MAT_B_Body", floats={"_DoubleSided": 1})}
        with virtual_resources(docs, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material("Body", double_sided=True)], [], armature(), v.root)
        self.assert_unresolved(result)

    def test_transparent_state_not_inferred_only_from_shared_pixels(self):
        docs = {"MAT_X_Body.json": dump("MAT_X_Body"),
                "MAT_X_Body_T.json": dump("MAT_X_Body_T")}
        with virtual_resources(docs, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material("Body", alpha=1.0)], [], armature(), v.root)
        self.assert_mapped(result, ["MAT_X_Body"])
        self.assertEqual(len(result["catalog"]), 2)


class NamelessReferenceTests(MappingTestCase):
    def test_unique_structural_family_resolves_nameless_without_overrides(self):
        stem = "MAT_Arbitrary_Body_2_UI"
        family = "TotallyDifferentPrefix_Body_Map2"
        pixels = {family + "_" + channel + ".png": (0.2, 0.4, 0.6) for channel in "DNMA"}
        with virtual_resources({stem + ".json": nameless(stem)}, pixels=pixels) as v:
            result = mapping.plan([material("Body")], [], armature(), v.root)
        self.assert_mapped(result, [stem])
        row = result["rows"][0]
        self.assertEqual(row["texture_overrides"], {})
        self.assertEqual({r["method"] for r in row["resolution"].values()}, {"inferred"})
        self.assertEqual(set(row["resolution"]), set(resources._CHANNELS))

    def test_pmx_atlas_proof_can_override_unresolved_cross_role_dnma_family(self):
        # Resources alone cannot equate Hair PathIDs to a Body atlas. The matcher
        # supplies independent pixel evidence, then keeps the Hair domain.
        stem = "MAT_NoIdentity_Hair_T_UI"
        family = "AnotherPrefix_Body_Map2"
        pixels = {family + "_" + channel + ".png": (0.2, 0.4, 0.6) for channel in "DNMA"}
        with virtual_resources({stem + ".json": nameless(stem)}, pixels=pixels) as v:
            catalog = resources.resolve_catalog(v.root)
            self.assertEqual(catalog["materials"][0].textures, {})
            self.assertEqual(len(catalog["errors"]), 4)
            result = mapping.plan([material("Hair")], [], armature(), v.root)
        self.assert_mapped(result, [stem])
        row = result["rows"][0]
        self.assertEqual(row["role"], "hair")
        self.assertEqual(set(row["texture_overrides"]), set(resources._CHANNELS))
        self.assertTrue(all(Path(path).is_absolute() for path in row["texture_overrides"].values()))
        self.assertTrue(all(family in path for path in row["texture_overrides"].values()))
        self.assertEqual(set(row["unresolved"]), set(resources._CHANNELS))
        self.assertTrue(any("不是PathID原样还原" in w for w in row["warnings"]))

    def test_missing_nma_channel_does_not_turn_nameless_override_into_valid_mapping(self):
        stem = "MAT_X_Hair"
        pixels = {"Any_Body_Map2_" + channel + ".png": (0.2, 0.4, 0.6) for channel in "DNM"}
        with virtual_resources({stem + ".json": nameless(stem)}, pixels=pixels) as v:
            result = mapping.plan([material("Hair")], [], armature(), v.root)
        self.assert_unresolved(result)
        self.assertEqual(result["rows"][0]["texture_overrides"], {})

    def test_multiple_json_identities_cannot_be_collapsed_by_same_nameless_family(self):
        docs = {stem + ".json": nameless(stem) for stem in ("MAT_A_Hair", "MAT_B_Hair")}
        pixels = {"Any_Body_Map2_" + channel + ".png": (0.2, 0.4, 0.6) for channel in "DNMA"}
        with virtual_resources(docs, pixels=pixels) as v:
            result = mapping.plan([material("Hair")], [], armature(), v.root)
        self.assert_unresolved(result)
        self.assertEqual(len(result["catalog"]), 2)


class NullReferenceAndSpecialDomainTests(MappingTestCase):
    def test_textureless_json_cannot_claim_unrelated_atlas_as_missing_reference(self):
        docs = {'MAT_Unknown_Body.json': dump('MAT_Unknown_Body'),
                'MAT_Unknown_Horn.json': dump('MAT_Unknown_Horn', main='', role='unknown')}
        with virtual_resources(docs, pixels={'Atlas.png': (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material('Body')], [], armature(), v.root)
        self.assert_mapped(result, ['MAT_Unknown_Body'])
        self.assertEqual(result['rows'][0]['texture_overrides'], {})

    def test_textureless_json_alone_does_not_synthesize_a_dnma_binding(self):
        docs = {'MAT_Unknown_Horn.json': dump('MAT_Unknown_Horn', main='', role='unknown')}
        pixels = {'Unrelated_Body_Map1_' + c + '.png': (0.2, 0.4, 0.6) for c in 'DNMA'}
        with virtual_resources(docs, pixels=pixels) as v:
            result = mapping.plan([material('Body')], [], armature(), v.root)
        self.assert_unresolved(result)

    def test_no_image_eye_shadow_keeps_textureless_domain(self):
        with virtual_resources({'MAT_Unknown_Eye.json': dump('MAT_Unknown_Eye', role='eye')},
                               pixels={'Atlas.png': (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material('目影', rgb=None, alpha=0.4)], [], armature(), v.root)
        self.assert_mapped(result, ['MAT_Unknown_Eye'])
        row = result['rows'][0]
        self.assertEqual(row['role'], 'eye_shadow')
        self.assertEqual(row['color_override'], [0., 0., 0., 1.])
        self.assertEqual(row['alpha'], 0.4)

    def test_unique_wing_json_preserves_edited_source_and_labels_inference(self):
        docs = {'MAT_Unknown_Wings.json': dump('MAT_Unknown_Wings', role='wing')}
        with virtual_resources(docs, pixels={'Atlas.png': (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material('翅膀', rgb=(0.95, 0.95, 0.95))], [], armature(), v.root)
        self.assert_mapped(result, ['MAT_Unknown_Wings'])
        self.assertTrue(result['rows'][0]['preserve_source_texture'])
        self.assertTrue(any('INFERRED' in w for w in result['rows'][0]['warnings']))

    def test_two_wing_jsons_remain_unresolved_without_atlas_proof(self):
        docs = {s + '.json': dump(s, role='wing') for s in ('MAT_A_Wings', 'MAT_B_Wings')}
        with virtual_resources(docs, pixels={'Atlas.png': (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([material('翅膀', rgb=(0.95, 0.95, 0.95))], [], armature(), v.root)
        self.assert_unresolved(result)


class DuplicateOverlayTests(MappingTestCase):
    def test_unique_full_triangle_overlap_recovers_overlay_and_preserves_source(self):
        donor = material("Body")
        overlay = material("edited overlay", rgb=(0.95, 0.95, 0.95), alpha=0.3)
        mesh = triangle_mesh([(donor, TRIANGLE), (overlay, TRIANGLE[1:] + TRIANGLE[:1])])
        before_vertices = [v.co for v in mesh.data.vertices]
        before_indices = [t.material_index for t in mesh.data.loop_triangles]
        with virtual_resources({"MAT_X_Body.json": dump("MAT_X_Body")}, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([donor, overlay], [mesh], armature(), v.root)
        self.assert_mapped(result, ["MAT_X_Body", "MAT_X_Body"])
        row = result["rows"][1]
        self.assertTrue(row["preserve_source_texture"])
        self.assertFalse(result["rows"][0]["preserve_source_texture"])
        self.assertEqual((row["confidence"], row["alpha"], row["sourceAlpha"]), (0.90, 0.3, 0.3))
        self.assertTrue(any("100%精确" in evidence for evidence in row["evidence"]))
        self.assertNotIn("unresolved_reason", row)
        self.assertEqual([v.co for v in mesh.data.vertices], before_vertices)
        self.assertEqual([t.material_index for t in mesh.data.loop_triangles], before_indices)
        self.assertEqual(mesh.data.materials, [donor, overlay])

    def test_similar_color_or_shifted_triangle_without_overlap_is_not_proof(self):
        donor = material("Body")
        overlay = material("edited overlay", rgb=(0.95, 0.95, 0.95))
        shifted = tuple((x + 0.01, y, z) for x, y, z in TRIANGLE)
        mesh = triangle_mesh([(donor, TRIANGLE), (overlay, shifted)])
        with virtual_resources({"MAT_X_Body.json": dump("MAT_X_Body")}, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([donor, overlay], [mesh], armature(), v.root)
        self.assert_unresolved(result, 1)
        self.assertFalse(result["rows"][1]["preserve_source_texture"])

    def test_partial_triangle_overlap_does_not_meet_geometry_threshold(self):
        donor = material("Body")
        overlay = material("edited overlay", rgb=(0.95, 0.95, 0.95))
        shifted = tuple((x + 1.0, y + 1.0, z) for x, y, z in TRIANGLE)
        mesh = triangle_mesh([(donor, TRIANGLE), (overlay, TRIANGLE), (overlay, shifted)])
        with virtual_resources({"MAT_X_Body.json": dump("MAT_X_Body")}, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([donor, overlay], [mesh], armature(), v.root)
        self.assert_unresolved(result, 1)

    def test_two_overlapping_different_json_donors_are_ambiguous(self):
        donor_a = material("Body", rgb=(0.2, 0.4, 0.6))
        donor_b = material("Body", rgb=(0.7, 0.4, 0.1))
        overlay = material("edited overlay", rgb=(0.95, 0.95, 0.95))
        mesh = triangle_mesh([(donor_a, TRIANGLE), (donor_b, TRIANGLE), (overlay, TRIANGLE)])
        docs = {"MAT_X_Body_1.json": dump("MAT_X_Body_1", "A.png"),
                "MAT_X_Body_2.json": dump("MAT_X_Body_2", "B.png")}
        with virtual_resources(docs, pixels={"A.png": (0.2, 0.4, 0.6), "B.png": (0.7, 0.4, 0.1)}) as v:
            result = mapping.plan([donor_a, donor_b, overlay], [mesh], armature(), v.root)
        self.assertEqual([r["stem"] for r in result["rows"][:2]], ["MAT_X_Body_1", "MAT_X_Body_2"])
        self.assert_unresolved(result, 2)

    def test_two_donors_with_same_json_identity_still_prove_one_overlay_identity(self):
        donors = [material("Body"), material("Body section")]
        overlay = material("edited overlay", rgb=(0.95, 0.95, 0.95))
        mesh = triangle_mesh([(donors[0], TRIANGLE), (donors[1], TRIANGLE), (overlay, TRIANGLE)])
        with virtual_resources({"MAT_X_Body.json": dump("MAT_X_Body")}, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan(donors + [overlay], [mesh], armature(), v.root)
        self.assert_mapped(result, ["MAT_X_Body"] * 3)
        self.assertTrue(result["rows"][2]["preserve_source_texture"])

    def test_single_json_union_of_disjoint_material_sections_proves_overlay(self):
        donors = [material("Body"), material("Body section")]
        overlay = material("edited overlay", rgb=(0.95, 0.95, 0.95))
        shifted = tuple((x + 2.0, y, z) for x, y, z in TRIANGLE)
        mesh = triangle_mesh([(donors[0], TRIANGLE), (donors[1], shifted),
                              (overlay, TRIANGLE), (overlay, shifted)])
        with virtual_resources({"MAT_X_Body.json": dump("MAT_X_Body")}, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan(donors + [overlay], [mesh], armature(), v.root)
        self.assert_mapped(result, ["MAT_X_Body"] * 3)
        self.assertTrue(result["rows"][2]["preserve_source_texture"])

    def test_union_of_different_json_families_is_not_overlay_proof(self):
        donors = [material("Body", rgb=(0.2, 0.4, 0.6)), material("Body", rgb=(0.7, 0.4, 0.1))]
        overlay = material("edited overlay", rgb=(0.95, 0.95, 0.95))
        shifted = tuple((x + 2.0, y, z) for x, y, z in TRIANGLE)
        mesh = triangle_mesh([(donors[0], TRIANGLE), (donors[1], shifted),
                              (overlay, TRIANGLE), (overlay, shifted)])
        docs = {"MAT_X_Body_1.json": dump("MAT_X_Body_1", "A.png"),
                "MAT_X_Body_2.json": dump("MAT_X_Body_2", "B.png")}
        with virtual_resources(docs, pixels={"A.png": (0.2, 0.4, 0.6), "B.png": (0.7, 0.4, 0.1)}) as v:
            result = mapping.plan(donors + [overlay], [mesh], armature(), v.root)
        self.assert_unresolved(result, 2)

    def test_no_geometry_means_no_duplicate_overlay_recovery(self):
        donor = material("Body")
        overlay = material("edited overlay", rgb=(0.95, 0.95, 0.95))
        with virtual_resources({"MAT_X_Body.json": dump("MAT_X_Body")}, pixels={"Atlas.png": (0.2, 0.4, 0.6)}) as v:
            result = mapping.plan([donor, overlay], [], armature(), v.root)
        self.assert_unresolved(result, 1)


class ExactDuplicateSafetyTests(MappingTestCase):
    def effect_case(self, *, coordinates=TRIANGLE, donor_count=1, effect_count=1,
                    mutate=None, mesh_options=None, documents=None, arm=None, effect_name='Hair effect'):
        donor = material('Hair')
        effect = material(effect_name, rgb=(.95,.95,.95), image_alpha=.2)
        effect.mmd_material.sphere_texture_type = '2'
        effect.node_tree.nodes['mmd_sphere_tex'] = types.SimpleNamespace(image=FakeImage('sphere'))
        mesh = triangle_mesh([(donor,TRIANGLE)] * donor_count + [(effect,coordinates)] * effect_count,
                             **(mesh_options or {}))
        rig = armature() if arm is None else arm
        if mutate:
            mutate(mesh,donor,effect,rig)
        docs = documents or {'MAT_Any_Hair.json':dump('MAT_Any_Hair',role='hair')}
        with virtual_resources(docs,pixels={'Atlas.png':(.2,.4,.6)}) as v:
            return mapping.plan([donor,effect],[mesh],rig,v.root)

    def assert_kept(self,result):
        row=result['rows'][1]
        self.assertFalse(row['archive'])
        self.assertNotIn('effect_policy',row)
        self.assertNotIn('effect_evidence',row)
        return row

    def test_reversed_winding_never_recovers_or_hides(self):
        result=self.effect_case(coordinates=tuple(reversed(TRIANGLE)))
        self.assert_unresolved(result,1)
        self.assert_kept(result)

    def test_rounding_near_coincidence_never_recovers_or_hides(self):
        shifted=tuple((x+1e-8,y,z) for x,y,z in TRIANGLE)
        result=self.effect_case(coordinates=shifted)
        self.assert_unresolved(result,1)
        self.assert_kept(result)

    def test_one_unique_triangle_above_old_995_ratio_is_not_discarded(self):
        donor=material('Hair');effect=material('Hair effect',rgb=(.95,.95,.95),image_alpha=.2)
        effect.mmd_material.sphere_texture_type='2'
        effect.node_tree.nodes['mmd_sphere_tex']=types.SimpleNamespace(image=FakeImage('sphere'))
        coords=[tuple((x+i*2.,y,z) for x,y,z in TRIANGLE) for i in range(201)]
        mesh=triangle_mesh([(donor,c) for c in coords[:200]]+[(effect,c) for c in coords])
        self.assertGreater(200/201,.995)
        with virtual_resources({'MAT_Any_Hair.json':dump('MAT_Any_Hair',role='hair')},pixels={'Atlas.png':(.2,.4,.6)}) as v:
            result=mapping.plan([donor,effect],[mesh],armature(),v.root)
        self.assert_unresolved(result,1)
        self.assert_kept(result)

    def test_duplicate_triangle_multiplicity_is_not_a_position_set(self):
        result=self.effect_case(donor_count=1,effect_count=2)
        self.assert_unresolved(result,1)
        self.assert_kept(result)

    def test_equal_multiplicity_and_donor_surplus_remain_provable(self):
        for donor_count,effect_count in ((2,2),(2,1)):
            with self.subTest(donor_count=donor_count,effect_count=effect_count):
                row=self.effect_case(donor_count=donor_count,effect_count=effect_count)['rows'][1]
                self.assertEqual(row['effect_policy'],'MME_DUPLICATE_OFF')
                self.assertEqual(row['effect_evidence']['triangles'],effect_count)

    def test_all_uv_layers_participate_not_just_active_uv(self):
        def mutate(mesh,*_):
            uv=types.SimpleNamespace(name='UV2',active_render=False,
                data=[types.SimpleNamespace(uv=(0.,0.)) for _ in mesh.data.loops])
            uv.data[-1].uv=(.01,0.)
            mesh.data.uv_layers.append(uv)
        result=self.effect_case(mutate=mutate)
        self.assert_unresolved(result,1)
        self.assert_kept(result)

    def test_missing_uv_corner_does_not_drop_only_invalid_triangle(self):
        result=self.effect_case(mutate=lambda mesh,*_:mesh.data.uv_layers[0].data.pop())
        self.assert_unresolved(result,1)
        self.assertIn('incomplete UV corner data',result['rows'][1]['binding_evidence']['blockers'])

    def test_weight_difference_allows_data_binding_but_never_off(self):
        def mutate(mesh,*_):
            mesh.vertex_groups=[types.SimpleNamespace(name='bone')]
            for i,v in enumerate(mesh.data.vertices):
                v.groups=[types.SimpleNamespace(group=0,weight=1. if i<3 else .5)]
        result=self.effect_case(mutate=mutate)
        self.assert_mapped(result,['MAT_Any_Hair']*2)
        row=self.assert_kept(result)
        self.assertTrue(row['preserve_source_texture'])
        self.assertEqual(row['binding_evidence']['unmatched_triangles'],0)
        self.assertEqual(row['duplicate_evidence']['unmatched_triangles'],1)
        self.assertEqual(row['effect_diagnostic']['policy'],'PRESERVE')

    def test_shape_morph_or_sdef_coordinate_difference_prevents_off(self):
        for name in ('expression','mmd_sdef_c'):
            def mutate(mesh,*_):
                key=types.SimpleNamespace(name=name,relative_key=None,vertex_group='',interpolation='KEY_LINEAR',
                    frame=0.,mute=False,value=0.,slider_min=0.,slider_max=1.,
                    data=[types.SimpleNamespace(co=v.co) for v in mesh.data.vertices])
                key.data[-1].co=(0.,1.,.01)
                mesh.data.shape_keys=types.SimpleNamespace(use_relative=True,eval_time=0.,key_blocks=[key],animation_data=None)
            result=self.effect_case(mutate=mutate)
            self.assert_mapped(result,['MAT_Any_Hair']*2)
            self.assertEqual(self.assert_kept(result)['duplicate_evidence']['unmatched_triangles'],1)

    def test_vertex_group_uv_morph_difference_is_not_ignored(self):
        def mutate(mesh,*_):
            mesh.vertex_groups=[types.SimpleNamespace(name='UV_motion+X')]
            mesh.data.vertices[-1].groups=[types.SimpleNamespace(group=0,weight=.25)]
        rig=armature(uv_morphs=[types.SimpleNamespace(data_type='VERTEX_GROUP')])
        self.assert_kept(self.effect_case(mutate=mutate,arm=rig))

    def test_material_morph_target_or_all_material_id_preserves_layer(self):
        for target,numeric in (('effect',18),('donor',17),('all',-1),('missing',18)):
            def mutate(mesh,donor,effect,rig):
                offset=types.SimpleNamespace(material_data=effect if target=='effect' else donor if target=='donor' else None,
                                             material_id=numeric)
                rig.parent.mmd_root.material_morphs=[types.SimpleNamespace(name='visibility',data=[offset])]
            with self.subTest(target=target):
                row=self.assert_kept(self.effect_case(mutate=mutate))
                self.assertTrue(any('material Morph' in b for b in row['effect_diagnostic']['blockers']))

    def test_legacy_or_unknown_uv_morph_and_missing_metadata_fail_closed(self):
        for storage in ('DATA','UNKNOWN'):
            rig=armature(uv_morphs=[types.SimpleNamespace(data_type=storage)])
            self.assert_kept(self.effect_case(arm=rig))
        self.assert_kept(self.effect_case(arm=types.SimpleNamespace(data=types.SimpleNamespace(bones=[]))))

    def test_same_object_non_armature_modifier_or_mesh_driver_is_unproved(self):
        def modifier(mesh,*_):mesh.modifiers=[types.SimpleNamespace(type='NODES')]
        def driver(mesh,*_):mesh.data.animation_data=types.SimpleNamespace(drivers=['custom'])
        for mutate in (modifier,driver):
            result=self.effect_case(mutate=mutate)
            self.assert_mapped(result,['MAT_Any_Hair']*2)
            self.assert_kept(result)

    def test_custom_normals_shared_smooth_fan_or_flat_space_can_be_proved(self):
        for options in ({'custom_normals':(123,-456)},
                        {'custom_normals':(123,-456),'smooth':True,'share_points':True}):
            with self.subTest(options=options):
                row=self.effect_case(mesh_options=options)['rows'][1]
                self.assertEqual(row['effect_policy'],'MME_DUPLICATE_OFF')

    def test_custom_short2_difference_or_unproved_separate_smooth_fans_keep(self):
        for options in ({'custom_normals':[(123,-456)]*3+[(123,-455)]*3},
                        {'custom_normals':(123,-456),'smooth':True}):
            with self.subTest(options=options):
                result=self.effect_case(mesh_options=options)
                self.assert_mapped(result,['MAT_Any_Hair']*2)
                self.assert_kept(result)

    def test_readable_sphere_image_required_not_just_add_flag(self):
        def mutate(mesh,donor,effect,rig):effect.node_tree.nodes.pop('mmd_sphere_tex')
        row=self.assert_kept(self.effect_case(mutate=mutate))
        self.assertIn('no readable static native sphere source',row['effect_diagnostic']['blockers'])

    def test_complete_finite_alpha_not_sample_or_material_alpha(self):
        invalid=(types.SimpleNamespace(size=(2,1),pixels=[0.,0.,0.,.2],channels=4),
                 types.SimpleNamespace(size=(1,1),pixels=[0.,0.,0.,float('nan')],channels=4),
                 types.SimpleNamespace(size=(1,1),pixels=[0.,0.,0.,-.1],channels=4),
                 types.SimpleNamespace(size=(1,1),pixels=[0.,0.,0.,.2],channels=3))
        for image in invalid:
            image.source='FILE'
            with self.subTest(image=image):self.assertIsNone(mapping._alpha_range(image))

    def test_animated_base_or_sphere_source_never_uses_current_frame_as_proof(self):
        for node_name in ('mmd_base_tex','mmd_sphere_tex'):
            for source in ('MOVIE','SEQUENCE','TILED','VIEWER','FILE_WITH_DRIVER'):
                def mutate(mesh,donor,effect,rig):
                    image=effect.node_tree.nodes[node_name].image
                    image.source='FILE' if source=='FILE_WITH_DRIVER' else source
                    if source=='FILE_WITH_DRIVER':image.animation_data=types.SimpleNamespace(drivers=['pixels'])
                with self.subTest(node_name=node_name,source=source):
                    result=self.effect_case(mutate=mutate)
                    self.assert_mapped(result,['MAT_Any_Hair']*2)
                    row=self.assert_kept(result)
                    blockers=row['effect_diagnostic']['blockers']
                    if node_name=='mmd_base_tex':
                        self.assertIn('base source is not a static FILE/GENERATED image',blockers)
                    else:self.assertIn('no readable static native sphere source',blockers)

    def test_static_generated_base_and_sphere_remain_admissible(self):
        def mutate(mesh,donor,effect,rig):
            effect.node_tree.nodes['mmd_base_tex'].image.source='GENERATED'
            effect.node_tree.nodes['mmd_sphere_tex'].image.source='GENERATED'
        row=self.effect_case(mutate=mutate)['rows'][1]
        self.assertEqual(row['effect_policy'],'MME_DUPLICATE_OFF')
        self.assertTrue(row['effect_evidence']['static_source_images'])

    def test_donor_effect_double_sided_mismatch_or_missing_flag_keeps_effect(self):
        for donor_sides,effect_sides in ((False,True),(True,False),(None,False),(False,None)):
            def mutate(mesh,donor,effect,rig):
                donor.mmd_material.is_double_sided=donor_sides
                effect.mmd_material.is_double_sided=effect_sides
            with self.subTest(donor_sides=donor_sides,effect_sides=effect_sides):
                result=self.effect_case(mutate=mutate)
                self.assert_mapped(result,['MAT_Any_Hair']*2)
                row=self.assert_kept(result)
                self.assertIn('donor/effect double-sided coverage differs or is unavailable',row['effect_diagnostic']['blockers'])

    def test_equal_double_sided_and_final_raster_flags_remain_admissible(self):
        def mutate(mesh,donor,effect,rig):
            donor.mmd_material.is_double_sided=effect.mmd_material.is_double_sided=True
        docs={'MAT_Any_Hair.json':dump('MAT_Any_Hair',role='hair',floats={'_Cull':0,'_DoubleSided':1})}
        row=self.effect_case(mutate=mutate,documents=docs)['rows'][1]
        self.assertEqual(row['effect_policy'],'MME_DUPLICATE_OFF')
        self.assertTrue(row['effect_evidence']['donor_effect_sidedness_equal'])
        self.assertTrue(row['effect_evidence']['final_raster_culling_equal'])
        self.assertEqual(row['effect_evidence']['raster_coverage'],[{'donor_slot':0,'donor_backface_culling':False,'effect_backface_culling':False}])

    def test_native_double_equality_does_not_prove_final_cull2_coverage(self):
        def mutate(mesh,donor,effect,rig):
            donor.mmd_material.is_double_sided=effect.mmd_material.is_double_sided=True
        docs={'MAT_Any_Hair.json':dump('MAT_Any_Hair',role='hair',floats={'_Cull':2,'_DoubleSided':1})}
        result=self.effect_case(mutate=mutate,documents=docs)
        self.assert_mapped(result,['MAT_Any_Hair']*2)
        row=self.assert_kept(result)
        self.assertIn('final donor/effect raster culling differs or is unavailable',row['effect_diagnostic']['blockers'])

    def test_different_or_unavailable_native_culling_blocks_off(self):
        for donor_old,effect_old in ((True,False),(False,True),(None,False)):
            def mutate(mesh,donor,effect,rig):
                donor.mmd_material.is_double_sided=effect.mmd_material.is_double_sided=True
                donor.use_backface_culling=donor_old;effect.use_backface_culling=effect_old
            docs={'MAT_Any_Hair.json':dump('MAT_Any_Hair',role='hair',floats={'_Cull':0,'_DoubleSided':1})}
            with self.subTest(donor_old=donor_old,effect_old=effect_old):
                row=self.assert_kept(self.effect_case(mutate=mutate,documents=docs))
                self.assertIn('final donor/effect raster culling differs or is unavailable',row['effect_diagnostic']['blockers'])

    def test_transparent_twin_json_collapses_to_base_for_the_overlay_slot(self):
        # A base JSON and its `_T` twin with the same texture family are one surface:
        # the overlay binds to the base and the twin is never preferred.
        docs={'MAT_Any_Hair.json':dump('MAT_Any_Hair',role='hair'),
              'MAT_Any_Hair_T.json':dump('MAT_Any_Hair_T',role='hair',floats={'_DstBlend':10})}
        result=self.effect_case(documents=docs)
        self.assertEqual(result['rows'][0]['stem'],'MAT_Any_Hair')
        self.assertEqual(result['rows'][1]['stem'],'MAT_Any_Hair')
        self.assertEqual(result['rows'][1]['binding_evidence']['pre_ranking_families'],2)
        self.assertEqual(len(result['rows'][1]['binding_evidence']['candidate_families']),1)
        self.assertTrue(result['rows'][1]['preserve_source_texture'])

    def test_prefer_base_variant_keeps_unrelated_families(self):
        def fam(stem,key='k'):
            md=type('M',(),{'stem':stem})()
            return ((stem,(),'hair'),{'md':md})
        a,b=fam('MAT_X_Hair_UI'),fam('MAT_X_Hair_T_UI')
        self.assertEqual([e['md'].stem for _,e in mapping._prefer_base_variant([a,b])],['MAT_X_Hair_UI'])
        c=fam('MAT_X_Hair_Pro_UI')
        self.assertEqual(len(mapping._prefer_base_variant([a,c])),2)
        self.assertEqual(len(mapping._prefer_base_variant([b])),1)

    def test_two_json_paths_same_stem_are_not_one_identity(self):
        docs={'a/MAT_Any_Hair.json':dump('MAT_Any_Hair',role='hair'),
              'b/MAT_Any_Hair.json':dump('MAT_Any_Hair',role='hair',floats={'_DstBlend':10})}
        result=self.effect_case(documents=docs)
        self.assert_unresolved(result,1)
        candidates=result['rows'][1]['binding_evidence']['candidate_families']
        self.assertEqual(len({c['json_path'] for c in candidates}),2)
        self.assert_kept(result)

    def test_same_atlas_does_not_erase_independent_semantic_domain(self):
        for effect_name,expected,constrained in (('Hair effect','MAT_Any_Hair',True),
                                                 ('Unidentified overlay','',False)):
            with self.subTest(effect_name=effect_name):
                body=material('Body');hair=material('Hair')
                effect=material(effect_name,rgb=(.95,.95,.95),image_alpha=.2)
                effect.mmd_material.sphere_texture_type='2'
                effect.node_tree.nodes['mmd_sphere_tex']=types.SimpleNamespace(image=FakeImage('sphere'))
                mesh=triangle_mesh([(body,TRIANGLE),(hair,TRIANGLE),(effect,TRIANGLE)])
                docs={'MAT_Any_Body.json':dump('MAT_Any_Body'),
                      'MAT_Any_Hair.json':dump('MAT_Any_Hair',role='hair')}
                with virtual_resources(docs,pixels={'Atlas.png':(.2,.4,.6)}) as v:
                    result=mapping.plan([body,hair,effect],[mesh],armature(),v.root)
                row=result['rows'][2]
                self.assertEqual(row['stem'],expected)
                self.assertEqual(row['binding_evidence']['pre_ranking_families'],1 if constrained else 2)
                if constrained:
                    self.assertEqual(row['effect_policy'],'MME_DUPLICATE_OFF')
                    self.assertEqual(row['effect_evidence']['donor_slots'],[1])
                else:
                    self.assert_unresolved(result,2)
                    self.assertEqual(len(row['binding_evidence']['candidate_families']),2)
                    self.assertFalse(row['archive'])

    def test_cross_object_rest_coincidence_cannot_prove_shared_animation(self):
        donor=material('Hair');effect=material('Hair effect',rgb=(.95,.95,.95),image_alpha=.2)
        effect.mmd_material.sphere_texture_type='2'
        effect.node_tree.nodes['mmd_sphere_tex']=types.SimpleNamespace(image=FakeImage('sphere'))
        meshes=[triangle_mesh([(donor,TRIANGLE)]),triangle_mesh([(effect,TRIANGLE)])]
        with virtual_resources({'MAT_Any_Hair.json':dump('MAT_Any_Hair',role='hair')},pixels={'Atlas.png':(.2,.4,.6)}) as v:
            result=mapping.plan([donor,effect],meshes,armature(),v.root)
        self.assert_unresolved(result,1)
        self.assert_kept(result)

    def test_recovered_overlay_cannot_cascade_into_a_later_donor(self):
        donor=material('Hair');first=material('Hair effect',rgb=(.95,.95,.95),image_alpha=.2)
        second=material('Hair next effect',rgb=(.94,.94,.94),image_alpha=.2)
        for effect in (first,second):
            effect.mmd_material.sphere_texture_type='2'
            effect.node_tree.nodes['mmd_sphere_tex']=types.SimpleNamespace(image=FakeImage('sphere'))
        mesh=triangle_mesh([(donor,TRIANGLE),(first,TRIANGLE),(second,TRIANGLE),(second,TRIANGLE)])
        with virtual_resources({'MAT_Any_Hair.json':dump('MAT_Any_Hair',role='hair')},pixels={'Atlas.png':(.2,.4,.6)}) as v:
            result=mapping.plan([donor,first,second],[mesh],armature(),v.root)
        self.assertEqual(result['rows'][1]['effect_policy'],'MME_DUPLICATE_OFF')
        self.assert_unresolved(result,2)
        self.assertFalse(result['rows'][2]['archive'])
        self.assertEqual(result['rows'][2]['binding_evidence']['pre_ranking_families'],1)
        self.assertEqual(result['rows'][2]['binding_evidence']['candidate_families'],[])

    def test_repeated_material_slot_does_not_multiply_a_donor(self):
        donor=material('Hair');effect=material('Hair effect',rgb=(.95,.95,.95),image_alpha=.2)
        effect.mmd_material.sphere_texture_type='2'
        effect.node_tree.nodes['mmd_sphere_tex']=types.SimpleNamespace(image=FakeImage('sphere'))
        mesh=triangle_mesh([(donor,TRIANGLE),(effect,TRIANGLE),(effect,TRIANGLE)])
        mesh.data.materials.append(donor)
        with virtual_resources({'MAT_Any_Hair.json':dump('MAT_Any_Hair',role='hair')},pixels={'Atlas.png':(.2,.4,.6)}) as v:
            result=mapping.plan([donor,effect,donor],[mesh],armature(),v.root)
        self.assert_unresolved(result,1)
        self.assert_kept(result)

    def test_group_index_order_is_not_part_of_weight_semantics(self):
        def mutate(mesh,*_):
            mesh.vertex_groups=[types.SimpleNamespace(name='bone_a'),types.SimpleNamespace(name='bone_b')]
            for i,v in enumerate(mesh.data.vertices):
                v.groups=[types.SimpleNamespace(group=0,weight=.3),types.SimpleNamespace(group=1,weight=.7)]
                if i>=3:v.groups.reverse()
        row=self.effect_case(mutate=mutate)['rows'][1]
        self.assertEqual(row['effect_policy'],'MME_DUPLICATE_OFF')

    def test_invalid_weight_or_nonfinite_vertex_preserves_without_partial_drop(self):
        def bad_weight(mesh,*_):
            mesh.vertex_groups=[types.SimpleNamespace(name='bone')]
            mesh.data.vertices[-1].groups=[types.SimpleNamespace(group=0,weight=float('nan'))]
        result=self.effect_case(mutate=bad_weight)
        self.assert_mapped(result,['MAT_Any_Hair']*2)
        row=self.assert_kept(result)
        self.assertIn('invalid vertex-group weight',row['duplicate_evidence']['blockers'])
        def bad_position(mesh,*_):mesh.data.vertices[-1].co=(float('nan'),1.,0.)
        result=self.effect_case(mutate=bad_position)
        self.assert_unresolved(result,1)
        self.assert_kept(result)

    def test_custom_normal_attribute_storage_must_be_complete_and_native(self):
        def mutate(mesh,*_):mesh.data.attributes['custom_normal'].data.pop()
        result=self.effect_case(mesh_options={'custom_normals':(0,0)},mutate=mutate)
        self.assert_mapped(result,['MAT_Any_Hair']*2)
        row=self.assert_kept(result)
        self.assertIn('unsupported normal attribute custom_normal',row['duplicate_evidence']['blockers'])

    def test_unrelated_material_morph_does_not_block_a_proved_effect(self):
        def mutate(mesh,donor,effect,rig):
            unrelated=material('Eye')
            offset=types.SimpleNamespace(material_data=unrelated,material_id=4)
            rig.parent.mmd_root.material_morphs=[types.SimpleNamespace(name='eye only',data=[offset])]
        row=self.effect_case(mutate=mutate)['rows'][1]
        self.assertEqual(row['effect_policy'],'MME_DUPLICATE_OFF')

    def test_source_material_or_node_drivers_prevent_default_off(self):
        for where in ('material','node_tree'):
            def mutate(mesh,donor,effect,rig):
                target=effect if where=='material' else effect.node_tree
                target.animation_data=types.SimpleNamespace(drivers=['alpha'])
            with self.subTest(where=where):
                row=self.assert_kept(self.effect_case(mutate=mutate))
                self.assertIn('animated/driven source material not proved',row['effect_diagnostic']['blockers'])

    def test_specialized_wing_inference_is_never_duplicate_off_proof(self):
        donor=material('Wing');effect=material('Wing effect',rgb=(.95,.95,.95),image_alpha=.2)
        effect.mmd_material.sphere_texture_type='2'
        effect.node_tree.nodes['mmd_sphere_tex']=types.SimpleNamespace(image=FakeImage('sphere'))
        mesh=triangle_mesh([(donor,TRIANGLE),(effect,TRIANGLE)])
        with virtual_resources({'MAT_Any_Wing.json':dump('MAT_Any_Wing',role='wing')},pixels={'Atlas.png':(.2,.4,.6)}) as v:
            result=mapping.plan([donor,effect],[mesh],armature(),v.root)
        self.assert_mapped(result,['MAT_Any_Wing']*2)
        row=self.assert_kept(result)
        self.assertIn('specialized inference',row['effect_diagnostic']['blockers'][0])


class MMEEffectPolicyTests(MappingTestCase):
    def plan_effect(self, *, additive=True, low_alpha=True, overlap=True, source_alpha=.2):
        donor = material('Hair', rgb=(.2,.4,.6))
        effect = material('Hair effect', rgb=(.95,.95,.95), image_alpha=source_alpha if low_alpha else .8)
        effect.mmd_material.sphere_texture_type = '2' if additive else '1'
        effect.node_tree.nodes['mmd_sphere_tex'] = types.SimpleNamespace(image=FakeImage('sphere'))
        tri = TRIANGLE if overlap else tuple((x+5.,y,z) for x,y,z in TRIANGLE)
        mesh=triangle_mesh([(donor,TRIANGLE),(effect,tri)])
        with virtual_resources({'MAT_Unknown_Hair.json':dump('MAT_Unknown_Hair', role='hair')}, pixels={'Atlas.png':(.2,.4,.6)}) as v:
            return mapping.plan([donor,effect],[mesh],armature(),v.root)

    def test_low_alpha_additive_proven_duplicate_is_preserved_but_default_off(self):
        row=self.plan_effect()['rows'][1]
        self.assertEqual(row['effect_policy'],'MME_DUPLICATE_OFF')
        self.assertTrue(row['archive'])
        self.assertEqual(row['effect_evidence']['triangle_overlap'],1.)
        self.assertEqual(row['effect_evidence']['donor_slots'],[0])
        self.assertTrue(row['stem'])

    def test_non_additive_duplicate_is_not_disabled(self):
        self.assertNotIn('effect_policy',self.plan_effect(additive=False)['rows'][1])

    def test_opaque_additive_duplicate_is_not_disabled(self):
        self.assertNotIn('effect_policy',self.plan_effect(low_alpha=False)['rows'][1])

    def test_low_alpha_without_geometric_proof_is_not_disabled(self):
        self.assertNotIn('effect_policy',self.plan_effect(overlap=False)['rows'][1])


if __name__ == "__main__":
    unittest.main()
