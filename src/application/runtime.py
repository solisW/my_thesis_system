from __future__ import annotations

from flask import Flask

from ..config import DRIFT_MONITOR_ENABLED
from ..drift_monitor import DriftMonitorService
from ..mqtt_gateway import MqttGateway
from ..simulation_module import SimulationModule
from ..training_module import ContinuousTrainingService


class RuntimeServices:
    """Owns long-lived background services for one Flask application."""

    def __init__(self) -> None:
        self.simulator: SimulationModule | None = None
        self.trainer: ContinuousTrainingService | None = None
        self.mqtt_gateway: MqttGateway | None = None
        self.drift_monitor: DriftMonitorService | None = None

    def start_background_services(self, app: Flask) -> None:
        if not DRIFT_MONITOR_ENABLED:
            return
        self.drift_monitor = self.drift_monitor_service(app)
        self.drift_monitor.start()

    def simulator_service(self, app: Flask) -> SimulationModule:
        if self.simulator is None:
            self.simulator = SimulationModule(app)
        return self.simulator

    def trainer_service(self, app: Flask, interval_seconds: int | None = None) -> ContinuousTrainingService:
        if self.trainer is None:
            kwargs = {"interval_seconds": interval_seconds} if interval_seconds is not None else {}
            self.trainer = ContinuousTrainingService(app, **kwargs)
        return self.trainer

    def mqtt_service(self, app: Flask) -> MqttGateway:
        if self.mqtt_gateway is None:
            self.mqtt_gateway = MqttGateway(app)
        return self.mqtt_gateway

    def drift_monitor_service(self, app: Flask) -> DriftMonitorService:
        if self.drift_monitor is None:
            self.drift_monitor = DriftMonitorService(app, on_drift=lambda _: self.start_training_after_drift(app))
        return self.drift_monitor

    def start_training_after_drift(self, app: Flask) -> None:
        trainer = self.trainer_service(app, interval_seconds=300)
        if not trainer.is_running():
            trainer.start()
