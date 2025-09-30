"""Tests for forecast parser functionality."""

import logging
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant, State
import pytest

from custom_components.haeo.data.loader import forecast_parsers
from tests.test_data.sensors import ALL_INVALID_SENSORS, ALL_VALID_SENSORS, INVALID_SENSORS_BY_PARSER


def _create_sensor_state(hass: HomeAssistant, entity_id: str, state_value: str, attributes: dict[str, Any]) -> State:
    """Create a sensor state and return it.

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID to create
        state_value: State value to set
        attributes: State attributes to set

    Returns:
        The created state object

    """
    hass.states.async_set(entity_id, state_value, attributes)

    if (state := hass.states.get(entity_id)) is None:
        msg = f"Failed to get state for {entity_id}"
        raise RuntimeError(msg)
    return state


@pytest.mark.parametrize(
    ("parser_type", "sensor_data"),
    ALL_VALID_SENSORS,
    ids=lambda val: val.get("description", str(val)) if isinstance(val, dict) else str(val),
)
def test_detect_format_valid_sensors(hass: HomeAssistant, parser_type: str, sensor_data: dict[str, Any]) -> None:
    """Test detection of valid forecast formats."""
    state = _create_sensor_state(hass, sensor_data["entity_id"], sensor_data["state"], sensor_data["attributes"])

    result = forecast_parsers.detect_format(state)

    assert result == sensor_data["expected_format"], f"Failed to detect {parser_type} format"


@pytest.mark.parametrize(
    ("parser_type", "sensor_data"),
    ALL_VALID_SENSORS,
    ids=lambda val: val.get("description", str(val)) if isinstance(val, dict) else str(val),
)
def test_parse_forecast_data_valid_sensors(hass: HomeAssistant, parser_type: str, sensor_data: dict[str, Any]) -> None:
    """Test parsing of valid forecast data."""
    state = _create_sensor_state(hass, sensor_data["entity_id"], sensor_data["state"], sensor_data["attributes"])

    result = forecast_parsers.parse_forecast_data(state)

    expected_count = sensor_data["expected_count"]
    if expected_count > 0:
        assert result is not None, f"Expected data for {parser_type}"
        assert len(result) == expected_count, f"Expected {expected_count} entries for {parser_type}"
        # Verify chronological order (only check if multiple entries)
        if len(result) > 1:
            assert result[0][0] < result[-1][0], f"Timestamps should be in chronological order for {parser_type}"
    else:
        assert result is None or len(result) == 0, f"Expected no data for invalid {parser_type} entry"


@pytest.mark.parametrize(
    ("parser_type", "sensor_data"),
    ALL_VALID_SENSORS,
    ids=lambda val: val.get("description", str(val)) if isinstance(val, dict) else str(val),
)
def test_get_forecast_units_valid_sensors(hass: HomeAssistant, parser_type: str, sensor_data: dict[str, Any]) -> None:
    """Test getting forecast units for valid sensors."""
    state = _create_sensor_state(hass, sensor_data["entity_id"], sensor_data["state"], sensor_data["attributes"])

    unit, device_class = forecast_parsers.get_forecast_units(state)

    assert unit is not None, f"Expected unit for {parser_type}"
    assert device_class is not None, f"Expected device_class for {parser_type}"


@pytest.mark.parametrize(
    ("parser_type", "sensor_data"),
    ALL_INVALID_SENSORS,
    ids=lambda val: val.get("description", str(val)) if isinstance(val, dict) else str(val),
)
def test_invalid_sensor_handling(hass: HomeAssistant, parser_type: str, sensor_data: dict[str, Any]) -> None:
    """Test handling of invalid sensor data."""
    state = _create_sensor_state(hass, sensor_data["entity_id"], sensor_data["state"], sensor_data["attributes"])

    detected_format = forecast_parsers.detect_format(state)
    parsed_data = forecast_parsers.parse_forecast_data(state)

    expected_format = sensor_data.get("expected_format")
    expected_count = sensor_data.get("expected_count", 0)

    assert detected_format == expected_format, f"Format detection mismatch for {sensor_data['description']}"

    if expected_count > 0:
        assert parsed_data is not None
        assert len(parsed_data) == expected_count
    else:
        assert parsed_data is None or len(parsed_data) == 0


def test_detect_empty_data(hass: HomeAssistant) -> None:
    """Test detection with empty attributes."""
    state = _create_sensor_state(hass, "sensor.empty", "0", {})

    result = forecast_parsers.detect_format(state)

    assert result is None


def test_detect_multiple_formats_warns(hass: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """If multiple parser detectors match the payload we should warn and return None."""

    attributes = {
        "forecasts": [
            {
                "per_kwh": 0.2,
                "start_time": "2025-10-05T12:00:00+00:00",
            }
        ],
        "forecast": [
            {
                "price": 0.3,
                "start_time": "2025-10-05T12:00:00+00:00",
            }
        ],
    }
    state = _create_sensor_state(hass, "sensor.ambiguous_forecast", "0", attributes)

    with patch.object(forecast_parsers._LOGGER, "warning") as warning_mock:
        result = forecast_parsers.detect_format(state)

    assert result is None
    warning_mock.assert_called_once()
    assert "Multiple forecast formats detected" in warning_mock.call_args[0][0]


def test_parse_unknown_format_returns_none(hass: HomeAssistant) -> None:
    """Test that parsing unknown format returns None."""
    state = _create_sensor_state(hass, "sensor.unknown", "0", {"unknown_field": "value"})

    result = forecast_parsers.parse_forecast_data(state)

    assert result is None


def test_get_forecast_units_unknown_format() -> None:
    """get_forecast_units should fail fast when no parser matches."""

    state = State("sensor.unknown", "0", {"unexpected": "value"})

    with pytest.raises(ValueError, match="unknown format"):
        forecast_parsers.get_forecast_units(state)


PARSER_MAP: dict[str, forecast_parsers.ForecastParser] = {
    forecast_parsers.amberelectric.DOMAIN: forecast_parsers.amberelectric.Parser,
    forecast_parsers.aemo_nem.DOMAIN: forecast_parsers.aemo_nem.Parser,
    forecast_parsers.solcast_solar.DOMAIN: forecast_parsers.solcast_solar.Parser,
    forecast_parsers.open_meteo_solar_forecast.DOMAIN: forecast_parsers.open_meteo_solar_forecast.Parser,
}


@pytest.mark.parametrize("parser_type", sorted(PARSER_MAP))
def test_parser_extract_rejects_invalid_payloads(
    hass: HomeAssistant,
    parser_type: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Each parser should reject invalid payloads even when called directly."""

    parser_cls = PARSER_MAP[parser_type]
    invalid_cases = INVALID_SENSORS_BY_PARSER[parser_type]

    for sensor in invalid_cases:
        state = _create_sensor_state(hass, sensor["entity_id"], sensor["state"], sensor["attributes"])

        with caplog.at_level(logging.WARNING, logger=parser_cls.__module__):
            result = parser_cls.extract(state)

        assert not parser_cls.detect(state)
        assert result == []
