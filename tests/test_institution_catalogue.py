import csv
import io
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes.institution_catalogue import router
from app.catalogues import institutions as catalogue
from app.schemas.education import EducationUpdateRequest
from scripts.import_institution_catalogue import build


@pytest.fixture(autouse=True)
def reset_cache():
    catalogue.load_catalogue.cache_clear()
    catalogue.search_index.cache_clear()
    yield
    catalogue.load_catalogue.cache_clear()
    catalogue.search_index.cache_clear()


@pytest.mark.parametrize(('raw', 'expected'), [
    ('  IIT   College ,Delhi ', 'IIT College, Delhi'),
    ('GOVERNMENT COLLEGE OF ENGINEERING', 'Government College of Engineering'),
    ('AIIMS IIT D.V. COLLEGE', 'AIIMS IIT D.V. College'),
    ('St. Mary’s College', 'St. Mary’s College'),
])
def test_safe_normalization(raw, expected):
    assert catalogue.clean_text(raw) == expected
    assert catalogue.clean_text(expected) == expected


def test_archive_dedup_requires_full_location_equivalence(tmp_path):
    csv_text = io.StringIO()
    writer = csv.writer(csv_text)
    writer.writerow(['id', 'state', 'name', 'address_line1', 'address_line2',
                     'city', 'district', 'pin_code'])
    writer.writerow(['1', 'Delhi', 'TEST COLLEGE', 'Road A', '', 'Delhi', 'Delhi', '100001'])
    writer.writerow(['2', 'Delhi', 'test college', 'road a', '', 'Delhi', 'Delhi', '100001'])
    writer.writerow(['3', 'Delhi', 'TEST COLLEGE', 'Road B', '', 'Delhi', 'Delhi', '100001'])
    path = tmp_path / 'fixture.zip'
    with ZipFile(path, 'w') as archive:
        archive.writestr('colleges-api-master/data/colleges.csv', csv_text.getvalue())
        archive.writestr('irrelevant.sql', 'NEVER EXECUTE')
    data = build(path)
    assert len(data['institutions']) == 2
    assert data['provenance']['equivalent_rows_removed'] == 1
    assert build(path) == data
    assert sorted(len(r['source_ids']) for r in data['institutions']) == [1, 2]


def test_real_catalogue_load_and_search():
    provenance, rows = catalogue.load_catalogue()
    assert provenance['input_rows'] == 43121
    assert len(rows) == 43119
    assert len({r['id'] for r in rows}) == len(rows)
    sample = next(r for r in rows if 'MERCHANT' in r['name'])
    result = catalogue.search_institutions(sample['name'], sample['state'], sample['district'])
    assert sample['id'] in [r['id'] for r in result['items']]
    assert (catalogue.search_institutions(sample['name'].swapcase())['total']
            == catalogue.search_institutions(sample['name'])['total'])


def test_search_pagination():
    first = catalogue.search_institutions('college', limit=2)
    next_page = catalogue.search_institutions('college', limit=2, offset=2)
    assert len(first['items']) == len(next_page['items']) == 2
    assert not ({r['id'] for r in first['items']} & {r['id'] for r in next_page['items']})
    assert first['total'] == next_page['total']


@pytest.mark.parametrize('query', ['', '   ', '!!!', 'NotARealInstitution987654321'])
def test_no_results_keep_manual_fallback(query):
    result = catalogue.search_institutions(query)
    assert result['items'] == []
    assert result['manual_entry_allowed'] is True


def test_missing_catalogue_is_safe_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(catalogue, 'DATA_PATH', tmp_path / 'missing.json')
    result = catalogue.search_institutions('college')
    assert result['available'] is False
    assert result['manual_entry_allowed'] is True


def test_manual_saved_value_is_not_rewritten_or_membership_validated():
    value = 'My unlisted overseas institution (custom)'
    assert EducationUpdateRequest(institution_name=value).institution_name == value
    assert catalogue.search_institutions(value)['total'] == 0


@pytest.mark.parametrize('params,status', [
    ({'q': 'college', 'limit': 2}, 200),
    ({'limit': 51}, 422), ({'limit': 0}, 422), ({'offset': -1}, 422),
    ({'q': 'x' * 161}, 422),
    ({'search': 'college', 'page': 2, 'limit': 2}, 200),
    ({'page': 0}, 422), ({'page': 2002}, 422),
    ({'page': 1, 'offset': 0}, 422),
    ({'q': 'a', 'search': 'b'}, 422),
])
def test_shared_public_api_contract(params, status):
    app = FastAPI()
    app.include_router(router, prefix='/api/v1')
    with TestClient(app) as client:
        response = client.get('/api/v1/catalogues/institutions', params=params)
    assert response.status_code == status
    if status == 200:
        body = response.json()
        assert body['manual_entry_allowed']
        assert len(body['items']) == 2
        assert set(body['items'][0]) == {'id', 'name', 'state', 'district', 'city'}


def test_page_and_search_alias_equivalence():
    app = FastAPI()
    app.include_router(router, prefix='/api/v1')
    with TestClient(app) as client:
        page = client.get('/api/v1/catalogues/institutions',
                          params={'search': 'college', 'page': 2, 'limit': 3}).json()
        offset = client.get('/api/v1/catalogues/institutions',
                            params={'q': 'college', 'offset': 3, 'limit': 3}).json()
    assert page == offset
    assert page['page'] == 2 and page['offset'] == 3
