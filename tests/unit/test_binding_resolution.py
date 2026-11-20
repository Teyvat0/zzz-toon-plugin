"""Pure-stdlib binding tests; no bpy, image decoder or original-asset writes.

Run: python -B -m unittest discover -s tests/unit -p test_binding_resolution.py -v
Synthetic fixtures are generated only inside TemporaryDirectory. The optional
local regression cases read the existing asset directories without copying them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import types
import unittest


_SOURCE = Path(__file__).resolve().parents[2] / "zzz_mmd_toon" / "resources.py"
resources = types.ModuleType("_zzz_binding_resources_tests")
exec(compile(_SOURCE.read_text(encoding="utf-8"), str(_SOURCE), "exec"), resources.__dict__)


def _env(name=None, *, file_id=3, path_id=-9223372036854775801, null=False, **metadata):
    texture = {"m_FileID": file_id, "m_PathID": path_id, "IsNull": null, **metadata}
    if name is not None:
        texture["Name"] = name
    return {"m_Texture": texture, "m_Scale": {"X": 1, "Y": 1},
            "m_Offset": {"X": 0.25, "Y": -0.5}}


def _unity(textures=None, **properties):
    return {"m_SavedProperties": {"m_TexEnvs": textures or {}, **properties}}


def _dnma(**overrides):
    refs = {prop: _env(path_id=str(1234567890123456780 + i))
            for i, prop in enumerate(("_MainTex", "_LightTex", "_OtherDataTex", "_OtherDataTex2"))}
    refs.update(overrides)
    return refs


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def dump(self, name, textures=None, **properties):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_unity(textures, **properties)), encoding="utf-8-sig")
        return path

    def image(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"dummy png bytes; no image decoding is allowed or needed")
        return str(path.resolve())

    def atlas(self, family, channels="DNMA", directory="Textures"):
        return {prop: self.image(f"{directory}/{family}_{channel.upper()}.png")
                for prop, channel in resources._CHANNELS.items() if channel.upper() in channels}

    def catalog(self):
        result = resources.resolve_catalog(self.root)
        self.assertEqual(set(result), {"materials", "index", "warnings", "errors"})
        self.assertIsInstance(result["index"], resources.TextureIndex)
        self.assertTrue(all(isinstance(v, str) for k in ("warnings", "errors") for v in result[k]))
        return result, {material.stem: material for material in result["materials"]}

    def test_non_null_no_name_references_preserve_raw_ids_and_metadata(self):
        refs = {
            "_MainTex": _env(file_id="3", path_id=-9223372036854775801),
            "_LightTex": _env("", file_id=4, path_id="9223372036854775807"),
            "_OtherDataTex": _env(None, file_id=5, path_id=99, extra={"keep": True}),
        }
        path = self.dump("Materials/MAT_Test_Body_1_UI.json", refs)
        material = resources.MaterialData(path)
        self.assertEqual(material.textures, {})
        self.assertEqual(set(material.references), set(refs))
        for prop, env in refs.items():
            self.assertEqual(material.texenvs[prop], env)
            self.assertEqual(material.references[prop], env["m_Texture"])
            self.assertEqual(material.unresolved[prop]["raw"], env["m_Texture"])
            self.assertIs(type(material.references[prop]["m_FileID"]), type(env["m_Texture"]["m_FileID"]))
            self.assertIs(type(material.references[prop]["m_PathID"]), type(env["m_Texture"]["m_PathID"]))
        self.assertEqual(material.raw, _unity(refs))
        result, by_stem = self.catalog()
        parsed = by_stem[material.stem]
        self.assertEqual(parsed.unresolved["_LightTex"]["raw"]["m_PathID"], "9223372036854775807")
        self.assertFalse(parsed.unresolved["_MainTex"]["optional"])
        self.assertEqual(len(result["errors"]), 4)

    def test_null_references_are_not_fictional_requests(self):
        refs = {"_Null": _env("Never", null=True),
                "_Zero": {"m_Texture": {"m_FileID": "0", "m_PathID": 0, "Name": ""}},
                "_Empty": {"m_Texture": {"Name": ""}},
                "_ExplicitNonNull": _env(file_id=0, path_id=0),
                "_MissingEnv": None,
                "_MissingTexture": {"m_Texture": None}}
        path = self.dump("MAT_HairShadow.json", refs)
        material = resources.MaterialData(path)
        self.assertEqual(set(material.references), {"_ExplicitNonNull"})
        self.assertEqual(material.textures, {})
        self.assertEqual(material.texenvs, refs)
        result, by_stem = self.catalog()
        self.assertEqual(result["errors"], [])
        self.assertEqual(set(by_stem["MAT_HairShadow"].unresolved), {"_ExplicitNonNull"})

    def test_scan_materials_still_returns_unvalidated_names_and_typed_values(self):
        refs = {"_MainTex": _env("DoesNotExist#123"), "_Empty": _env("")}
        self.dump("Materials/Untyped.json", refs,
                  m_Floats=[["_Value", "0.5"]], m_Colors={"_Color": [0.1, 0.2, 2.0]})
        material = resources.scan_materials(self.root / "Materials")[0]
        self.assertEqual(material.textures, {"_MainTex": "DoesNotExist#123"})
        self.assertEqual(material.main_tex, "DoesNotExist#123")
        self.assertEqual(material.get("_Value"), 0.5)
        self.assertEqual(material.get("_Color"), (0.1, 0.2, 2.0, 1.0))
        self.assertEqual(material.resolution, {})
        self.assertIn("_Empty", material.unresolved)

    def test_explicit_names_take_priority_even_when_family_differs(self):
        expected = self.atlas("Arbitrary_Body_Map2")
        self.atlas("Unrelated_Body_Map1")
        refs = {prop: _env(Path(path).stem) for prop, path in expected.items()}
        self.dump("MAT_Whatever_Body_1_T_UI.json", refs)
        result, by_stem = self.catalog()
        material = by_stem["MAT_Whatever_Body_1_T_UI"]
        self.assertEqual(result["errors"], [])
        self.assertEqual(material.textures, {p: e["m_Texture"]["Name"] for p, e in refs.items()})
        self.assertEqual(material.unresolved, {})
        self.assertEqual({r["method"] for r in material.resolution.values()}, {"explicit"})
        for prop, path in expected.items():
            self.assertEqual(material.resolution[prop]["path"], path)

    def test_broken_explicit_name_does_not_silently_infer_another_texture(self):
        self.atlas("Anything_Body_Map1")
        self.dump("MAT_Test_Body_1_UI.json", _dnma(_MainTex=_env("Missing_D.png")))
        result, by_stem = self.catalog()
        material = by_stem["MAT_Test_Body_1_UI"]
        self.assertNotIn("_MainTex", material.textures)
        self.assertIn("explicit Name was not found", material.unresolved["_MainTex"]["reason"])
        self.assertTrue(any(material.stem + " _MainTex" in error for error in result["errors"]))
        self.assertEqual(material.unresolved["_MainTex"]["raw"]["Name"], "Missing_D.png")

    def test_ambiguous_explicit_name_and_path_reference_remain_strict(self):
        self.atlas("Anything_Body_Map1")
        expected = [self.image("A/Explicit.png"), self.image("B/Explicit.png")]
        self.dump("MAT_Test_Body_1_UI.json", _dnma(_MainTex=_env("Explicit")))
        result, by_stem = self.catalog()
        material = by_stem["MAT_Test_Body_1_UI"]
        self.assertEqual(set(material.unresolved["_MainTex"]["candidates"]), set(expected))
        self.assertNotIn("_MainTex", material.resolution)
        self.assertEqual(len(result["errors"]), 1)
        with self.assertRaises(resources.AmbiguousTextureError):
            result["index"].find("Explicit.png")
        self.assertEqual(result["index"].find("A\\Explicit.png"), expected[0])
        self.assertIsNone(result["index"].find("unknown/Explicit.png"))
        self.assertIsNone(result["index"].find("Explicit.jpg"))

    def test_unique_body_number_families_and_separate_states(self):
        first = self.atlas("NoIdentityMatching_Body_Map1")
        second = self.atlas("DifferentPrefix_Body_Map2")
        for stem in ("MAT_X_Body_1_UI", "MAT_X_Body_1_T_UI", "MAT_X_Body_2_UI"):
            self.dump("Materials/" + stem + ".json", _dnma())
        self.dump("Materials/MAT_HairShadow.json")
        result, by_stem = self.catalog()
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["materials"]), 4)
        for stem in ("MAT_X_Body_1_UI", "MAT_X_Body_1_T_UI"):
            self.assertEqual(by_stem[stem].textures, first)
            self.assertEqual({r["method"] for r in by_stem[stem].resolution.values()}, {"inferred"})
        self.assertEqual(by_stem["MAT_X_Body_2_UI"].textures, second)
        self.assertEqual(by_stem["MAT_HairShadow"].textures, {})
        self.assertEqual(by_stem["MAT_HairShadow"].unresolved, {})
        self.assertNotEqual(by_stem["MAT_X_Body_1_UI"].path, by_stem["MAT_X_Body_1_T_UI"].path)
        self.assertTrue(all(Path(value).is_absolute() for value in first.values()))

    def test_unique_hair_family_is_allowed_but_body_is_not_hair_evidence(self):
        hair = self.atlas("Any_Hair_Map3")
        self.atlas("Any_Body_Map3")
        self.dump("MAT_Unknown_Hair_3_T_UI.json", _dnma())
        result, by_stem = self.catalog()
        self.assertEqual(result["errors"], [])
        self.assertEqual(by_stem["MAT_Unknown_Hair_3_T_UI"].textures, hair)

    def test_hair_without_hair_atlas_is_unresolved_and_can_be_overridden(self):
        self.atlas("Whatever_Body_Map2")
        self.dump("MAT_Unknown_Body_2_UI.json", _dnma())
        self.dump("MAT_Unknown_Hair_T_UI.json", _dnma())
        result, by_stem = self.catalog()
        hair = by_stem["MAT_Unknown_Hair_T_UI"]
        self.assertEqual(hair.textures, {})
        self.assertEqual(set(hair.unresolved), set(resources._CHANNELS))
        self.assertEqual(len(result["errors"]), 4)
        self.assertTrue(all(not entry["optional"] for entry in hair.unresolved.values()))
        self.assertEqual(len(result["materials"]), 2)
        # Exact same FileIDs and PathIDs in two JSONs are not equivalence proof.
        self.assertTrue(by_stem["MAT_Unknown_Body_2_UI"].textures)

    def test_unnumbered_body_does_not_select_one_of_multiple_atlases(self):
        first = self.atlas("Any_Body_Map1")
        self.atlas("Any_Body_Map2", channels="D")
        self.dump("MAT_X_Body_UI.json", _dnma())
        result, by_stem = self.catalog()
        material = by_stem["MAT_X_Body_UI"]
        self.assertEqual(material.textures, {})
        self.assertEqual(len(result["errors"]), 4)
        # N has one file, but selecting it would mix an ambiguous atlas family.
        self.assertEqual(material.unresolved["_LightTex"]["candidates"], [first["_LightTex"]])

    def test_character_prefix_never_breaks_a_structural_family_tie(self):
        first = self.atlas("Matching_Body_Map1")
        second = self.atlas("Other_Body_Map1")
        self.dump("MAT_Matching_Body_1_UI.json", _dnma())
        result, by_stem = self.catalog()
        material = by_stem["MAT_Matching_Body_1_UI"]
        self.assertEqual(material.textures, {})
        self.assertEqual(set(material.unresolved["_MainTex"]["candidates"]),
                         {first["_MainTex"], second["_MainTex"]})
        self.assertEqual(len(result["errors"]), 4)

    def test_duplicate_image_extensions_are_not_arbitrarily_selected(self):
        expected = self.atlas("NoTable_Body_Map1")
        other = self.image("Textures/NoTable_Body_Map1_D.tga")
        self.dump("MAT_Any_Body_1_UI.json", _dnma())
        result, by_stem = self.catalog()
        material = by_stem["MAT_Any_Body_1_UI"]
        self.assertEqual(set(material.unresolved["_MainTex"]["candidates"]), {expected["_MainTex"], other})
        self.assertNotIn("_MainTex", material.textures)
        self.assertEqual(len(result["errors"]), 1)

    def test_face_eye_and_eyebrows_share_only_unique_face_diffuse(self):
        diffuse = self.image("Textures/Unknown_Face_Map_D.png")
        light = self.image("Textures/Female_Face_Lightmap.png")
        self.image("Textures/Eye_E.png")
        for role in ("Face", "Eye", "Eyebrows"):
            refs = {"_MainTex": _env()}
            if role == "Face":
                refs["_LightTex"] = _env(path_id="99")
            self.dump(f"Materials/MAT_Different_{role}_UI.json", refs)
        result, by_stem = self.catalog()
        self.assertEqual(result["errors"], [])
        for material in by_stem.values():
            self.assertEqual(material.textures["_MainTex"], diffuse)
        self.assertEqual(by_stem["MAT_Different_Face_UI"].textures["_LightTex"], light)

    def test_face_ambiguity_and_nonunique_lightmap_are_required_errors(self):
        diffuse = [self.image("Textures/One_Face_D.png"), self.image("Textures/Two_Face_Map_D.png")]
        light = [self.image("A/Female_Face_Lightmap.png"), self.image("B/Female_Face_Lightmap.png")]
        self.dump("MAT_Any_Face_UI.json", {"_MainTex": _env(), "_LightTex": _env()})
        result, by_stem = self.catalog()
        material = by_stem["MAT_Any_Face_UI"]
        self.assertEqual(material.textures, {})
        self.assertEqual(set(material.unresolved["_MainTex"]["candidates"]), set(diffuse))
        self.assertEqual(set(material.unresolved["_LightTex"]["candidates"]), set(light))
        self.assertEqual(len(result["errors"]), 2)

    def test_face_lightmap_pattern_accepts_male_and_numbered_names_only_when_unique(self):
        self.image("Textures/Unknown_Face_D.png")
        light = self.image("Textures/Male_Face_01_Lightmap.png")
        self.dump("MAT_Any_Face_UI.json", {"_MainTex": _env(), "_LightTex": _env()})
        result, by_stem = self.catalog()
        self.assertEqual(by_stem["MAT_Any_Face_UI"].textures["_LightTex"], light)
        self.assertEqual(result["errors"], [])

    def test_unrelated_lightmap_name_is_not_a_face_lightmap(self):
        self.image("Textures/Unknown_Face_D.png")
        self.image("Textures/Unknown_Body_Lightmap.png")
        self.dump("MAT_Any_Face_UI.json", {"_MainTex": _env(), "_LightTex": _env()})
        result, by_stem = self.catalog()
        self.assertNotIn("_LightTex", by_stem["MAT_Any_Face_UI"].textures)
        self.assertEqual(len(result["errors"]), 1)

    def test_multiple_unnamed_matcaps_are_optional_and_never_ordered_by_id(self):
        expected = self.atlas("Unknown_Body_Map1")
        caps = [self.image("Textures/Eff_MatCap_001.png"), self.image("Textures/Eff_MatCap_002.png")]
        refs = _dnma(_MatCapTex=_env(file_id=4, path_id="777"),
                     _MatCapTex2=_env(file_id=5, path_id=888))
        self.dump("MAT_Any_Body_1_UI.json", refs)
        result, by_stem = self.catalog()
        material = by_stem["MAT_Any_Body_1_UI"]
        self.assertEqual(material.textures, expected)
        self.assertEqual(result["errors"], [])
        for prop in ("_MatCapTex", "_MatCapTex2"):
            self.assertTrue(material.unresolved[prop]["optional"])
            self.assertEqual(set(material.unresolved[prop]["candidates"]), set(caps))
            self.assertIn("disable", material.unresolved[prop]["reason"])
            self.assertNotIn(prop, material.resolution)
            self.assertTrue(any(material.stem + " " + prop + ":" in warning for warning in result["warnings"]))
        self.assertEqual(material.unresolved["_MatCapTex"]["raw"]["m_PathID"], "777")
        json.dumps(material.unresolved)

    def test_one_matcap_image_cannot_identify_multiple_unnamed_references(self):
        cap = self.image("Textures/Eff_MatCap_001.png")
        self.dump("MAT_HairShadow.json", {"_MatCapTex": _env(), "_MatCapTex2": _env(path_id=88)})
        result, by_stem = self.catalog()
        material = by_stem["MAT_HairShadow"]
        self.assertEqual(material.textures, {})
        self.assertEqual(result["errors"], [])
        self.assertEqual(set(material.unresolved), {"_MatCapTex", "_MatCapTex2"})
        self.assertTrue(all(entry["candidates"] == [cap] for entry in material.unresolved.values()))

    def test_explicit_matcap_resolves_while_unnamed_reference_stays_optional(self):
        cap = self.image("Textures/Eff_MatCap_001.png")
        self.dump("MAT_HairShadow.json", {"_MatCapTex": _env("Eff_MatCap_001"), "_MatCapTex2": _env()})
        result, by_stem = self.catalog()
        material = by_stem["MAT_HairShadow"]
        self.assertEqual(result["errors"], [])
        self.assertEqual(material.textures, {"_MatCapTex": "Eff_MatCap_001"})
        self.assertEqual(material.resolution["_MatCapTex"]["path"], cap)
        self.assertEqual(set(material.unresolved), {"_MatCapTex2"})

    def test_cross_json_file_and_path_ids_are_never_used_as_a_decoder(self):
        self.image("Textures/NamedTexture.png")
        self.dump("Materials/One.json", {"_MainTex": _env("NamedTexture", file_id=2, path_id=99)})
        self.dump("Materials/Two.json", {"_MainTex": _env(file_id=2, path_id=99)})
        result, by_stem = self.catalog()
        self.assertEqual(by_stem["One"].textures["_MainTex"], "NamedTexture")
        self.assertNotIn("_MainTex", by_stem["Two"].textures)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(by_stem["Two"].unresolved["_MainTex"]["candidates"], [])

    def test_absent_and_explicitly_null_required_refs_are_errors_not_invented(self):
        self.atlas("Any_Body_Map1")
        # Even an existing stale Name must not resurrect an explicitly null ref.
        self.dump("MAT_Any_Body_1_UI.json", {"_MainTex": _env("Any_Body_Map1_D", null=True)})
        result, by_stem = self.catalog()
        material = by_stem["MAT_Any_Body_1_UI"]
        self.assertEqual(material.textures, {})
        self.assertEqual(len(result["errors"]), 4)
        self.assertEqual(material.unresolved["_MainTex"]["raw"]["IsNull"], True)
        self.assertIsNone(material.unresolved["_LightTex"]["raw"])

    def test_duplicate_stems_and_textureless_hairshadow_remain_separate(self):
        self.dump("Materials/MAT_HairShadow_UI.json")
        self.dump("Nested/MAT_HairShadow_UI.json")
        result, by_stem = self.catalog()
        self.assertEqual(len(result["materials"]), 2)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])
        self.assertNotEqual(result["materials"][0].path, result["materials"][1].path)
        self.assertTrue(all(not material.textures for material in result["materials"]))

    def test_bad_json_is_reported_without_discarding_valid_materials(self):
        self.dump("Materials/MAT_HairShadow_UI.json")
        bad = self.root / "Materials" / "bad.json"
        bad.write_text("{malformed", encoding="utf-8")
        result, by_stem = self.catalog()
        self.assertEqual(set(by_stem), {"MAT_HairShadow_UI"})
        self.assertTrue(any("bad.json" in error for error in result["errors"]))
        with self.assertRaises(resources.MaterialFormatError):
            resources.scan_materials(self.root)

    def test_invalid_root_returns_explicit_catalog_diagnostic(self):
        for root in ("", self.root / "does-not-exist"):
            with self.subTest(root=root):
                result = resources.resolve_catalog(root)
                self.assertEqual(result["materials"], [])
                self.assertTrue(result["errors"])
                self.assertIsInstance(result["index"], resources.TextureIndex)


class LocalAssetRegressionTests(unittest.TestCase):
    """Read-only integration evidence; names here are fixtures, never rules."""
    base = Path(os.environ.get("ZZZ_ASSETS_DIR", "ZZZ-Characters"))

    def test_evelyn_nameless_body_face_and_unresolved_hair_matcaps(self):
        root = self.base / "evelyn-chevalier-a-moth-to-light"
        if not root.is_dir():
            self.skipTest("Local Evelyn assets are not installed")
        result = resources.resolve_catalog(root)
        materials = result["materials"]
        by_stem = {material.stem: material for material in materials}
        self.assertEqual({m.path for m in materials}, {m.path for m in resources.scan_materials(root)})
        for suffix in ("Body_1_UI", "Body_1_T_UI", "Body_2_UI"):
            material = by_stem["MAT_Evelyn_" + suffix]
            self.assertTrue(set(resources._CHANNELS) <= set(material.textures))
            self.assertTrue(all(material.resolution[prop]["method"] == "inferred" for prop in resources._CHANNELS))
            self.assertTrue(all(entry["optional"] for entry in material.unresolved.values()))
        face = by_stem["MAT_Evelyn_Face_UI"]
        self.assertTrue({"_MainTex", "_LightTex"} <= set(face.textures))
        for stem in ("MAT_Evelyn_Eye_UI", "MAT_Evelyn_Eyebrows_UI"):
            self.assertEqual(by_stem[stem].textures["_MainTex"], face.textures["_MainTex"])
        hair = by_stem["MAT_Evelyn_Hair_T_UI"]
        self.assertFalse(set(resources._CHANNELS) & set(hair.textures))
        self.assertTrue(set(resources._CHANNELS) <= set(hair.unresolved))
        self.assertTrue(all(any(hair.stem + " " + prop in error for error in result["errors"])
                            for prop in resources._CHANNELS))
        self.assertTrue(any("MatCap" in warning for warning in result["warnings"]))
        self.assertEqual(by_stem["MAT_HairShadow"].textures, {})

    def test_astra_explicit_hair_body_atlas_is_not_blocked_by_family(self):
        root = self.base / "astra-yao-scarlet-rock-chandelier" / "Scarlet Rock"
        if not root.is_dir():
            self.skipTest("Local Astra assets are not installed")
        result = resources.resolve_catalog(root / "Materials")
        self.assertEqual(result["errors"], [])
        by_stem = {material.stem: material for material in result["materials"]}
        hair = by_stem["MAT_Astra_Hair_T_UI"]
        self.assertEqual(hair.textures["_MainTex"], "Astra_Body_Map2_D")
        self.assertEqual(hair.resolution["_MainTex"]["method"], "explicit")
        self.assertTrue(set(resources._CHANNELS) <= set(hair.textures))
        self.assertEqual(by_stem["MAT_HairShadow_UI"].textures, {})
        self.assertEqual(len(result["materials"]), len(resources.scan_materials(root)))


if __name__ == "__main__":
    unittest.main()
