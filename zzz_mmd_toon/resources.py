"""Read Unity material dumps and resolve their exact texture references.

This module deliberately has no Blender dependency. Scanning preserves every
JSON identity, including textureless and alternate-state materials. The optional
``resolve_catalog`` pass validates explicit names first, then allows only unique
structural texture-family inference. Unity pointer IDs are never decoded or
compared across JSON files; no pixel/PMX evidence is invented here.
"""

from __future__ import annotations

import json
import math
import os
import posixpath
import re
from collections.abc import Mapping
from pathlib import Path


IMAGE_EXTS = frozenset({
    ".png", ".tga", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".dds",
    ".webp", ".exr", ".hdr",
})


def preview_backface_culling(md, role):
    """Audited Goo preview raster state; not Unity/game pass equivalence."""
    if role in {'eye', 'mouth', 'eyebrow', 'eye_shadow', 'eye_shadow_texture', 'eye_highlight'}:
        return False
    cull, double = md.get('_Cull'), md.get('_DoubleSided')
    return (cull == 2) or not (double == 1 or cull == 0)


def native_preview_culling(source, detached_culling, *, preserve_source_texture=False):
    """Final source raster coverage, or None if native evidence is unavailable."""
    old = getattr(source, 'use_backface_culling', None)
    double = getattr(getattr(source, 'mmd_material', None), 'is_double_sided', None)
    if old is True or double is False:
        return True
    if old is not False or double is not True:
        return None
    if preserve_source_texture:
        return False
    return bool(detached_culling) if isinstance(detached_culling, bool) else None


class MaterialFormatError(ValueError):
    """A JSON file cannot be interpreted without dropping material data."""


class AmbiguousTextureError(ValueError):
    """A texture reference has more than one possible indexed file."""

    def __init__(self, reference: str, candidates):
        self.reference = reference
        self.candidates = tuple(sorted(set(candidates), key=lambda p: (p.casefold(), p)))
        super().__init__(
            f"Ambiguous texture reference {reference!r}: " + "; ".join(self.candidates)
        )


def _directory(root) -> Path:
    if root is None or not os.fspath(root):
        raise ValueError("A non-empty resource directory is required")
    path = Path(root).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(str(path))
    if not path.is_dir():
        raise NotADirectoryError(str(path))
    return path


def normalize_root(root) -> str:
    """Return an absolute resource root, accepting its Materials directory too.

    Missing paths and non-directories raise FileNotFoundError and
    NotADirectoryError respectively; an empty path raises ValueError. No global
    configuration or character-specific local paths are consulted.
    """
    path = _directory(root)
    return str(path.parent if path.name.casefold() == "materials" else path)


def _pairs(value, label: str) -> dict:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        result = dict(value)
    elif isinstance(value, (list, tuple)):
        result = {}
        for item in value:
            if isinstance(item, Mapping):
                if "Key" in item and "Value" in item:
                    key, entry = item["Key"], item["Value"]
                elif "first" in item and "second" in item:
                    key, entry = item["first"], item["second"]
                else:
                    raise MaterialFormatError(f"{label}: unsupported property pair {item!r}")
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                key, entry = item
            else:
                raise MaterialFormatError(f"{label}: unsupported property pair {item!r}")
            if not isinstance(key, str):
                raise MaterialFormatError(f"{label}: property names must be strings")
            if key in result:
                raise MaterialFormatError(f"{label}: duplicate property {key!r}")
            result[key] = entry
    else:
        raise MaterialFormatError(f"{label}: expected a property dictionary or pair list")
    if any(not isinstance(key, str) for key in result):
        raise MaterialFormatError(f"{label}: property names must be strings")
    return result


def _number(value, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MaterialFormatError(f"{label}: invalid numeric value {value!r}") from exc
    if not math.isfinite(result):
        raise MaterialFormatError(f"{label}: non-finite numeric value {value!r}")
    return result


def _rgba(value, label: str) -> tuple[float, float, float, float]:
    if isinstance(value, Mapping) and all(k in value for k in ("r", "g", "b")):
        components = (value["r"], value["g"], value["b"], value.get("a", 1.0))
    elif isinstance(value, (list, tuple)) and len(value) in (3, 4):
        components = tuple(value) + ((1.0,) if len(value) == 3 else ())
    else:
        raise MaterialFormatError(f"{label}: expected RGB(A) colour components")
    # Unity also stores packed data vectors in m_Colors. Do not gamma or clamp.
    return tuple(_number(v, label) for v in components)


class MaterialData:
    """One material JSON, including its exact raw fields and texture metadata.

    Before catalogue resolution, ``textures`` retains the compatible property ->
    explicit Name interface. ``references`` also keeps non-null references with
    no Name; their FileID/PathID values are never coerced or interpreted. ``raw``
    and ``texenvs`` retain null entries, scale/offset and all original metadata.
    ``resolve_catalog`` validates ``textures`` and adds per-property ``resolution``
    (method, path and evidence) or ``unresolved`` (raw reference, candidates,
    optional and reason). Callers can supply independently verified overrides.
    Floats and colours are parsed but never gamma-converted or range-clamped.
    ``get`` intentionally queries scalar/colour shader parameters, not textures.
    Malformed data raises MaterialFormatError rather than silently losing a
    material or parameter during preflight.
    """

    def __init__(self, path):
        self.path = str(Path(path).expanduser().resolve())
        try:
            with open(self.path, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise MaterialFormatError(f"{self.path}: invalid material JSON: {exc}") from exc
        if not isinstance(data, dict) or "m_SavedProperties" not in data:
            raise MaterialFormatError(f"{self.path}: not a Unity material JSON")
        props = data["m_SavedProperties"]
        if props is None:
            props = {}
        if not isinstance(props, Mapping):
            raise MaterialFormatError(f"{self.path}: m_SavedProperties must be a dictionary")
        self.raw = data
        self.stem = Path(self.path).stem
        self.name = data.get("m_Name") or self.stem
        shader = data.get("m_Shader")
        self.shader = shader.get("Name", "") if isinstance(shader, Mapping) else ""
        prefix = self.path + ": "
        self.floats = {
            key: _number(value, prefix + key)
            for key, value in _pairs(props.get("m_Floats"), prefix + "m_Floats").items()
        }
        self.colors = {
            key: _rgba(value, prefix + key)
            for key, value in _pairs(props.get("m_Colors"), prefix + "m_Colors").items()
        }
        self.texenvs = _pairs(props.get("m_TexEnvs"), prefix + "m_TexEnvs")
        self.textures = {}
        self.references = {}
        self.resolution = {}
        self.unresolved = {}
        for key, env in self.texenvs.items():
            if env is None:
                continue
            if not isinstance(env, Mapping):
                raise MaterialFormatError(f"{prefix}{key}: texture environment must be a dictionary")
            texture = env.get("m_Texture")
            if texture is None:
                continue
            if not isinstance(texture, Mapping):
                raise MaterialFormatError(f"{prefix}{key}: m_Texture must be a dictionary")
            name = texture.get("Name", "")
            if name is None:
                name = ""
            if not isinstance(name, str):
                raise MaterialFormatError(f"{prefix}{key}: texture Name must be a string")
            # An explicit null flag is authoritative. Older exports without it
            # can express a null pointer as FileID=PathID=0. Do not turn those
            # placeholders into requested textures; retain them in texenvs/raw.
            has_pointer = any(texture.get(field) not in (None, "", 0, "0")
                              for field in ("m_FileID", "m_PathID"))
            non_null = not texture.get("IsNull", False) and (
                bool(name) or has_pointer or texture.get("IsNull") is False)
            if non_null:
                self.references[key] = dict(texture)
                if name:
                    self.textures[key] = name
                else:
                    self.unresolved[key] = {
                        "raw": dict(texture), "candidates": [], "optional": True,
                        "reason": "non-null texture reference has no Name",
                    }

    def get(self, key, default=None):
        if key in self.floats:
            return self.floats[key]
        if key in self.colors:
            return self.colors[key]
        return default

    @property
    def main_tex(self) -> str:
        """Convenience only; it must never be used to merge material identities."""
        return self.textures.get("_MainTex", "")


def _walk_files(path: Path):
    # os.walk does not follow directory symlinks and has deterministic ordering.
    def fail(error):
        raise error

    for directory, dirs, names in os.walk(path, followlinks=False, onerror=fail):
        dirs.sort(key=lambda s: (s.casefold(), s))
        for name in sorted(names, key=lambda s: (s.casefold(), s)):
            file = Path(directory) / name
            if file.is_file():
                yield file


def scan_materials(root) -> list[MaterialData]:
    """Catalogue every material JSON recursively, without MainTex/state filters.

    Duplicate stems are kept as distinct entries. The material-building caller
    must reject stem ambiguity rather than choosing a first entry. Any malformed
    JSON is an explicit MaterialFormatError (including its path); scans never
    silently present a partial catalogue as complete.
    """
    path = Path(normalize_root(root))
    files = [p for p in _walk_files(path) if p.suffix.casefold() == ".json"]
    files.sort(key=lambda p: (str(p).casefold(), str(p)))
    return [MaterialData(path) for path in files]


def validate_role_textures(material, index, role):
    """Side-effect-free role contract; call before any Blender preparation."""
    required = set() if role == 'eye_shadow' else {'_MainTex'}
    if role in {'body', 'hair', 'wing'}:
        required.update(('_LightTex', '_OtherDataTex', '_OtherDataTex2'))
    elif role == 'face':
        required.add('_LightTex')
    result = {}
    for key in sorted(required):
        ref = material.textures.get(key)
        if not ref:
            raise MaterialFormatError(f'{material.stem}: required texture property {key} is empty')
        path = index.find(ref)
        if not path or not Path(path).is_file():
            raise FileNotFoundError(f'{material.stem} {key}: {ref}')
        result[key] = path
    return result


def _reference_key(name: str) -> str:
    return posixpath.normpath(name.replace("\\", "/")).casefold()


class TextureIndex:
    """Resolve exact case-insensitive names, never silently first-match a file.

    ``find`` accepts an exact file stem, exact filename (with extension), or an
    explicitly indexed relative/absolute path. A name with an extension never
    falls back to another extension, and path references never degrade to a
    basename search. ``#123`` suffixes and alternate atlas names are not stripped.
    Missing/empty references return None; duplicate candidates raise
    AmbiguousTextureError, even if their bytes happen to be identical.
    """

    def __init__(self):
        self._roots = set()
        self._by_stem = {}
        self._by_filename = {}
        self._by_path = {}

    @staticmethod
    def _add(table, key: str, path: str):
        table.setdefault(key, set()).add(path)

    def add_dir(self, root):
        path = Path(normalize_root(root))
        root_key = os.path.normcase(str(path))
        if root_key in self._roots:
            return
        self._roots.add(root_key)
        for file in _walk_files(path):
            if file.suffix.casefold() not in IMAGE_EXTS:
                continue
            absolute = str(file.resolve())
            self._add(self._by_stem, file.stem.casefold(), absolute)
            self._add(self._by_filename, file.name.casefold(), absolute)
            self._add(self._by_path, _reference_key(absolute), absolute)
            self._add(self._by_path, _reference_key(file.relative_to(path).as_posix()), absolute)

    def find(self, name):
        if name is None or name == "":
            return None
        if not isinstance(name, str):
            raise TypeError("Texture reference must be a string or None")
        key = _reference_key(name)
        if "/" in name.replace("\\", "/") or ":" in name:
            candidates = self._by_path.get(key, set())
        elif Path(name).suffix.casefold() in IMAGE_EXTS:
            candidates = self._by_filename.get(key, set())
        else:
            candidates = self._by_stem.get(key, set())
        if len(candidates) > 1:
            raise AmbiguousTextureError(name, candidates)
        return next(iter(candidates)) if candidates else None


_CHANNELS = {
    "_MainTex": "d", "_LightTex": "n",
    "_OtherDataTex": "m", "_OtherDataTex2": "a",
}
_ATLAS_ROLES = frozenset({"body", "hair", "wing"})
_FACE_ROLES = frozenset({"face", "eye", "eyebrow"})


def _tokens(name: str) -> list[str]:
    # Only structural words are used below. Character/name prefixes are never
    # compared, ranked, whitelisted or used to break a candidate tie.
    spaced = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    return re.findall(r"[^\W_]+", spaced.casefold())


def _role_token(token):
    match = re.fullmatch(r"(body|hair|wing|face|eye|eyes|eyebrow|eyebrows)(\d*)", token)
    if not match:
        return None
    role, number = match.groups()
    return {"eyes": "eye", "eyebrows": "eyebrow"}.get(role, role), number


def _family_number(tail):
    if not tail or tail == ["map"]:
        return ""
    joined = "".join(tail)
    match = re.fullmatch(r"(?:map)?(\d+)", joined)
    return match.group(1) if match else None


def _material_family(stem):
    tokens = _tokens(stem)
    while tokens and tokens[-1] in {"ui", "t"}:
        tokens.pop()
    if tokens[-2:] == ["hair", "shadow"] or tokens[-1:] == ["hairshadow"]:
        return "hair_shadow", ""
    # A role must be the structural suffix, not a word hidden in the arbitrary
    # character prefix. Unknown suffixes intentionally need caller evidence.
    for i in range(len(tokens) - 1, -1, -1):
        parsed = _role_token(tokens[i])
        if parsed:
            role, attached_number = parsed
            number = _family_number(tokens[i + 1:])
            if number is not None and not (attached_number and number):
                return role, attached_number or number
            return "", ""
    return "", ""


def _texture_family(path):
    tokens = _tokens(Path(path).stem)
    if not tokens or tokens[-1] not in _CHANNELS.values():
        return None
    channel = tokens.pop()
    for i in range(len(tokens) - 1, -1, -1):
        parsed = _role_token(tokens[i])
        if parsed and parsed[0] in _ATLAS_ROLES:
            role, attached_number = parsed
            number = _family_number(tokens[i + 1:])
            if number is not None and not (attached_number and number):
                return role, attached_number or number, tuple(tokens), channel
            return None
    return None


def _required_properties(role):
    if role == "hair_shadow":
        return set()
    required = {"_MainTex"} if role else set()
    if role in _ATLAS_ROLES:
        required.update(_CHANNELS)
    elif role == "face":
        required.add("_LightTex")
    return required


def _family_candidates(role, number, images):
    """Return channels only after selecting one whole atlas family.

    Different character prefixes, numbered atlases, duplicate extensions and
    duplicate files are not ranked away. An unnumbered material needs exactly
    one family of its role; Body_1 needs exactly one Body_Map1 family.
    """
    families = {}
    for path in images:
        parsed = _texture_family(path)
        if parsed is None:
            continue
        texture_role, texture_number, family, channel = parsed
        if texture_role != role or (number and texture_number != number):
            continue
        families.setdefault(family, {}).setdefault(channel, []).append(path)
    if len(families) == 1:
        channels = next(iter(families.values()))
        return {prop: sorted(channels.get(channel, []), key=lambda p: (p.casefold(), p))
                for prop, channel in _CHANNELS.items()}, True
    # Preserve every channel candidate for diagnostics even when a single
    # channel happens to have only one file in an otherwise ambiguous family.
    return {prop: sorted({path for channels in families.values()
                          for path in channels.get(channel, [])},
                         key=lambda p: (p.casefold(), p))
            for prop, channel in _CHANNELS.items()}, False


def _is_face_diffuse(path):
    tokens = _tokens(Path(path).stem)
    return bool(tokens and tokens[-1] == "d" and any(
        parsed and parsed[0] == "face" for parsed in map(_role_token, tokens[:-1])))


def _is_face_lightmap(path):
    tokens = _tokens(Path(path).stem)
    return bool(tokens and tokens[-1] == "lightmap" and "face" in tokens[:-1])


def _inference_candidates(prop, role, number, images, atlas):
    if role in _ATLAS_ROLES and prop in _CHANNELS:
        channels, unique_family = atlas
        return channels.get(prop, []), unique_family, f"{role} atlas family {number or '(unnumbered)'}"
    if role in _FACE_ROLES and prop == "_MainTex":
        return [p for p in images if _is_face_diffuse(p)], True, "Face diffuse family"
    if role == "face" and prop == "_LightTex":
        # This is a generic exported asset name, not a character table. Other
        # face maps and multiple copies require explicit/caller evidence.
        # Male/Female and numbered variants (Male_Face_01_Lightmap ...) share one
        # token pattern; more than one match stays ambiguous (never ranked).
        return [p for p in images if _is_face_lightmap(p)], True, "Face lightmap"
    if "matcap" in prop.casefold():
        # Even a lone image cannot identify several differently numbered
        # unnamed MatCap properties. Never assign one by numeric order/ID.
        return [p for p in images if "matcap" in Path(p).stem.casefold()], False, "unnamed MatCap binding"
    return [], False, "no supported structural family"


def resolve_catalog(root) -> dict:
    """Resolve a resource catalogue without Blender or image decoding.

    The result always has ``materials``, ``index``, ``warnings`` and ``errors``.
    Binding failures do not drop material entries: callers may provide PMX pixel
    atlas evidence or explicitly disable unresolved optional MatCaps. Only exact
    names and unique role/atlas families are accepted. Pointer IDs are preserved
    verbatim for diagnostics, never decoded or matched across material files.
    ``scan_materials`` remains the original strict parser-only API.
    """
    index = TextureIndex()
    result = {"materials": [], "index": index, "warnings": [], "errors": []}
    try:
        path = Path(normalize_root(root))
        index.add_dir(path)
        files = sorted((p for p in _walk_files(path) if p.suffix.casefold() == ".json"),
                       key=lambda p: (str(p).casefold(), str(p)))
    except (OSError, ValueError) as exc:
        result["errors"].append(f"Resource catalogue: {exc}")
        return result
    images = sorted({p for paths in index._by_stem.values() for p in paths},
                    key=lambda p: (p.casefold(), p))
    for file in files:
        try:
            material = MaterialData(file)
        except (OSError, MaterialFormatError) as exc:
            result["errors"].append(str(exc))
            continue
        result["materials"].append(material)
        role, number = _material_family(material.stem)
        required = _required_properties(role)
        # Unknown material roles still owe their explicitly requested main map.
        if "_MainTex" in material.references:
            required.add("_MainTex")
        atlas = _family_candidates(role, number, images) if role in _ATLAS_ROLES else ({}, False)
        material.textures = {}
        material.resolution = {}
        material.unresolved = {}
        for prop in sorted(set(material.references) | required):
            raw = material.references.get(prop)
            if raw is None:
                env = material.texenvs.get(prop)
                raw = env.get("m_Texture") if isinstance(env, Mapping) else None
            # Only a retained non-null reference can supply a Name. A null
            # environment may still carry a stale Name in its diagnostic raw.
            name = raw.get("Name") if prop in material.references else None
            optional = prop not in required
            candidates = []
            if name:
                # A present but broken/ambiguous explicit name is never silently
                # replaced with a different inferred atlas.
                try:
                    resolved = index.find(name)
                except AmbiguousTextureError as exc:
                    candidates = list(exc.candidates)
                    reason = "explicit Name is ambiguous"
                else:
                    if resolved:
                        material.textures[prop] = name
                        material.resolution[prop] = {
                            "method": "explicit", "path": resolved, "reference": name,
                        }
                        continue
                    reason = "explicit Name was not found in the texture index"
            elif prop not in material.references:
                reason = "required texture reference is null or absent"
            else:
                candidates, unique_family, family = _inference_candidates(
                    prop, role, number, images, atlas)
                if unique_family and len(candidates) == 1:
                    resolved = candidates[0]
                    material.textures[prop] = resolved
                    material.resolution[prop] = {
                        "method": "inferred", "path": resolved, "family": family,
                        "evidence": "unique structural role/family tokens",
                    }
                    result["warnings"].append(
                        f"{material.stem} {prop}: inferred {family} -> {resolved}")
                    continue
                if "matcap" in prop.casefold():
                    reason = "unnamed MatCap has no verified property binding; disable it or provide an override"
                elif candidates:
                    reason = "structural texture family is ambiguous"
                else:
                    reason = f"no candidate for {family}"
            material.unresolved[prop] = {
                "raw": dict(raw) if isinstance(raw, Mapping) else raw,
                "candidates": candidates, "optional": optional, "reason": reason,
            }
            severity = "warnings" if optional else "errors"
            detail = f"; candidates: {'; '.join(candidates)}" if candidates else ""
            result[severity].append(
                f"{material.stem} {prop}: {reason}{detail} [{material.path}]")
    return result
