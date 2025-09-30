"""Unit tests for ForecastLoader and ForecastAndSensorLoader."""

from unittest.mock import AsyncMock, patch

from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
import pytest

from custom_components.haeo.data.loader import ForecastAndSensorLoader, ForecastLoader


async def test_forecast_loader_missing_sensor(hass: HomeAssistant) -> None:
    """Test ForecastLoader handles missing sensors."""
    loader = ForecastLoader()

    # Check availability first
    assert loader.available(hass=hass, value=["sensor.missing"], forecast_times=[]) is False

    # Try to load - should raise ValueError
    with pytest.raises(ValueError, match=r"Sensor sensor\.missing not found"):
        await loader.load(hass=hass, value=["sensor.missing"], forecast_times=[0, 3600])


async def test_forecast_loader_no_forecast_data(hass: HomeAssistant) -> None:
    """Test ForecastLoader handles sensors without forecast data."""
    loader = ForecastLoader()

    # Create sensor without forecast attributes
    hass.states.async_set(
        "sensor.no_forecast",
        "100",
        {"device_class": SensorDeviceClass.POWER, "unit_of_measurement": UnitOfPower.WATT},
    )

    # Should not be available (no forecast data)
    assert loader.available(hass=hass, value=["sensor.no_forecast"], forecast_times=[]) is False

    # Try to load - should raise ValueError about missing forecast data
    with pytest.raises(ValueError, match=r"No forecast data available for sensor"):
        await loader.load(hass=hass, value=["sensor.no_forecast"], forecast_times=[0, 3600])


async def test_forecast_loader_invalid_type(hass: HomeAssistant) -> None:
    """Test ForecastLoader handles invalid input types."""
    loader = ForecastLoader()

    # Test with number (not a sequence)
    assert loader.is_valid_value(123) is False

    # Test with sequence of non-strings
    assert loader.is_valid_value([1, 2, 3]) is False


async def test_forecast_loader_unavailable_state(hass: HomeAssistant) -> None:
    """Test ForecastLoader handles unavailable sensor states."""
    loader = ForecastLoader()

    hass.states.async_set("sensor.unavailable", "unavailable")

    # Should not be available
    assert loader.available(hass=hass, value=["sensor.unavailable"], forecast_times=[]) is False


async def test_forecast_loader_available_success(hass: HomeAssistant) -> None:
    """ForecastLoader reports availability when sensors expose forecast data."""

    loader = ForecastLoader()
    hass.states.async_set("sensor.valid", "123")

    with patch("custom_components.haeo.data.loader.forecast_loader.detect_format", return_value="solcast_solar"):
        assert loader.available(hass=hass, value=["sensor.valid"], forecast_times=[]) is True


async def test_forecast_loader_load_success(hass: HomeAssistant) -> None:
    """ForecastLoader aggregates forecast data using numpy interpolation."""

    loader = ForecastLoader()
    hass.states.async_set("sensor.forecast", "123")
    forecast_times = [0, 3600]
    forecast_data = [(0, 1.0), (3600, 2.0)]

    with (
        patch("custom_components.haeo.data.loader.forecast_loader.parse_forecast_data", return_value=forecast_data),
        patch(
            "custom_components.haeo.data.loader.forecast_loader.get_forecast_units",
            return_value=(UnitOfPower.KILO_WATT, SensorDeviceClass.POWER),
        ),
        patch(
            "custom_components.haeo.data.loader.forecast_loader.convert_to_base_unit",
            side_effect=lambda value, _unit, _device_class: value,
        ),
    ):
        result = await loader.load(
            hass=hass,
            value=["sensor.forecast"],
            forecast_times=forecast_times,
        )

    assert result == [1.0, 2.0]


async def test_forecast_loader_type_error_for_invalid_value(hass: HomeAssistant) -> None:
    """ForecastLoader rejects values that are not sequences of sensor IDs."""

    loader = ForecastLoader()

    with pytest.raises(TypeError, match=r"Value must be a sequence of sensor entity IDs"):
        await loader.load(hass=hass, value="sensor.invalid", forecast_times=[0, 3600])


async def test_forecast_and_sensor_loader_missing_sensor(hass: HomeAssistant) -> None:
    """Test ForecastAndSensorLoader handles missing sensors."""
    loader = ForecastAndSensorLoader()

    # Check availability first - missing sensor
    assert (
        loader.available(
            hass=hass,
            value={"live": ["sensor.missing"], "forecast": ["sensor.missing"]},
            forecast_times=[],
        )
        is False
    )


@pytest.mark.parametrize(
    ("availability", "expected_outcome"),
    [((True, True), "available"), ((True, False), "unavailable"), ((False, True), "unavailable")],
)
async def test_forecast_and_sensor_loader_available_matrix(
    hass: HomeAssistant,
    availability: tuple[bool, bool],
    expected_outcome: str,
) -> None:
    """Combined loader requires both live and forecast data to be available."""

    loader = ForecastAndSensorLoader()
    value = {"live": ["sensor.live"], "forecast": ["sensor.forecast"]}
    sensor_available, forecast_available = availability

    with (
        patch.object(loader._sensor_loader, "available", return_value=sensor_available) as sensor_available_mock,
        patch.object(loader._forecast_loader, "available", return_value=forecast_available) as forecast_available_mock,
    ):
        observed = loader.available(hass=hass, value=value, forecast_times=[])
        assert observed is (expected_outcome == "available")

    sensor_available_mock.assert_called_once_with(hass=hass, value=value["live"], forecast_times=[])
    forecast_available_mock.assert_called_once_with(hass=hass, value=value["forecast"], forecast_times=[])


async def test_forecast_and_sensor_loader_combines_live_with_forecast(hass: HomeAssistant) -> None:
    """The first forecast bucket is replaced with live sensor data."""

    loader = ForecastAndSensorLoader()
    value = {"live": ["sensor.live"], "forecast": ["sensor.forecast"]}

    with (
        patch.object(loader._sensor_loader, "load", AsyncMock(return_value=2.5)) as sensor_load_mock,
        patch.object(loader._forecast_loader, "load", AsyncMock(return_value=[0.0, 5.0])) as forecast_load_mock,
    ):
        result = await loader.load(hass=hass, value=value, forecast_times=[0, 3600])

    sensor_load_mock.assert_awaited_once_with(hass=hass, value=value["live"], forecast_times=[0, 3600])
    forecast_load_mock.assert_awaited_once_with(hass=hass, value=value["forecast"], forecast_times=[0, 3600])
    assert result == [2.5, 5.0]


async def test_forecast_and_sensor_loader_invalid_type(hass: HomeAssistant) -> None:
    """Test ForecastAndSensorLoader type validation."""
    loader = ForecastAndSensorLoader()

    # Test is_valid_value with invalid types
    assert loader.is_valid_value("not_a_dict") is False
    assert loader.is_valid_value(123) is False
    assert loader.is_valid_value(["list"]) is False


async def test_forecast_and_sensor_loader_missing_keys(hass: HomeAssistant) -> None:
    """Test ForecastAndSensorLoader validates structure with TypeGuard."""
    loader = ForecastAndSensorLoader()

    # Test with missing 'live' key - is_valid_value should return False
    assert loader.is_valid_value({"forecast": ["sensor.test"]}) is False

    # Test with missing 'forecast' key - is_valid_value should return False
    assert loader.is_valid_value({"live": ["sensor.test"]}) is False

    # Test with both keys present and valid - is_valid_value should return True
    assert loader.is_valid_value({"live": ["sensor.test"], "forecast": ["sensor.forecast"]}) is True
