"""Tests for the SAHJONY Envios (Houston → Cuba) quote intake API."""
import re

from pydantic import ValidationError

from envios_api import (
    CargoType,
    EnviosIntakeIn,
    build_reference,
    _validate_branch,
)


REFERENCE_RE = re.compile(r'^ENV-2026-[A-Z0-9]{6}$')


def _base(**kw):
    d = dict(
        full_name='Juan Pérez',
        whatsapp='+17835550199',
        cargo_type='contenedor_fcl',
        origin_detail='1234 Main St, Houston, TX',
        origin_mode='pickup',
        cuba_province='La Habana',
        cuba_city='La Habana',
        container_size='40',
        goods_description='Muebles de madera',
        preferred_language='es',
    )
    d.update(kw)
    return EnviosIntakeIn(**d)


def test_reference_format_and_uniqueness():
    refs = {build_reference() for _ in range(500)}
    assert len(refs) == 500, 'reference collisions detected'
    assert all(REFERENCE_RE.match(r) for r in refs)


def test_reference_year_prefix():
    assert build_reference().startswith('ENV-2026-')


def test_fcl_intake_valid():
    p = _base()
    assert p.cargo_type == 'contenedor_fcl'
    assert p.container_size == '40'


def test_fcl_requires_container_size():
    p = _base(container_size=None)
    try:
        _validate_branch(p)
    except Exception as exc:
        assert getattr(exc, 'status_code', None) == 422
        return
    raise AssertionError('FCL without container size must be rejected')


def test_pallet_intake_valid():
    p = _base(cargo_type='pallet_consolidado', container_size=None,
              pieces=4, weight_kg=320.5, dimensions_cm='120x100x150')
    assert p.cargo_type == 'pallet_consolidado'
    assert p.pieces == 4
    assert p.weight_kg == 320.5


def test_pallet_requires_pieces():
    p = _base(cargo_type='pallet_consolidado', container_size=None, pieces=None)
    try:
        _validate_branch(p)
    except Exception as exc:
        assert getattr(exc, 'status_code', None) == 422
        return
    raise AssertionError('pallet intake without pieces must be rejected')


def test_honeypot_field_exists_on_model():
    p = _base(website='http://spam.example')
    assert p.website == 'http://spam.example'


def test_invalid_cargo_type_rejected():
    try:
        _base(cargo_type='barco')  # type: ignore[arg-type]
    except ValidationError:
        return
    raise AssertionError('unknown cargo_type must fail validation')


def test_cargo_type_is_freight_only():
    # This app covers FCL containers + pallets; cars live in the car app.
    assert set(CargoType.__args__) == {'contenedor_fcl', 'pallet_consolidado'}


def test_name_min_length_enforced():
    try:
        _base(full_name='A')
    except ValidationError:
        return
    raise AssertionError('single-char names must fail validation')


def test_api_module_has_no_invented_pricing():
    # Guardrail: the intake module must never contain ocean freight rates,
    # transit times, schedules, or named Houston→Cuba carriers. We check for
    # data-like patterns (not plain words like "schedule" in prose).
    src = open('envios_api.py', encoding='utf-8').read()
    data_patterns = [
        r'\$\s?\d[\d.,]*\s*/\s*(lb|kg|contenedor|container)',  # freight rates
        r'\b\d+\s*(a|to|-)\s*\d+\s*(d[ií]as|days|semanas)\b',   # transit-time windows
        r'\b(seaboard|crowley|maersk|hapag|msc|cma cgm)\b',     # named carriers
    ]
    for pat in data_patterns:
        assert not re.search(pat, src, re.IGNORECASE), f'invented fact marker present: {pat}'
