"""The anti-hallucination guarantee: no invented Maximo names get through."""
from __future__ import annotations

from core.models import ChangeItem, ChangeType
from maximo.validator import ValidationReport


def test_catalogue_loads_real_schemas(validator):
    assert validator.catalog.size >= 400, "bundled object-structure catalogue is missing"
    assert len(validator.catalog.known_objects()) > 200


def test_known_object_is_confirmed(validator):
    r = validator.object("WORKORDER")
    assert r.exists and r.source == "catalogue"
    assert "MXAPIWO" in r.detail


def test_invented_object_is_rejected(validator):
    r = validator.object("TOTALLYMADEUPOBJECT")
    assert not r.exists
    assert r.source == "unverified"


def test_close_misspelling_gets_a_suggestion(validator):
    r = validator.object("WORKORDR")
    assert not r.exists
    assert "WORKORDER" in r.suggestions


def test_real_attribute_carries_type_and_length(validator):
    r = validator.attribute("WORKORDER", "description")
    assert r.exists
    spec = validator.attribute_spec("WORKORDER", "description")
    assert spec["type"] == "ALN"
    assert spec["length"] > 0


def test_invented_attribute_is_rejected(validator):
    r = validator.attribute("WORKORDER", "CUCOMMENT")
    assert not r.exists, "an attribute that does not exist must not be confirmed"


def test_status_validated_against_process(validator, process):
    assert validator.status("ACCEPTED", process, "cu").exists
    assert not validator.status("BANANA", process, "cu").exists


def test_report_turns_failures_into_flags(validator, process):
    report = ValidationReport()
    item = ChangeItem(
        title="t", change_type=ChangeType.CONFIG,
        maximo_object="NOSUCHOBJECT", maximo_attribute="NOSUCHFIELD",
    )
    validator.check_change_item(item, process, report)
    flags = report.to_flags("test")
    assert flags, "an unconfirmed name must raise a flag for human review"
    assert not report.clean


def test_offline_client_refuses_rather_than_guessing(cfg):
    """With no credentials the client raises, it does not silently succeed."""
    from core.errors import MaximoError
    from maximo.client import MaximoClient

    client = MaximoClient(cfg.maximo)
    assert not client.configured
    try:
        client.get("apimeta")
        raise AssertionError("expected MaximoError")
    except MaximoError as exc:
        assert "not configured" in exc.message.lower()
