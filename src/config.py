import os
from pathlib import Path
from urllib.parse import quote_plus


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
MODEL_DIR = BASE_DIR / "models"
MODEL_REGISTRY_DIR = MODEL_DIR / "registry"
DOCS_DIR = BASE_DIR / "docs"
INSTANCE_DIR = BASE_DIR / "instance"

RAW_DATA_FILE = RAW_DATA_DIR / "gas_meter_readings.csv"
PREDICTION_FILE = PROCESSED_DATA_DIR / "predictions.csv"
DATABASE_FILE = INSTANCE_DIR / "gas_monitor.db"

MODEL_FILE = MODEL_DIR / "lstm_autoencoder.pt"
SCALER_FILE = MODEL_DIR / "scaler.pkl"
META_FILE = MODEL_DIR / "train_meta.json"
ACTIVE_MODEL_META_FILE = MODEL_DIR / "active_model.json"

FEATURE_COLUMNS = [
    "instant_flow",
    "cumulative_usage",
    "battery_voltage",
    "signal_strength",
    "valve_state",
    "temperature",
    "pressure",
]

WINDOW_SIZE = 24
TRAIN_EPOCHS = 20
BATCH_SIZE = 32
LEARNING_RATE = 0.001
HIDDEN_SIZE = 32
NUM_LAYERS = 2
TRAIN_SPLIT = 0.8
SIMULATION_INTERVAL_SECONDS = 3
ONLINE_TIMEOUT_SECONDS = 15
ENGINEER_ONLINE_TIMEOUT_SECONDS = int(os.getenv("ENGINEER_ONLINE_TIMEOUT_SECONDS", "45"))
SIMULATION_DEVICE_COUNT = int(os.getenv("SIMULATION_DEVICE_COUNT", "50"))
PHYSICAL_DATA_RETENTION_DAYS = int(os.getenv("PHYSICAL_DATA_RETENTION_DAYS", "30"))
ASYNC_DETECTION_ENABLED = os.getenv("ASYNC_DETECTION_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
ASYNC_DETECTION_WORKERS = int(os.getenv("ASYNC_DETECTION_WORKERS", "4"))
MQTT_ENABLED = os.getenv("MQTT_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "").strip()
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "").strip()
MQTT_REGISTER_TOPIC = os.getenv("MQTT_REGISTER_TOPIC", "gas-meter/register")
MQTT_UPLOAD_TOPIC = os.getenv("MQTT_UPLOAD_TOPIC", "gas-meter/+/upload")
CARRIER_WEBHOOK_TOKEN = os.getenv("CARRIER_WEBHOOK_TOKEN", "").strip()
DRIFT_MONITOR_ENABLED = os.getenv("DRIFT_MONITOR_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
DRIFT_CHECK_INTERVAL_SECONDS = int(os.getenv("DRIFT_CHECK_INTERVAL_SECONDS", "300"))
DRIFT_MIN_RECENT_POINTS = int(os.getenv("DRIFT_MIN_RECENT_POINTS", "120"))
DRIFT_SCORE_THRESHOLD = float(os.getenv("DRIFT_SCORE_THRESHOLD", "1.25"))


def ensure_directories() -> None:
    for directory in [
        DATA_DIR,
        RAW_DATA_DIR,
        PROCESSED_DATA_DIR,
        MODEL_DIR,
        MODEL_REGISTRY_DIR,
        DOCS_DIR,
        INSTANCE_DIR,
    ]:
        directory.mkdir(parents=True, exist_ok=True)


def get_database_uri() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url
    mysql_user = os.getenv("MYSQL_USER", "root")
    mysql_password = os.getenv("MYSQL_PASSWORD", "")
    mysql_host = os.getenv("MYSQL_HOST", "127.0.0.1")
    mysql_port = os.getenv("MYSQL_PORT", "3306")
    mysql_database = os.getenv("MYSQL_DATABASE", "gas_monitor")
    prefer_mysql = os.getenv("DB_BACKEND", "mysql").lower() == "mysql"
    if prefer_mysql:
        return (
            f"mysql+pymysql://{quote_plus(mysql_user)}:{quote_plus(mysql_password)}"
            f"@{mysql_host}:{mysql_port}/{mysql_database}"
        )
    return f"sqlite:///{DATABASE_FILE.as_posix()}"
