from __future__ import annotations

import re
import uuid
from typing import Any

from service_transformations.suggestion_schemas import TransformationSourceSignal, TransformationSuggestion

_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')

_STRING_LIKE_SCHEMA = frozenset({'string', 'object', 'mixed'})
_NUMERIC_TYPES = frozenset({'int', 'float'})
_FILL_NULL_MAX_PCT = 55.0
_DROP_NULL_MIN_PCT = 90.0
_DATE_NAME_PATTERN = re.compile(
    r'(date|time|timestamp|datetime|created|updated|modified)',
    re.IGNORECASE,
)


def _sid(dataset_id: uuid.UUID, *parts: str) -> uuid.UUID:
    raw = ':'.join(str(p) for p in (dataset_id, *parts))
    return uuid.uuid5(_NS, raw)


def _trim_strings_suggestion(
    dataset_id: uuid.UUID,
    schema_json: dict[str, Any] | None,
    profile_json: dict[str, Any] | None,
    preview_json: dict[str, Any] | None,
) -> TransformationSuggestion | None:
    columns_schema = (schema_json or {}).get('columns') or []
    string_cols: list[str] = []
    for col in columns_schema:
        if not isinstance(col, dict):
            continue
        name = col.get('name')
        inf = str(col.get('inferred_type', '')).lower()
        if not isinstance(name, str) or not name:
            continue
        if inf in _STRING_LIKE_SCHEMA or inf in {'object', 'mixed'}:
            string_cols.append(name)

    if not string_cols and profile_json:
        for pc in profile_json.get('columns') or []:
            if not isinstance(pc, dict):
                continue
            name = pc.get('name')
            inf = str(pc.get('inferred_type', '')).lower()
            if isinstance(name, str) and inf in _STRING_LIKE_SCHEMA | {'object', 'mixed'}:
                if name not in string_cols:
                    string_cols.append(name)

    if not string_cols:
        return None

    whitespace_hint = False
    rows = (preview_json or {}).get('rows') or []
    if isinstance(rows, list) and rows:
        for row in rows[:50]:
            if not isinstance(row, dict):
                continue
            for col in string_cols:
                val = row.get(col)
                if isinstance(val, str) and val != val.strip():
                    whitespace_hint = True
                    break
            if whitespace_hint:
                break

    confidence: Any = 'medium'
    explanation = (
        'String-like columns may carry leading or trailing whitespace; trimming is a safe normalization step.'
    )
    signals: list[TransformationSourceSignal] = [
        TransformationSourceSignal(signal='string_like_columns', detail='schema/profile', value=string_cols)
    ]
    if whitespace_hint:
        confidence = 'high'
        explanation = (
            'Preview values show leading or trailing whitespace on at least one string column; trim those values.'
        )
        signals.append(TransformationSourceSignal(signal='preview_whitespace', detail='preview_json rows'))

    return TransformationSuggestion(
        suggestion_id=_sid(dataset_id, 'trim_strings', ','.join(sorted(string_cols))),
        step_type='trim_strings',
        title='Trim whitespace on text columns',
        explanation=explanation,
        confidence=confidence,
        config={'columns': string_cols},
        source_signals=signals,
        priority=10,
    )


def _remove_duplicates_suggestion(dataset_id: uuid.UUID, profile_json: dict[str, Any] | None) -> TransformationSuggestion | None:
    if not profile_json:
        return None
    dup = int(profile_json.get('duplicate_row_count') or 0)
    if dup <= 0:
        return None
    return TransformationSuggestion(
        suggestion_id=_sid(dataset_id, 'remove_duplicates'),
        step_type='remove_duplicates',
        title='Remove duplicate rows',
        explanation=(
            f'Profile reports {dup} duplicate row(s) ({profile_json.get("duplicate_row_percentage", 0)}% of rows). '
            'Deduplicate while keeping the first occurrence of each row.'
        ),
        confidence='high' if dup > 1 else 'medium',
        config={'keep': 'first'},
        source_signals=[
            TransformationSourceSignal(
                signal='duplicate_row_count',
                value=dup,
            ),
            TransformationSourceSignal(
                signal='duplicate_row_percentage',
                value=profile_json.get('duplicate_row_percentage'),
            ),
        ],
        priority=40,
    )


def _fill_nulls_suggestions(dataset_id: uuid.UUID, profile_json: dict[str, Any] | None) -> list[TransformationSuggestion]:
    if not profile_json:
        return []
    high_null = set(profile_json.get('quality_flags', {}).get('high_null_columns') or [])
    out: list[TransformationSuggestion] = []
    for col in profile_json.get('columns') or []:
        if not isinstance(col, dict):
            continue
        name = col.get('name')
        if not isinstance(name, str) or not name:
            continue
        null_pct = float(col.get('null_percentage') or 0.0)
        if null_pct <= 0 or null_pct > _FILL_NULL_MAX_PCT:
            continue
        if name in high_null and null_pct >= 50.0:
            continue
        inf = str(col.get('inferred_type', '')).lower()
        if inf in _NUMERIC_TYPES:
            strategy = 'median' if col.get('std_value') and float(col.get('std_value') or 0) > 0 else 'mean'
            out.append(
                TransformationSuggestion(
                    suggestion_id=_sid(dataset_id, 'fill_nulls', name, strategy),
                    step_type='fill_nulls',
                    title=f'Fill nulls in `{name}` ({strategy})',
                    explanation=(
                        f'Column `{name}` has {null_pct:.1f}% null values; '
                        f'numeric columns can be imputed using the {strategy} of non-null values.'
                    ),
                    confidence='medium' if null_pct < 25 else 'low',
                    config={
                        'strategy': strategy,
                        'columns': [name],
                    },
                    source_signals=[
                        TransformationSourceSignal(signal='null_percentage', value=null_pct),
                        TransformationSourceSignal(signal='inferred_type', value=inf),
                    ],
                    priority=30,
                )
            )
        elif inf in {'string', 'object', 'mixed', 'bool'}:
            out.append(
                TransformationSuggestion(
                    suggestion_id=_sid(dataset_id, 'fill_nulls', name, 'mode'),
                    step_type='fill_nulls',
                    title=f'Fill nulls in `{name}` (mode)',
                    explanation=(
                        f'Column `{name}` has {null_pct:.1f}% null values; '
                        'for categorical text, the most frequent non-null value (mode) is a practical default.'
                    ),
                    confidence='medium' if null_pct < 25 else 'low',
                    config={
                        'strategy': 'mode',
                        'columns': [name],
                    },
                    source_signals=[
                        TransformationSourceSignal(signal='null_percentage', value=null_pct),
                        TransformationSourceSignal(signal='inferred_type', value=inf),
                    ],
                    priority=30,
                )
            )
    return out


def _drop_columns_suggestion(dataset_id: uuid.UUID, profile_json: dict[str, Any] | None) -> TransformationSuggestion | None:
    if not profile_json:
        return None
    qf = profile_json.get('quality_flags') or {}
    constant = list(qf.get('constant_value_columns') or [])
    drop_for_null: list[str] = []
    for col in profile_json.get('columns') or []:
        if not isinstance(col, dict):
            continue
        name = col.get('name')
        if not isinstance(name, str):
            continue
        null_pct = float(col.get('null_percentage') or 0.0)
        if null_pct >= _DROP_NULL_MIN_PCT:
            drop_for_null.append(name)
    to_drop = sorted(set(constant) | set(drop_for_null))
    if not to_drop:
        return None
    return TransformationSuggestion(
        suggestion_id=_sid(dataset_id, 'drop_columns', ','.join(to_drop)),
        step_type='drop_columns',
        title='Drop low-information columns',
        explanation=(
            'Some columns are constant (single distinct value) or almost entirely null; dropping them reduces noise. '
            'Review before applying in production.'
        ),
        confidence='medium' if constant else 'low',
        config={'columns': to_drop},
        source_signals=[
            TransformationSourceSignal(signal='constant_value_columns', value=constant),
            TransformationSourceSignal(signal='very_high_null_columns', value=drop_for_null),
        ],
        priority=50,
    )


def _looks_numeric_string(samples: list[Any]) -> bool:
    if not samples:
        return False
    ok = 0
    for s in samples[:8]:
        if s is None:
            continue
        try:
            float(str(s).replace(',', '').strip())
            ok += 1
        except (TypeError, ValueError):
            continue
    return ok >= 2


def _looks_bool_string(samples: list[Any]) -> bool:
    truthy = {'true', 'false', 'yes', 'no', '1', '0', 'y', 'n'}
    hits = 0
    for s in samples[:8]:
        if s is None:
            continue
        if str(s).strip().lower() in truthy:
            hits += 1
    return hits >= 2


def _cast_column_types_suggestions(dataset_id: uuid.UUID, profile_json: dict[str, Any] | None) -> list[TransformationSuggestion]:
    if not profile_json:
        return []
    mixed = set(profile_json.get('quality_flags', {}).get('mixed_type_suspicions') or [])
    out: list[TransformationSuggestion] = []
    for col in profile_json.get('columns') or []:
        if not isinstance(col, dict):
            continue
        name = col.get('name')
        if not isinstance(name, str) or not name:
            continue
        inf = str(col.get('inferred_type', '')).lower()
        samples = col.get('sample_values') or []
        if not isinstance(samples, list):
            samples = []
        if name in mixed:
            out.append(
                TransformationSuggestion(
                    suggestion_id=_sid(dataset_id, 'cast', name, 'string'),
                    step_type='cast_column_types',
                    title=f'Normalize type for `{name}`',
                    explanation=(
                        f'Column `{name}` is flagged as mixed-type; casting to string preserves values while '
                        'stabilizing downstream transforms.'
                    ),
                    confidence='medium',
                    config={'mappings': {name: 'string'}},
                    source_signals=[
                        TransformationSourceSignal(signal='mixed_type_suspicion', value=name),
                    ],
                    priority=15,
                )
            )
            continue
        if inf == 'string' and _looks_numeric_string(samples):
            target = 'float' if any('.' in str(s) for s in samples if s is not None) else 'int'
            out.append(
                TransformationSuggestion(
                    suggestion_id=_sid(dataset_id, 'cast', name, target),
                    step_type='cast_column_types',
                    title=f'Cast `{name}` to {target}',
                    explanation=(
                        'Sample values look numeric but the column is stored as text; casting enables numeric transforms.'
                    ),
                    confidence='low',
                    config={'mappings': {name: target}},
                    source_signals=[
                        TransformationSourceSignal(signal='numeric_like_strings', value=name),
                    ],
                    priority=15,
                )
            )
        elif inf == 'string' and _looks_bool_string(samples):
            out.append(
                TransformationSuggestion(
                    suggestion_id=_sid(dataset_id, 'cast', name, 'boolean'),
                    step_type='cast_column_types',
                    title=f'Cast `{name}` to boolean',
                    explanation='Sample values resemble boolean encodings (yes/no, true/false); cast for cleaner filtering.',
                    confidence='low',
                    config={'mappings': {name: 'boolean'}},
                    source_signals=[
                        TransformationSourceSignal(signal='boolean_like_strings', value=name),
                    ],
                    priority=15,
                )
            )
    return out


def _parse_dates_suggestions(dataset_id: uuid.UUID, profile_json: dict[str, Any] | None) -> list[TransformationSuggestion]:
    if not profile_json:
        return []
    out: list[TransformationSuggestion] = []
    for col in profile_json.get('columns') or []:
        if not isinstance(col, dict):
            continue
        name = col.get('name')
        if not isinstance(name, str) or not name:
            continue
        inf = str(col.get('inferred_type', '')).lower()
        if inf == 'datetime':
            continue
        name_match = bool(_DATE_NAME_PATTERN.search(name))
        samples = col.get('sample_values') or []
        sample_hint = False
        if isinstance(samples, list):
            for s in samples[:5]:
                if isinstance(s, str) and _DATE_NAME_PATTERN.search(s):
                    sample_hint = True
                    break
        if not name_match and not sample_hint:
            continue
        if inf not in {'string', 'object', 'mixed', 'empty'}:
            continue
        out.append(
            TransformationSuggestion(
                suggestion_id=_sid(dataset_id, 'parse_dates', name),
                step_type='parse_dates',
                title=f'Parse `{name}` as dates',
                explanation=(
                    'Column name or sample values suggest date/time content; parse to datetime for time-based logic.'
                ),
                confidence='medium' if name_match else 'low',
                config={'columns': [name], 'format': '', 'errors': 'coerce'},
                source_signals=[
                    TransformationSourceSignal(signal='column_name_pattern', value=name_match),
                    TransformationSourceSignal(signal='sample_date_like', value=sample_hint),
                ],
                priority=16,
            )
        )
    return out


def _select_columns_suggestion(
    dataset_id: uuid.UUID,
    schema_json: dict[str, Any] | None,
    profile_json: dict[str, Any] | None,
) -> TransformationSuggestion | None:
    """Only when many columns are obvious drops — suggest keeping the rest."""
    if not schema_json or not profile_json:
        return None
    ordered = list(schema_json.get('ordered_columns') or [])
    if len(ordered) < 12:
        return None
    qf = profile_json.get('quality_flags') or {}
    constant = set(qf.get('constant_value_columns') or [])
    high_null = set(qf.get('high_null_columns') or [])
    junk = constant | high_null
    if len(junk) < 6 or len(junk) < len(ordered) // 3:
        return None
    keep = [c for c in ordered if c not in junk]
    if len(keep) < 3:
        return None
    return TransformationSuggestion(
        suggestion_id=_sid(dataset_id, 'select_columns', str(len(keep))),
        step_type='select_columns',
        title='Narrow to informative columns',
        explanation=(
            'Many columns look constant or mostly null relative to the table width; selecting a focused column '
            'set can simplify downstream pipelines.'
        ),
        confidence='low',
        config={'columns': keep},
        source_signals=[
            TransformationSourceSignal(signal='constant_value_columns', value=sorted(constant)),
            TransformationSourceSignal(signal='high_null_columns', value=sorted(high_null)),
        ],
        priority=55,
    )


def build_suggestions_for_dataset(
    *,
    dataset_id: uuid.UUID,
    project_id: uuid.UUID,
    schema_json: dict[str, Any] | None,
    profile_json: dict[str, Any] | None,
    preview_json: dict[str, Any] | None,
) -> list[TransformationSuggestion]:
    _ = project_id
    collected: list[TransformationSuggestion] = []

    t = _trim_strings_suggestion(dataset_id, schema_json, profile_json, preview_json)
    if t:
        collected.append(t)

    collected.extend(_cast_column_types_suggestions(dataset_id, profile_json))
    collected.extend(_parse_dates_suggestions(dataset_id, profile_json))
    collected.extend(_fill_nulls_suggestions(dataset_id, profile_json))

    rd = _remove_duplicates_suggestion(dataset_id, profile_json)
    if rd:
        collected.append(rd)

    dc = _drop_columns_suggestion(dataset_id, profile_json)
    if dc:
        collected.append(dc)

    sc = _select_columns_suggestion(dataset_id, schema_json, profile_json)
    if sc:
        collected.append(sc)

    collected.sort(key=lambda s: (s.priority, s.step_type, str(s.suggestion_id)))
    return collected
