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
    assert result.classification == "STRUCTURED_ADDRESS_CANDIDATE"
    assert result.document_address_type == "permanent"
    assert result.address is not None
    assert result.address.address_line_1 == "House 1, Synthetic Line"
    assert result.address.address_line_2 == "Synthetic Line Two, Synthetic Landmark"
    assert result.address.locality == "Synthetic Locality"
    assert result.address.city == "Synthetic City"
    assert result.address.country == "IN"


def test_one_untyped_address_is_a_structured_candidate():
    result = parse_driving_licence_address_result(drvlc_xml(address(**(FULL | {"type": ""}))))
    assert result.classification == "STRUCTURED_ADDRESS_CANDIDATE"
    assert result.document_address_type == "untyped"


def test_permanent_address_wins_over_present_address():
    present = FULL | {"type": "present", "line1": "Present Line"}
    permanent = FULL | {"line1": "Permanent Line"}
    result = parse_driving_licence_address_result(
        drvlc_xml(address(**present), address(**permanent))
    )
    assert result.classification == "STRUCTURED_ADDRESS_CANDIDATE"
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
    assert result.classification == "ADDRESS_AMBIGUOUS"
    assert result.address is None
    assert result.prefill_text is None


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
    assert result.classification == "STRUCTURED_ADDRESS_CANDIDATE"
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
    assert result.classification == "STRUCTURED_ADDRESS_CANDIDATE"
    assert result.address is not None
    assert result.address.city == "Synthetic City"


@pytest.mark.parametrize("omitted", ["line2", "landmark"])
def test_optional_secondary_fields_may_be_absent(omitted):
    values = {key: value for key, value in FULL.items() if key != omitted}
    result = parse_driving_licence_address_result(drvlc_xml(address(**values)))
    assert result.classification == "STRUCTURED_ADDRESS_CANDIDATE"


def test_vtc_is_the_locality_and_city_fallback():
    values = {key: value for key, value in FULL.items() if key != "locality"}
    result = parse_driving_licence_address_result(drvlc_xml(address(**values)))
    assert result.address is not None
    assert result.address.locality == result.address.city == "Synthetic City"


def test_district_is_the_last_city_fallback():
    values = {key: value for key, value in FULL.items() if key not in {"locality", "vtc"}}
    result = parse_driving_licence_address_result(drvlc_xml(address(**values)))
    assert result.address is not None
    assert result.address.locality is None
    assert result.address.city == "Synthetic District"


@pytest.mark.parametrize("missing,expected", [("pin", "postal_code"), ("state", "state")])
def test_missing_structured_field_becomes_prefill_candidate(missing, expected):
    values = {key: value for key, value in FULL.items() if key != missing}
    result = parse_driving_licence_address_result(drvlc_xml(address(**values)))
    assert result.classification == "ADDRESS_PREFILL_CANDIDATE"
    assert result.address is None
    assert result.prefill_text is not None
    assert result.missing_fields == (expected,)


def test_malformed_address_xml_fails_closed():
    result = parse_driving_licence_address_result(b"<Certificate type='DRVLC'><IssuedTo>")
    assert result.classification == "ADDRESS_PARSE_FAILED"
    assert result.address is None
    assert result.prefill_text is None


def test_namespaced_alternate_schema_and_aliases_are_supported():
    xml = drvlc_xml(
        '<PermanentAddress addressLine1="Synthetic Line" addressLine2="Line Two" '
        'houseNo="House 1" landmark="Landmark" subDistrict="Synthetic Town" '
        'postalCode="400001" stateName="Synthetic State" countryCode="IND"/>',
        namespaced=True,
    )
    result = parse_driving_licence_address_result(xml)
    assert result.classification == "STRUCTURED_ADDRESS_CANDIDATE"
    assert result.document_address_type == "permanent"
    assert result.address is not None
    assert result.address.city == "Synthetic Town"


def test_legacy_person_attribute_schema_is_supported():
    attributes = (
        'address="Synthetic Line" district="Synthetic District" '
        'state="Synthetic State" pincode="400001" country="IN"'
    )
    result = parse_driving_licence_address_result(drvlc_xml(person_attributes=attributes))
    assert result.classification == "STRUCTURED_ADDRESS_CANDIDATE"
    assert result.document_address_type == "untyped"


def test_issuer_address_is_never_used_for_candidate():
    result = parse_driving_licence_address_result(drvlc_xml())
    assert result.classification == "NO_ADDRESS_AVAILABLE"
    assert result.address is None


def test_single_present_address_is_prefill_even_when_fully_structured():
    result = parse_driving_licence_address_result(
        drvlc_xml(address(**(FULL | {"type": "present"})))
    )
    assert result.classification == "ADDRESS_PREFILL_CANDIDATE"
    assert result.document_address_type == "present_or_current"
    assert result.address is None
    assert result.prefill_text is not None


def test_real_provider_shape_returns_authentic_free_form_prefill():
    result = parse_driving_licence_address_result(
        drvlc_xml(address(type="present", line1="Synthetic Free Form", country="IN"))
    )
    assert result.classification == "ADDRESS_PREFILL_CANDIDATE"
    assert result.document_address_type == "present_or_current"
    assert result.address is None
    assert result.prefill_text == "Synthetic Free Form, IN"
    assert result.missing_fields == ("city", "state", "postal_code")


def test_untyped_incomplete_address_is_prefill_candidate():
    result = parse_driving_licence_address_result(
        drvlc_xml(address(line1="Synthetic Untyped Free Form", country="IN"))
    )
    assert result.classification == "ADDRESS_PREFILL_CANDIDATE"
    assert result.document_address_type == "untyped"
    assert result.prefill_text == "Synthetic Untyped Free Form, IN"
    assert result.address is None


def test_country_only_is_not_an_address_candidate():
    result = parse_driving_licence_address_result(
        drvlc_xml(address(type="present", country="IN"))
    )
    assert result.classification == "NO_ADDRESS_AVAILABLE"
    assert result.prefill_text is None


def test_prefill_normalizes_delimiters_without_inventing_fields():
    result = parse_driving_licence_address_result(
        drvlc_xml(address(type="present", line1="  House 1 ;; Road 2  ", country="IN"))
    )
    assert result.prefill_text == "House 1, Road 2, IN"
    assert result.address is None
    assert result.missing_fields == ("city", "state", "postal_code")


def test_invalid_pin_is_prefill_but_unsupported_country_fails_closed():
    invalid_pin = parse_driving_licence_address_result(
        drvlc_xml(address(**(FULL | {"pin": "000000"})))
    )
    unsupported_country = parse_driving_licence_address_result(
        drvlc_xml(address(**(FULL | {"country": "OTHER"})))
    )
    assert invalid_pin.classification == "ADDRESS_PREFILL_CANDIDATE"
    assert invalid_pin.missing_fields == ("postal_code",)
    assert unsupported_country.classification == "ADDRESS_PARSE_FAILED"
    assert unsupported_country.prefill_text is None


def test_parse_result_repr_does_not_include_address_values():
    result = parse_driving_licence_address_result(drvlc_xml(address(**FULL)))
    prefill = parse_driving_licence_address_result(
        drvlc_xml(address(type="present", line1="Private Synthetic Value", country="IN"))
    )
    assert "Synthetic" not in repr(result)
    assert "Private Synthetic Value" not in repr(prefill)
