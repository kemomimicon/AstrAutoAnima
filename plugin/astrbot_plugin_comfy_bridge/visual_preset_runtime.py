"""Local visual catalog compiler. No network, inference, or workflow mutations."""
from __future__ import annotations

import copy
import json
from pathlib import Path


class VisualPresetError(ValueError):
    pass


class VisualPresetCatalog:
    def __init__(self, data: dict):
        self.data = copy.deepcopy(data)
        self.by_id: dict[str, dict] = {}
        for category in ('lighting', 'material'):
            rows = data.get(f'{category}_presets')
            if not isinstance(rows, list) or not rows:
                raise VisualPresetError(f'Missing {category} catalog')
            for row in rows:
                if not isinstance(row, dict):
                    raise VisualPresetError('Preset must be an object')
                ident = row.get('id')
                if not isinstance(ident, str) or not ident or ident in self.by_id:
                    raise VisualPresetError('Missing or duplicate preset ID')
                if row.get('category') != category or not isinstance(row.get('prompt'), str) or not row['prompt'].strip():
                    raise VisualPresetError(f'Invalid prompt/category: {ident}')
                role = row.get('role') if category == 'lighting' else row.get('exclusive_group')
                allowed = {'key', 'effect'} if category == 'lighting' else {'primary_material', 'detail_material', 'surface_effect'}
                if role not in allowed:
                    raise VisualPresetError(f'Invalid role: {ident}')
                avoid = row.get('avoid_with', [])
                if not isinstance(avoid, list) or any(not isinstance(x, str) for x in avoid):
                    raise VisualPresetError(f'Invalid conflicts: {ident}')
                self.by_id[ident] = copy.deepcopy(row)
        for row in self.by_id.values():
            if any(x not in self.by_id for x in row.get('avoid_with', [])):
                raise VisualPresetError(f"Unknown conflict ID: {row['id']}")

    def _select(self, ident, category, role):
        if ident in (None, '', 'none', '无'):
            return None
        if not isinstance(ident, str):
            raise VisualPresetError('Each slot accepts one preset ID')
        row = self.by_id.get(ident)
        if not row or row['category'] != category:
            raise VisualPresetError(f'Unknown {category} preset: {ident}')
        actual = row.get('role') if category == 'lighting' else row.get('exclusive_group')
        if actual != role:
            raise VisualPresetError(f'Preset is not {role}: {ident}')
        return row

    @staticmethod
    def _compile(rows):
        rows = [r for r in rows if r]
        selected = {r['id'] for r in rows}
        for row in rows:
            conflicts = selected.intersection(row.get('avoid_with', []))
            if conflicts:
                raise VisualPresetError(f"Conflicting presets: {row['id']} / {', '.join(sorted(conflicts))}")
        # Catalog strings remain untouched; only the emitted comma-separated
        # fragments are deduplicated, retaining their original spelling/order.
        seen, terms = set(), []
        for row in rows:
            for raw in row['prompt'].split(','):
                term = raw.strip()
                key = term.casefold()
                if term and key not in seen:
                    seen.add(key)
                    terms.append(term)
        return ', '.join(terms)

    def compile_lighting(self, key_id=None, effect_id=None):
        return self._compile([
            self._select(key_id, 'lighting', 'key'),
            self._select(effect_id, 'lighting', 'effect'),
        ])

    def compile_material(self, primary_id=None, detail_ids=None, surface_effect_id=None):
        if detail_ids is None:
            detail_ids = []
        if not isinstance(detail_ids, list) or len(detail_ids) > 2:
            raise VisualPresetError('At most two detail materials per target')
        return self._compile([
            self._select(primary_id, 'material', 'primary_material'),
            *(self._select(x, 'material', 'detail_material') for x in detail_ids),
            self._select(surface_effect_id, 'material', 'surface_effect'),
        ])


def load_visual_catalog(path: Path) -> tuple[VisualPresetCatalog | None, str]:
    """Callers must display/log the warning and disable this optional module."""
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict):
            raise VisualPresetError('Catalog must be an object')
        return VisualPresetCatalog(data), ''
    except (OSError, ValueError, TypeError) as exc:
        return None, f'光影/材质预设不可用（基础生图不受影响）：{exc}'


def compile_visual_options(options: dict, path: Path) -> str:
    keys = ('lighting_key', 'lighting_effect', 'material_primary', 'material_details', 'material_surface')
    if not any(options.get(key) for key in keys):
        return ''
    catalog, warning = load_visual_catalog(path)
    if catalog is None:
        raise VisualPresetError(warning)
    details = options.get('material_details', '')
    details = [x for x in details.split(',') if x] if isinstance(details, str) else details
    lighting = catalog.compile_lighting(options.get('lighting_key'), options.get('lighting_effect'))
    material = catalog.compile_material(options.get('material_primary'), details, options.get('material_surface'))
    return ', '.join(value for value in (lighting, material) if value)
