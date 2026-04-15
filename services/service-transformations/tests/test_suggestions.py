from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_transformations.router import build_router
from service_transformations.suggestion_rules import build_suggestions_for_dataset
from shared_python.errors import NotFoundError, UnauthorizedError, register_exception_handlers


def _user() -> UserRead:
    return UserRead(
        id=uuid.uuid4(),
        username='tester',
        role='admin',
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _clean_profile() -> dict:
    return {
        'row_count': 100,
        'column_count': 2,
        'duplicate_row_count': 0,
        'duplicate_row_percentage': 0.0,
        'columns': [
            {
                'name': 'id',
                'inferred_type': 'int',
                'null_percentage': 0.0,
                'unique_count': 100,
                'sample_values': [1, 2],
            },
            {
                'name': 'x',
                'inferred_type': 'float',
                'null_percentage': 0.0,
                'unique_count': 50,
                'sample_values': [1.0, 2.0],
            },
        ],
        'quality_flags': {
            'high_null_columns': [],
            'constant_value_columns': [],
            'potential_id_columns': [],
            'mixed_type_suspicions': [],
        },
    }


def test_suggestions_clean_dataset_minimal() -> None:
    ds = uuid.uuid4()
    pj = uuid.uuid4()
    schema = {'columns': [{'name': 'id', 'inferred_type': 'int', 'nullable': False}], 'ordered_columns': ['id']}
    out = build_suggestions_for_dataset(
        dataset_id=ds,
        project_id=pj,
        schema_json=schema,
        profile_json=_clean_profile(),
        preview_json={'rows': [], 'columns': ['id', 'x']},
    )
    assert not any(s.step_type == 'remove_duplicates' for s in out)
    assert not any(s.step_type == 'fill_nulls' for s in out)


def test_duplicate_suggestion_when_profile_shows_dupes() -> None:
    ds = uuid.uuid4()
    pj = uuid.uuid4()
    profile = _clean_profile()
    profile['duplicate_row_count'] = 5
    profile['duplicate_row_percentage'] = 5.0
    out = build_suggestions_for_dataset(
        dataset_id=ds,
        project_id=pj,
        schema_json={'columns': [], 'ordered_columns': []},
        profile_json=profile,
        preview_json=None,
    )
    dup = [s for s in out if s.step_type == 'remove_duplicates']
    assert len(dup) == 1
    assert dup[0].config == {'keep': 'first'}


def test_fill_nulls_suggestion_for_moderate_nulls() -> None:
    ds = uuid.uuid4()
    pj = uuid.uuid4()
    profile = _clean_profile()
    profile['columns'] = [
        {
            'name': 'amount',
            'inferred_type': 'float',
            'null_percentage': 12.0,
            'std_value': 1.2,
            'sample_values': [1.0, None],
        }
    ]
    out = build_suggestions_for_dataset(
        dataset_id=ds,
        project_id=pj,
        schema_json=None,
        profile_json=profile,
        preview_json=None,
    )
    fills = [s for s in out if s.step_type == 'fill_nulls' and 'amount' in str(s.config)]
    assert fills
    assert fills[0].config['strategy'] in {'mean', 'median'}


def test_drop_columns_for_constant_and_extreme_null() -> None:
    ds = uuid.uuid4()
    pj = uuid.uuid4()
    profile = _clean_profile()
    profile['quality_flags']['constant_value_columns'] = ['dead']
    profile['columns'].append(
        {
            'name': 'dead',
            'inferred_type': 'string',
            'null_percentage': 0.0,
            'unique_count': 1,
            'sample_values': ['x'],
        }
    )
    profile['columns'].append(
        {
            'name': 'emptyish',
            'inferred_type': 'string',
            'null_percentage': 95.0,
            'unique_count': 2,
            'sample_values': ['a', None],
        }
    )
    out = build_suggestions_for_dataset(
        dataset_id=ds,
        project_id=pj,
        schema_json={'ordered_columns': ['id', 'x', 'dead', 'emptyish'], 'columns': []},
        profile_json=profile,
        preview_json=None,
    )
    drops = [s for s in out if s.step_type == 'drop_columns']
    assert drops
    cols = set(drops[0].config.get('columns', []))
    assert 'dead' in cols
    assert 'emptyish' in cols


def _build_client():
    db = object()

    def get_db():
        return db

    def get_current_user():
        return _user()

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_router(get_db, get_current_user))
    return TestClient(app), db


@patch('service_transformations.suggestions.get_dataset_model_for_project')
@patch('service_transformations.suggestions.ensure_owned_project')
def test_suggestions_endpoint_returns_payload(_ensure, get_dataset) -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    get_dataset.return_value = SimpleNamespace(
        id=dataset_id,
        schema_json={'columns': [{'name': 'a', 'inferred_type': 'string', 'nullable': True}], 'ordered_columns': ['a']},
        profile_json={
            'row_count': 10,
            'column_count': 1,
            'duplicate_row_count': 2,
            'duplicate_row_percentage': 20.0,
            'columns': [
                {
                    'name': 'a',
                    'inferred_type': 'string',
                    'null_percentage': 5.0,
                    'unique_count': 5,
                    'sample_values': [' x '],
                }
            ],
            'quality_flags': {
                'high_null_columns': [],
                'constant_value_columns': [],
                'potential_id_columns': [],
                'mixed_type_suspicions': [],
            },
        },
        preview_json={'columns': ['a'], 'rows': [{'a': ' hi '}]},
    )
    client, _ = _build_client()
    r = client.get(f'/projects/{project_id}/datasets/{dataset_id}/suggestions')
    assert r.status_code == 200
    body = r.json()
    assert body['dataset_id'] == str(dataset_id)
    assert body['project_id'] == str(project_id)
    assert isinstance(body['suggestions'], list)
    assert len(body['suggestions']) >= 1


@patch('service_transformations.suggestions.ensure_owned_project', side_effect=NotFoundError('Project not found.'))
def test_suggestions_endpoint_requires_project_access(_ensure) -> None:
    client, _ = _build_client()
    r = client.get(f'/projects/{uuid.uuid4()}/datasets/{uuid.uuid4()}/suggestions')
    assert r.status_code == 404


def test_suggestions_endpoint_unauthenticated() -> None:
    def get_db():
        return object()

    def get_current_user():
        raise UnauthorizedError('Authentication required.')

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_router(get_db, get_current_user))
    client = TestClient(app)
    r = client.get(f'/projects/{uuid.uuid4()}/datasets/{uuid.uuid4()}/suggestions')
    assert r.status_code == 401
