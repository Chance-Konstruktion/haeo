"""Tests for ForecastAndSensorLoader."""

from collections.abc import Sequence
from typing import Any, TypeGuard

from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
import pytest

from custom_components.haeo.data.loader import ForecastAndSensorLoader, ForecastAndSensorValue
from custom_components.haeo.data.loader.forecast_loader import ForecastLoader
from custom_components.haeo.data.loader.sensor_loader import SensorLoader


async def test_forecast_and_sensor_loader_type_guard(hass: HomeAssistant) -> None:
    """Test ForecastAndSensorLoader TypeGuard validation."""
    loader = ForecastAndSensorLoader()

    # Valid value
    valid_value: ForecastAndSensorValue = {
        "live": ["sensor.live"],
        "forecast": ["sensor.forecast"],
    }
    assert loader.is_valid_value(valid_value) is True

    # Missing 'live' key
    assert loader.is_valid_value({"forecast": ["sensor.forecast"]}) is False

    # Missing 'forecast' key
    assert loader.is_valid_value({"live": ["sensor.live"]}) is False

    # Wrong type for 'live' (not a sequence)
    assert loader.is_valid_value({"live": "sensor.live", "forecast": ["sensor.forecast"]}) is False

    # Wrong type for 'forecast' (not a sequence)
    assert loader.is_valid_value({"live": ["sensor.live"], "forecast": "sensor.forecast"}) is False

    # Not a dict
    assert loader.is_valid_value("not a dict") is False
    assert loader.is_valid_value(None) is False
    assert loader.is_valid_value([]) is False


async def test_forecast_and_sensor_loader_unavailable_live(hass: HomeAssistant) -> None:
    """Test availability when live sensor is unavailable."""
    loader = ForecastAndSensorLoader()

    # Set up forecast sensor (available)
    hass.states.async_set(
        "sensor.forecast_power",
        "1000",
        {
            "device_class": SensorDeviceClass.POWER,
            "unit_of_measurement": UnitOfPower.WATT,
            "forecast": [
                {"datetime": "2024-01-01T00:00:00Z", "power": 1000},
            ],
        },
    )

    # Live sensor is unavailable
    hass.states.async_set("sensor.live_power", "unavailable")

    value: ForecastAndSensorValue = {
        "live": ["sensor.live_power"],
        "forecast": ["sensor.forecast_power"],
    }

    forecast_times = [0]

    # Should not be available
    assert loader.available(hass=hass, value=value, forecast_times=forecast_times) is False


async def test_forecast_and_sensor_loader_unavailable_forecast(hass: HomeAssistant) -> None:
    """Test availability when forecast sensor is unavailable."""
    loader = ForecastAndSensorLoader()

    # Set up live sensor (available)
    hass.states.async_set(
        "sensor.live_power", "2000", {"device_class": SensorDeviceClass.POWER, "unit_of_measurement": UnitOfPower.WATT}
    )

    # Forecast sensor missing forecast attribute
    hass.states.async_set(
        "sensor.forecast_power",
        "1000",
        {"device_class": SensorDeviceClass.POWER, "unit_of_measurement": UnitOfPower.WATT},
    )

    value: ForecastAndSensorValue = {
        "live": ["sensor.live_power"],
        "forecast": ["sensor.forecast_power"],
    }

    forecast_times = [0]

    # Should not be available (forecast missing)
    assert loader.available(hass=hass, value=value, forecast_times=forecast_times) is False


class _DummySensorLoader(SensorLoader):
    def available(self, *, hass: HomeAssistant, value: Any, **kwargs: Any) -> bool:
        del hass, value, kwargs
        return True

    async def load(self, *, hass: HomeAssistant, value: Any, **kwargs: Any) -> float:
        del hass, value, kwargs
        return 0.75


class _DummyForecastLoader(ForecastLoader):
    def __init__(self, result: Sequence[float]) -> None:
        self._result = list(result)

    def available(self, *, hass: HomeAssistant, value: Any, **kwargs: Any) -> bool:
        del hass, value, kwargs
        return True

    def is_valid_value(self, value: Any) -> TypeGuard[Sequence[str]]:
        return (
            isinstance(value, Sequence) and not isinstance(value, str) and all(isinstance(item, str) for item in value)
        )

    async def load(
        self,
        *,
        hass: HomeAssistant,
        value: Any,
        forecast_times: Sequence[int],
        **kwargs: Any,
    ) -> list[float]:
        del hass, value, forecast_times, kwargs
        return list(self._result)


async def test_forecast_and_sensor_loader_load_merges_live_value(hass: HomeAssistant) -> None:
    """The first forecast point should be replaced with the live sensor reading."""

    loader = ForecastAndSensorLoader()
    loader._sensor_loader = _DummySensorLoader()
    loader._forecast_loader = _DummyForecastLoader([1.0, 2.0])

    value: ForecastAndSensorValue = {
        "live": ["sensor.live_power"],
        "forecast": ["sensor.forecast_power"],
    }

    result = await loader.load(hass=hass, value=value, forecast_times=[0, 1])

    assert result == [0.75, 2.0]


async def test_forecast_and_sensor_loader_load_invalid_value(hass: HomeAssistant) -> None:
    """Invalid structures should raise a TypeError before loading."""

    loader = ForecastAndSensorLoader()

    with pytest.raises(TypeError, match="Value must be a dict"):
        await loader.load(hass=hass, value="not-a-dict", forecast_times=[0])
