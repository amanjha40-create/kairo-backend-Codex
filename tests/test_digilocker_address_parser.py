"""Privacy-safe DRVLC address extraction contract tests."""

from __future__ import annotations

import pytest

from app.integrations.digilocker.education import parse_driving_licence_address_result


def address(**values: str) -> str:
    attributes = " ".join(f'{name}="{value}"' for name, value in values.items())
    return f"<Address {attributes}/>"


def drvlc_xml(*addresses: str, namespaced: bool = False, person_attributes: str = "") -> bytes:
    namespace = ' xmlns="urn:digilocker:certificate"' if namespaced else ""
    return (
        f'<Certificate{namespace} type="DRVLC">'
        '<IssuedBy><Organization name="Issuer">'
        '<Address type="official" line1="Issuer only" vtc="Issuer city" '
        'pin="100001" state="Issuer state" country="IN"/>'
        "</Organization></IssuedBy>"
        f'<IssuedTo><Person name="Synthetic" {person_attributes}>'
        f'{"".join(addresses)}'
        "</Person></IssuedTo>"
        "<CertificateData><DrivingLicense/></CertificateData>"
        "</Certificate>"
    ).encode()


FULL = {
    "type": "permanent",
    "line1": "Synthetic Line",
    "line2": "Synthetic Line Two",
    "house": "House 1",
    "landmark": "Synthetic Landmark",
    "locality": "Synthetic Locality",
    "vtc": "Synthetic City",
    "district": "Synthetic District",
    "pin": "400001",
    "state": "Synthetic State",
    "country": "IN",
}


def test_full_permanent_address_maps_official_drvlc_fields():
    result = parse_driving_licence_address_result(drvlc_xml(address(**FULL)))

    assert result.reason == "COMPLETE"
    assert result.selected_type == "permanent"
    assert result.address is not None
    assert result.address.address_line_1 == "House 1, Synthetic Line"
    assert result.address.address_line_2 == "Synthetic Line Two, Synthetic Landmark"
    assert result.address.locality == "Synthetic Locality"
    assert result.address.city == "Synthetic City"
    assert result.address.country == "IN"


def test_one_untyped_address_is_accepted():
    values = FULL | {"type": ""}
    result = parse_driving_licence_address_result(drvlc_xml(address(**values)))

    assert result.reason == "COMPLETE"
    assert result.selected_type == "untyped"


def test_permanent_address_wins_over_present_address():
    present = FULL | {"type": "present", "line1": "Present Line"}
    permanent = FULL | {"line1": "Permanent Line"}
    result = parse_driving_licence_address_result(
        drvlc_xml(address(**present), address(**permanent))
    )

    assert result.reason == "COMPLETE"
    assert result.address is not None
    assert "Permanent Line" in result.address.address_line_1


@pytest.mark.parametrize(
    "addresses",
    [
        (address(**(FULL | {"type": ""})), address(**(FULL | {"type": ""}))),
        (address(**FULL), address(**FULL)),
        (
            address(**(FULL | {"type": "present"})),
            address(**(FULL | {"type": "current"})),
        ),
    ],
)
def test_multiple_addresses_without_one_permanent_are_ambiguous(addresses):
    result = parse_driving_licence_address_result(drvlc_xml(*addresses))

    assert result.reason == "ADDRESS_AMBIGUOUS"
    assert result.address is None


def test_house_street_and_district_form_minimum_address():
    result = parse_driving_licence_address_result(
        drvlc_xml(
            address(
                type="permanent",
                house="House 1",
                street="Synthetic Street",
                locality="Synthetic Locality",
                district="Synthetic District",
                pin="400001",
                state="Synthetic State",
                country="IND",
            )
        )
    )

    assert result.reason == "COMPLETE"
    assert result.address is not None
    assert result.address.address_line_1 == "House 1, Synthetic Street"
    assert result.address.city == "Synthetic District"


def test_explicit_city_schema_is_supported():
    result = parse_driving_licence_address_result(
        drvlc_xml(
            address(
                line1="Synthetic Line",
                locality="Synthetic Locality",
                city="Synthetic City",
                state="Synthetic State",
                pin="400001",
                country="India",
            )
        )
    )

    assert result.reason == "COMPLETE"
    assert result.address is not None
    assert result.address.city == "Synthetic City"


@pytest.mark.parametrize("omitted", ["line2", "landmark"])
def test_optional_secondary_fields_may_be_absent(omitted):
    values = {key: value for key, value in FULL.items() if key != omitted}
    result = parse_driving_licence_address_result(drvlc_xml(address(**values)))

    assert result.reason == "COMPLETE"


def test_vtc_is_the_locality_and_city_fallback():
    values = {key: value for key, value in FULL.items() if key not in {"locality"}}
    result = parse_driving_licence_address_result(drvlc_xml(address(**values)))

    assert result.address is not None
    assert result.address.locality == result.address.city == "Synthetic City"


def test_district_is_the_last_city_fallback():
    values = {key: value for key, value in FULL.items() if key not in {"locality", "vtc"}}
    result = parse_driving_licence_address_result(drvlc_xml(address(**values)))

    assert result.address is not None
    assert result.address.locality is None
    assert result.address.city == "Synthetic District"


@pytest.mark.parametrize(
    "missing,expected",
    [("pin", "postal_code"), ("state", "state")],
)
def test_missing_required_field_has_stable_reason(missing, expected):
    values = {key: value for key, value in FULL.items() if key != missing}
    result = parse_driving_licence_address_result(drvlc_xml(address(**values)))

    assert result.reason == "REQUIRED_FIELD_MISSING"
    assert result.missing_fields == (expected,)


def test_malformed_address_xml_fails_closed():
    result = parse_driving_licence_address_result(b"<Certificate type='DRVLC'><IssuedTo>")

    assert result.reason == "MALFORMED_XML"
    assert result.address is None


def test_namespaced_alternate_schema_and_aliases_are_supported():
    xml = drvlc_xml(
        '<PermanentAddress addressLine1="Synthetic Line" addressLine2="Line Two" '
        'houseNo="House 1" landmark="Landmark" subDistrict="Synthetic Town" '
        'postalCode="400001" stateName="Synthetic State" countryCode="IND"/>',
        namespaced=True,
    )
    result = parse_driving_licence_address_result(xml)

    assert result.reason == "COMPLETE"
    assert result.selected_type == "permanent"
    assert result.address is not None
    assert result.address.city == "Synthetic Town"


def test_legacy_person_attribute_schema_is_supported():
    attributes = (
        'address="Synthetic Line" district="Synthetic District" '
        'state="Synthetic State" pincode="400001" country="IN"'
    )
    result = parse_driving_licence_address_result(
        drvlc_xml(person_attributes=attributes)
    )

    assert result.reason == "COMPLETE"
    assert result.selected_type == "untyped"


def test_issuer_address_is_never_used_for_candidate():
    result = parse_driving_licence_address_result(drvlc_xml())

    assert result.reason == "ADDRESS_NODE_NOT_FOUND"
    assert result.address is None


def test_single_present_address_is_not_a_permanent_candidate():
    result = parse_driving_licence_address_result(
        drvlc_xml(address(**(FULL | {"type": "present"})))
    )

    assert result.reason == "ADDRESS_TYPE_UNSUPPORTED"
    assert result.address is None


@pytest.mark.parametrize(
    "changes,reason",
    [({"pin": "000000"}, "PIN_INVALID"), ({"country": "OTHER"}, "COUNTRY_UNSUPPORTED")],
)
def test_invalid_minimum_values_fail_closed(changes, reason):
    result = parse_driving_licence_address_result(drvlc_xml(address(**(FULL | changes))))

    assert result.reason == reason
    assert result.address is None


def test_parse_result_repr_does_not_include_address_values():
    result = parse_driving_licence_address_result(drvlc_xml(address(**FULL)))

    assert "Synthetic" not in repr(result)
