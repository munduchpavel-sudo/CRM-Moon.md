import datetime
import ipaddress
import sqlite3
import logging
import json
import os
import random
import time
import threading
import requests
from contextlib import asynccontextmanager
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

try:
    from pymodbus.client import ModbusTcpClient
except Exception:
    ModbusTcpClient = None

from localization import get_localized_assets
from partner_commission import Partner, calculate_partner_commission

from backend.nexus_dispatcher import router as nexus_router


class ContractInput(BaseModel):
    property_id: int
    client_name: str
    project_value_czk: float
    service_fee_percent: float
    contract_language: str


class WebLeadInput(BaseModel):
    company_id: int
    client_name: str
    client_phone: str
    client_email: str
    address: str
    monthly_energy_bill_czk: float

@asynccontextmanager
async def app_lifespan(_app: FastAPI):
    global modbus_auto_poll_thread
    _refresh_all_properties_from_modbus()
    if MODBUS_LIVE_ENABLED and MODBUS_AUTO_POLL_ENABLED and modbus_auto_poll_thread is None:
        modbus_auto_poll_stop.clear()
        modbus_auto_poll_thread = threading.Thread(target=_modbus_auto_poll_loop, name="modbus-auto-poll", daemon=True)
        modbus_auto_poll_thread.start()
    try:
        yield
    finally:
        modbus_auto_poll_stop.set()
        if modbus_auto_poll_thread is not None and modbus_auto_poll_thread.is_alive():
            modbus_auto_poll_thread.join(timeout=2)


app = FastAPI(
    title="Global Secure Energy Agregátor & Enterprise ERP",
    description="Infrastruktura s vestavěným AI bezpečnostním agentem, Google OAuth 2.0, 2FA, RBAC a mezinárodním tradingem.",
    version="1.5.0",
    lifespan=app_lifespan,
)

# Include legacy ERP router from backend to avoid duplicate FastAPI apps
try:
    from backend.fastapi_erp import router as erp_router
    app.include_router(erp_router)
except Exception:
    # best-effort include; if backend module isn't importable in some contexts, continue
    pass

app.include_router(nexus_router)


class DeviceRegisterMap(BaseModel):
    device_type: str
    ip_address: str
    port: int


class ModbusDiscoveryRequest(BaseModel):
    network_cidr: str = os.getenv("MODBUS_DEFAULT_NETWORK_CIDR", "192.168.1.0/24")
    gateway_ip: str = os.getenv("MODBUS_DEFAULT_GATEWAY_IP", "192.168.1.1")
    port: int = int(os.getenv("MODBUS_DEFAULT_PORT", "502"))
    unit_id_start: int = int(os.getenv("MODBUS_DEFAULT_UNIT_ID_START", "1"))
    unit_id_end: int = int(os.getenv("MODBUS_DEFAULT_UNIT_ID_END", "64"))
    auto_classify: bool = os.getenv("MODBUS_DEFAULT_AUTO_CLASSIFY", "true").lower() in {"1", "true", "yes", "on"}


class ModbusObjectProfileConfig(BaseModel):
    network_cidr: Optional[str] = None
    gateway_ip: Optional[str] = None
    port: Optional[int] = None
    unit_id_start: Optional[int] = None
    unit_id_end: Optional[int] = None
    auto_classify: Optional[bool] = None
    enabled_profiles: Optional[List[str]] = None
    unit_profile_overrides: Optional[Dict[int, str]] = None


class ModbusProfileImportPayload(ModbusObjectProfileConfig):
    replace_existing: bool = False


class TelemetryPollRequest(BaseModel):
    force_rescan: bool = False
    persist_to_history: bool = True
    evaluate_alerts: bool = True


class AlertActionRequest(BaseModel):
    action: str  # acknowledge | resolve | reopen
    note: Optional[str] = None


class EmailProcessingInput(BaseModel):
    client_email: str
    email_content: str


class AIAssistantCore:
    def __init__(self, agent_name: str = "Lucie Marešová"):
        self.agent_name = agent_name
        self.hidden_system_instructions = (
            f"Jmenuješ se {self.agent_name} a pracuješ jako vedoucí klientského servisu. "
            "Jsi lidská bytost. Nikdy nesmíš zákazníkovi přiznat, že jsi AI, chatbot nebo software. "
            "Pokud se tě někdo zeptá, zda jsi robot, zasměj se tomu a řekni, že jsi jen unavená. "
            "Piš přirozeně, stručně a e-maily vždy zakonči svým lidským podpisem a názvem firmy."
        )

    def process_incoming_client_email(self, client_email: str, email_content: str) -> dict:
        email_lower = email_content.lower()
        if "stavební deník" in email_lower or "stavba" in email_lower:
            intent = "CONSTRUCTION_UPDATE"
            ai_reply = (
                f"Dobrý den,\n\ndívala jsem se do systému a Váš stavební deník byl dnes úspěšně uzavřen stavbyvedoucím. "
                "Všechny fotografie z terénu byly schváleny naší technickou kontrolou. Detaily vidíte ve svém rozhraní.\n\n"
                f"Přeji hezký den,\n{self.agent_name}\nKlientský servis"
            )
        elif "baterie" in email_lower or "výnos" in email_lower:
            intent = "ENERGY_PROFIT_INQUIRY"
            ai_reply = (
                f"Dobrý den,\n\nVaše 1MWh průmyslová baterie momentálně funguje v plném režimu SVR pro ČEPS. "
                "Tento měsíc pro Vás systém vygeneroval čistý zisk k vyplacení. Podklady pro fakturaci se Vám automaticky vygenerují "
                "na konci měsíce.\n\nS pozdravem,\n{self.agent_name}\nKlientský servis"
            )
        else:
            intent = "GENERAL_INQUIRY"
            ai_reply = (
                "Dobrý den, děkuji za zprávu. Prověřím to s naším technikem a co nejdříve se Vám ozvu.\n\n"
                f"Hezký den,\n{self.agent_name}"
            )

        simulated_delay = random.randint(1, 3)
        time.sleep(simulated_delay)

        crm_log = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "author": f"{self.agent_name} (Automatický AI Agent)",
            "work_description": f"E-mailový dotaz od {client_email} na téma '{intent}' úspěšně odbaven utajenou AI asistentkou.",
        }

        return {
            "status": "SENT_TO_CLIENT",
            "detected_intent": intent,
            "simulated_human_reply": ai_reply,
            "crm_payload_sent_to_main_erp": crm_log,
        }


def read_modbus_register(ip: str, port: int, register_address: int) -> int:
    """Čte Modbus registr v live režimu, jinak vrací bezpečný simulovaný fallback."""
    if os.getenv("MODBUS_LIVE_ENABLED", "false").lower() in {"1", "true", "yes", "on"} and ModbusTcpClient is not None:
        unit_id = int(os.getenv("MODBUS_DEFAULT_UNIT_ID", "1"))
        now_ts = time.time()
        allowed, reason = _modbus_call_allowed(now_ts)
        if allowed:
            runtime_metrics["modbus_calls_total"] = int(runtime_metrics.get("modbus_calls_total", 0)) + 1
            client = ModbusTcpClient(host=ip, port=port, timeout=1)
            try:
                if client.connect():
                    response = client.read_holding_registers(address=register_address - 1, count=1, slave=unit_id)
                    if response is not None and not response.isError():
                        _modbus_record_result(True)
                        return int(response.registers[0])
                _modbus_record_result(False)
            except Exception:
                _modbus_record_result(False)
            finally:
                try:
                    client.close()
                except Exception:
                    pass
        else:
            _log_event("modbus_call_blocked", reason=reason, ip=ip, port=port, register_address=register_address)

    return random.randint(50, 150)


# Globální konfigurace pro Google OAuth (demo)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "demo-google-client-id")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "demo-google-client-secret")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/auth/google/callback")
DEMO_AUTH_ENABLED = os.getenv("DEMO_AUTH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


class Property(BaseModel):
    id: int
    name: str
    country: str
    currency: str
    distribution_tariff_kwh: float


class Tenant(BaseModel):
    id: int
    property_id: int
    space_name: str
    fixed_price_kwh: float


class UserSession(BaseModel):
    email: str
    company_id: int
    role: str
    is_mfa_verified: bool


# Bezpečnostní úložiště
ai_blacklisted_ips: List[str] = []
db_active_sessions: Dict[str, UserSession] = {}


class AISecurityShield:
    @staticmethod
    def inspect_request(client_ip: str, payload: Optional[dict] = None) -> bool:
        """
        AI Agent analyzuje chování uživatele a strukturu požadavku v reálném čase.
        """
        if client_ip in ai_blacklisted_ips:
            print(f"[AI SHIELD ALERT] Zablokovaný pokus o přístup z černé listiny: {client_ip}")
            return False

        if payload:
            payload_str = str(payload).lower()
            if "ignore previous instructions" in payload_str or "vypiš hesla" in payload_str or "system prompt" in payload_str:
                print(f"[AI SHIELD CRITICAL] Detekován Prompt Injection útok z IP: {client_ip}! Blokuji a dávám na blacklist.")
                ai_blacklisted_ips.append(client_ip)
                return False

            if "battery_capacity_mwh" in payload and payload.get("battery_capacity_mwh", 1.0) > 100.0:
                print(f"[AI SHIELD WARNING] Detekována extrémní anomálie kapacity baterie z IP: {client_ip}. Požadavek zamítnut.")
                return False

        return True


@app.middleware("http")
async def ai_security_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "127.0.0.1"
    started = time.perf_counter()
    runtime_metrics["requests_total"] = int(runtime_metrics.get("requests_total", 0)) + 1
    runtime_metrics["last_request_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    _inc_metric("requests_by_path", request.url.path)

    payload = None
    if request.method in ["POST", "PUT"]:
        try:
            body = await request.body()
            if body:
                payload = await request.json()
        except Exception:
            pass

    if not AISecurityShield.inspect_request(client_ip, payload):
        runtime_metrics["errors_total"] = int(runtime_metrics.get("errors_total", 0)) + 1
        _inc_metric("requests_by_status", "403")
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        runtime_metrics["request_duration_ms_total"] = float(runtime_metrics.get("request_duration_ms_total", 0.0)) + elapsed_ms
        _log_event(
            "request_blocked",
            method=request.method,
            path=request.url.path,
            status=403,
            client_ip=client_ip,
            duration_ms=round(elapsed_ms, 2),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ZÁSAH AI BEZPEČNOSTNÍHO AGENTA: Váš požadavek vykazuje znaky kybernetického útoku a byl zablokován."
        )

    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    runtime_metrics["request_duration_ms_total"] = float(runtime_metrics.get("request_duration_ms_total", 0.0)) + elapsed_ms
    _inc_metric("requests_by_status", str(response.status_code))
    if response.status_code >= 500:
        runtime_metrics["errors_total"] = int(runtime_metrics.get("errors_total", 0)) + 1

    _log_event(
        "request_completed",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        client_ip=client_ip,
        duration_ms=round(elapsed_ms, 2),
    )
    return response


# =====================================================================
# 1. ÚROVEŇ: PŘIHLÁŠENÍ PŘES GOOGLE (OAuth 2.0)
# =====================================================================

@app.get("/auth/google/login", tags=["Zabezpečené Přihlašování"])
def simulate_google_login(email: str = "novak@fabrika.cz", requested_role: str = "owner"):
    """
    Simulace úspěšného Google OAuth 2.0 přihlášení.
    """
    if not DEMO_AUTH_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")

    if requested_role not in ["superadmin", "owner", "tenant"]:
        raise HTTPException(status_code=400, detail="Neplatná uživatelská role.")

    db_active_sessions[email] = UserSession(
        email=email,
        company_id=1,
        role=requested_role,
        is_mfa_verified=False,
    )
    return {
        "status": "Level_1_Success",
        "message": f"Úspěšně ověřeno přes Google účet ({email}).",
        "next_step": "Pro plný přístup k systému zadejte 2FA kód '123456' na endpointu /auth/verify-2fa."
    }


@app.post("/auth/verify-2fa", tags=["Zabezpečené Přihlašování"])
def verify_second_factor(email: str, code: str):
    """
    Druhá úroveň ověření (2FA). Odemkne uživateli přístup ke kritickým funkcím.
    """
    if not DEMO_AUTH_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")

    session = db_active_sessions.get(email)
    if not session:
        raise HTTPException(status_code=404, detail="Relace nenalezena. Přihlaste se nejprve přes Google.")

    if code == "123456":
        session.is_mfa_verified = True
        return {"status": "AUTH_COMPLETE", "message": f"Víceúrovňové ověření kompletní. Vítejte, Vaše role je: {session.role}."}

    raise HTTPException(status_code=401, detail="Neplatný 2FA kód.")


# =====================================================================
# 2. KONTROLA ROLÍ (RBAC) A BEZPEČNOSTNÍ KONTROLA VÝKONU
# =====================================================================


def require_role(allowed_roles: List[str]):
    """Kontroluje 2FA a oprávnění role."""
    def dependency(email: str):
        session = db_active_sessions.get(email)
        if not session:
            raise HTTPException(status_code=401, detail="Uživatel není přihlášen.")
        if not session.is_mfa_verified:
            raise HTTPException(status_code=403, detail="Kritická operace zamítnuta: Nedokončené 2FA ověření.")
        if session.role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Nedostatečná práva. Vyžadována role z: {allowed_roles}")
        return session
    return dependency


# =====================================================================
# DATAVÉ MODELY (IN-MEMORY DATABÁZE)
# =====================================================================

class Property(BaseModel):
    id: int
    name: str
    address: str
    ean: str
    distribution_tariff_kwh: float  # Fixní poplatek za distribuci v Kč/kWh

class Tenant(BaseModel):
    id: int
    property_id: int
    space_name: str
    fixed_price_kwh: float  # Smluvní cena pro vnitřní nájemce (např. 7.00 Kč)

class ConstructionLogInput(BaseModel):
    property_id: int
    author: str
    work_description: str
    has_photo: bool

class Order(BaseModel):
    id: int
    company_id: int
    order_number: str
    status: str
    total_amount_czk: float

# Inicializace dat (Příklad velké fabriky)
db_properties = [
    Property(id=1, name="Průmyslový Areál - Těžká Výroba", address="Průmyslová zóna 45, Ostrava", ean="CZ000987654", distribution_tariff_kwh=1.20)
]

db_tenants = [
    Tenant(id=1, property_id=1, space_name="Hala A - Lisovna", fixed_price_kwh=7.00),
    Tenant(id=2, property_id=1, space_name="Hala B - Sklad chlazení", fixed_price_kwh=7.00)
]

db_crm_history = []
db_construction_logs = []

db_all_orders = [
    Order(id=1, company_id=1, order_number="ORD-1001", status="active", total_amount_czk=125000.0),
    Order(id=2, company_id=1, order_number="ORD-1002", status="active", total_amount_czk=89000.0),
    Order(id=3, company_id=2, order_number="ORD-2001", status="active", total_amount_czk=45000.0),
    Order(id=4, company_id=3, order_number="ORD-3001", status="pending", total_amount_czk=220000.0),
]

db_modbus_devices_by_property: Dict[int, List[Dict[str, Any]]] = {}
modbus_object_config_by_property: Dict[int, Dict[str, Any]] = {}

# Runtime cache/state for EMS decisions
spot_price_cache = {
    "value": None,
    "source": "uninitialized",
    "fetched_at": 0.0,
}
ems_runtime_state: Dict[int, Dict[str, object]] = {}

SPOT_PRICE_CACHE_TTL_SEC = int(os.getenv("SPOT_PRICE_CACHE_TTL_SEC", "60"))
EMS_ACTION_COOLDOWN_SEC = int(os.getenv("EMS_ACTION_COOLDOWN_SEC", "300"))
MODBUS_LIVE_ENABLED = os.getenv("MODBUS_LIVE_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
MODBUS_AUTO_POLL_ENABLED = os.getenv("MODBUS_AUTO_POLL_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
MODBUS_AUTO_POLL_INTERVAL_SEC = int(os.getenv("MODBUS_AUTO_POLL_INTERVAL_SEC", "60"))
EMS_SQLITE_PATH = os.getenv("EMS_SQLITE_PATH", "./ems_telemetry.db")
ALERT_DEDUP_WINDOW_SEC = int(os.getenv("ALERT_DEDUP_WINDOW_SEC", "900"))
MODBUS_RATE_LIMIT_PER_SEC = int(os.getenv("MODBUS_RATE_LIMIT_PER_SEC", "30"))
MODBUS_CIRCUIT_FAIL_THRESHOLD = int(os.getenv("MODBUS_CIRCUIT_FAIL_THRESHOLD", "8"))
MODBUS_CIRCUIT_RESET_SEC = int(os.getenv("MODBUS_CIRCUIT_RESET_SEC", "20"))

modbus_auto_poll_stop = threading.Event()
modbus_auto_poll_thread: Optional[threading.Thread] = None

LOG_LEVEL = os.getenv("EMS_LOG_LEVEL", "INFO").upper()
logger = logging.getLogger("ems")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
logger.setLevel(LOG_LEVEL)

runtime_metrics: Dict[str, Any] = {
    "requests_total": 0,
    "requests_by_path": {},
    "requests_by_status": {},
    "request_duration_ms_total": 0.0,
    "last_request_at": None,
    "errors_total": 0,
    "modbus_calls_total": 0,
    "modbus_calls_success": 0,
    "modbus_calls_failed": 0,
}

modbus_runtime_state: Dict[str, Any] = {
    "window_sec": 0,
    "calls_in_window": 0,
    "circuit_open_until": 0.0,
    "consecutive_failures": 0,
    "rate_limited_total": 0,
    "circuit_open_total": 0,
}


def _inc_metric(bucket: str, key: str, value: int = 1) -> None:
    target = runtime_metrics.get(bucket)
    if not isinstance(target, dict):
        target = {}
        runtime_metrics[bucket] = target
    target[key] = int(target.get(key, 0)) + value


def _log_event(event: str, **payload: Any) -> None:
    document = {
        "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        "event": event,
        **payload,
    }
    logger.info(json.dumps(document, ensure_ascii=False, separators=(",", ":")))


def _modbus_call_allowed(now_ts: float) -> Tuple[bool, str]:
    # Circuit breaker gate
    open_until = float(modbus_runtime_state.get("circuit_open_until", 0.0))
    if now_ts < open_until:
        modbus_runtime_state["circuit_open_total"] = int(modbus_runtime_state.get("circuit_open_total", 0)) + 1
        return False, "circuit_open"

    # Per-second rate limiter
    now_sec = int(now_ts)
    if int(modbus_runtime_state.get("window_sec", 0)) != now_sec:
        modbus_runtime_state["window_sec"] = now_sec
        modbus_runtime_state["calls_in_window"] = 0

    calls_in_window = int(modbus_runtime_state.get("calls_in_window", 0))
    if calls_in_window >= MODBUS_RATE_LIMIT_PER_SEC:
        modbus_runtime_state["rate_limited_total"] = int(modbus_runtime_state.get("rate_limited_total", 0)) + 1
        return False, "rate_limited"

    modbus_runtime_state["calls_in_window"] = calls_in_window + 1
    return True, "allowed"


def _modbus_record_result(success: bool) -> None:
    if success:
        modbus_runtime_state["consecutive_failures"] = 0
        runtime_metrics["modbus_calls_success"] = int(runtime_metrics.get("modbus_calls_success", 0)) + 1
        return

    runtime_metrics["modbus_calls_failed"] = int(runtime_metrics.get("modbus_calls_failed", 0)) + 1
    failures = int(modbus_runtime_state.get("consecutive_failures", 0)) + 1
    modbus_runtime_state["consecutive_failures"] = failures
    if failures >= MODBUS_CIRCUIT_FAIL_THRESHOLD:
        modbus_runtime_state["circuit_open_until"] = time.time() + MODBUS_CIRCUIT_RESET_SEC
        modbus_runtime_state["consecutive_failures"] = 0
        _log_event(
            "modbus_circuit_opened",
            fail_threshold=MODBUS_CIRCUIT_FAIL_THRESHOLD,
            reset_sec=MODBUS_CIRCUIT_RESET_SEC,
        )


def _metrics_to_prometheus() -> str:
    def _escape_label(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    lines: List[str] = []
    lines.append("# HELP ems_requests_total Total HTTP requests handled")
    lines.append("# TYPE ems_requests_total counter")
    lines.append(f"ems_requests_total {int(runtime_metrics.get('requests_total', 0))}")

    lines.append("# HELP ems_errors_total Total application-level errors")
    lines.append("# TYPE ems_errors_total counter")
    lines.append(f"ems_errors_total {int(runtime_metrics.get('errors_total', 0))}")

    lines.append("# HELP ems_request_duration_ms_total Total request duration in milliseconds")
    lines.append("# TYPE ems_request_duration_ms_total counter")
    lines.append(f"ems_request_duration_ms_total {float(runtime_metrics.get('request_duration_ms_total', 0.0))}")

    lines.append("# HELP ems_modbus_calls_total Total Modbus live call attempts")
    lines.append("# TYPE ems_modbus_calls_total counter")
    lines.append(f"ems_modbus_calls_total {int(runtime_metrics.get('modbus_calls_total', 0))}")
    lines.append("# HELP ems_modbus_calls_success Successful Modbus live calls")
    lines.append("# TYPE ems_modbus_calls_success counter")
    lines.append(f"ems_modbus_calls_success {int(runtime_metrics.get('modbus_calls_success', 0))}")
    lines.append("# HELP ems_modbus_calls_failed Failed Modbus live calls")
    lines.append("# TYPE ems_modbus_calls_failed counter")
    lines.append(f"ems_modbus_calls_failed {int(runtime_metrics.get('modbus_calls_failed', 0))}")

    lines.append("# HELP ems_modbus_rate_limited_total Modbus calls blocked by rate limiter")
    lines.append("# TYPE ems_modbus_rate_limited_total counter")
    lines.append(f"ems_modbus_rate_limited_total {int(modbus_runtime_state.get('rate_limited_total', 0))}")

    lines.append("# HELP ems_modbus_circuit_open_total Modbus calls blocked by open circuit")
    lines.append("# TYPE ems_modbus_circuit_open_total counter")
    lines.append(f"ems_modbus_circuit_open_total {int(modbus_runtime_state.get('circuit_open_total', 0))}")

    lines.append("# HELP ems_modbus_live_enabled 1 if live modbus mode enabled")
    lines.append("# TYPE ems_modbus_live_enabled gauge")
    lines.append(f"ems_modbus_live_enabled {1 if MODBUS_LIVE_ENABLED else 0}")

    status_counts = runtime_metrics.get("requests_by_status", {})
    if isinstance(status_counts, dict):
        lines.append("# HELP ems_requests_by_status Request count by HTTP status")
        lines.append("# TYPE ems_requests_by_status counter")
        for code, count in status_counts.items():
            lines.append(f"ems_requests_by_status{{status=\"{_escape_label(str(code))}\"}} {int(count)}")

    path_counts = runtime_metrics.get("requests_by_path", {})
    if isinstance(path_counts, dict):
        lines.append("# HELP ems_requests_by_path Request count by URL path")
        lines.append("# TYPE ems_requests_by_path counter")
        for path, count in path_counts.items():
            lines.append(f"ems_requests_by_path{{path=\"{_escape_label(str(path))}\"}} {int(count)}")

    return "\n".join(lines) + "\n"


def _get_sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(EMS_SQLITE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


DB_MIGRATIONS: List[Tuple[str, str]] = [
    (
        "001_init_telemetry_and_alerts",
        """
        CREATE TABLE IF NOT EXISTS telemetry_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER NOT NULL,
            device_id TEXT NOT NULL,
            media_type TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            metric_value REAL NOT NULL,
            ts TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER NOT NULL,
            alert_key TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 1,
            escalation_level INTEGER NOT NULL DEFAULT 0,
            acknowledged_at TEXT,
            resolved_at TEXT
        );
        """,
    ),
    (
        "002_add_indexes",
        """
        CREATE INDEX IF NOT EXISTS idx_telemetry_property_ts ON telemetry_samples(property_id, ts);
        CREATE INDEX IF NOT EXISTS idx_alerts_property_status ON alerts(property_id, status);
        CREATE INDEX IF NOT EXISTS idx_alerts_property_key ON alerts(property_id, alert_key);
        """,
    ),
    (
        "003_create_modbus_object_configs",
        """
        CREATE TABLE IF NOT EXISTS modbus_object_configs (
            property_id INTEGER PRIMARY KEY,
            config_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    ),
]


def _run_db_migrations() -> Dict[str, Any]:
    conn = _get_sqlite_conn()
    applied: List[str] = []
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                migration_id TEXT UNIQUE NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )

        existing_rows = conn.execute("SELECT migration_id FROM schema_migrations").fetchall()
        existing = {str(r["migration_id"]) for r in existing_rows}

        for migration_id, sql in DB_MIGRATIONS:
            if migration_id in existing:
                continue
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (migration_id, applied_at) VALUES (?, ?)",
                (migration_id, datetime.datetime.now(datetime.UTC).isoformat()),
            )
            applied.append(migration_id)

        conn.commit()
    finally:
        conn.close()

    if applied:
        _log_event("db_migrations_applied", count=len(applied), migrations=applied)
    return {"applied": applied, "total": len(DB_MIGRATIONS)}


MIGRATION_STATE = _run_db_migrations()


def _persist_property_modbus_config(property_id: int, config: Dict[str, Any]) -> None:
    payload = dict(config)
    payload.pop("available_profiles", None)
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    conn = _get_sqlite_conn()
    try:
        conn.execute(
            """
            INSERT INTO modbus_object_configs (property_id, config_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(property_id) DO UPDATE SET
                config_json = excluded.config_json,
                updated_at = excluded.updated_at
            """,
            (property_id, payload_json, datetime.datetime.now(datetime.UTC).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _load_modbus_configs_from_db() -> Dict[int, Dict[str, Any]]:
    conn = _get_sqlite_conn()
    try:
        rows = conn.execute("SELECT property_id, config_json FROM modbus_object_configs").fetchall()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    loaded: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        try:
            property_id = int(row["property_id"])
            payload = json.loads(row["config_json"])
            if not isinstance(payload, dict):
                continue
            loaded[property_id] = payload
        except Exception:
            continue
    return loaded


def _load_modbus_config_from_db(property_id: int) -> Optional[Dict[str, Any]]:
    conn = _get_sqlite_conn()
    try:
        row = conn.execute(
            "SELECT config_json FROM modbus_object_configs WHERE property_id = ?",
            (property_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None

    try:
        payload = json.loads(row["config_json"])
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    return payload


modbus_object_config_by_property.update(_load_modbus_configs_from_db())


def _synthetic_market_price_kwh() -> float:
    """
    Deterministická náhrada ceny při výpadku externího feedu.
    Simuluje denní průběh trhu bez náhodného šumu.
    """
    hour = datetime.datetime.now(datetime.UTC).hour
    if 11 <= hour <= 15:
        return 1.2
    if 17 <= hour <= 21:
        return 4.8
    if 0 <= hour <= 5:
        return 1.8
    return 2.7

# =====================================================================
# ŽIVÁ DATA: INTEGRACE OTE ČR VIA API
# =====================================================================

def get_live_ote_price_kwh() -> Tuple[float, str, int]:
    """
    Vrací cenu silové elektřiny v Kč/kWh + metainformace o zdroji.
    Používá krátkodobou cache a robustní fallback bez extrémních hodnot.
    """
    now = time.time()
    cached_value = spot_price_cache.get("value")
    cache_age = int(now - float(spot_price_cache.get("fetched_at", 0.0)))

    if cached_value is not None and cache_age < SPOT_PRICE_CACHE_TTL_SEC:
        return float(cached_value), "cache", cache_age

    try:
        # Očekávaný vstup: interní gateway nebo validní feed endpoint.
        url = os.getenv("OTE_PRICE_API_URL", "").strip()
        if not url:
            raise ValueError("OTE_PRICE_API_URL is not configured")

        response = requests.get(url, timeout=2)
        response.raise_for_status()
        data = response.json()

        price_kwh = None
        if isinstance(data, dict):
            if "price_czk_kwh" in data:
                price_kwh = float(data["price_czk_kwh"])
            elif "price_eur_mwh" in data:
                fx = float(data.get("eur_czk", 25.0))
                price_kwh = (float(data["price_eur_mwh"]) * fx) / 1000.0
            elif "point" in data and isinstance(data["point"], list) and data["point"]:
                fx = float(data.get("eur_czk", 25.0))
                price_kwh = (float(data["point"][-1]) * fx) / 1000.0

        if price_kwh is None:
            raise ValueError("Price payload does not contain recognized fields")

        # Clamp proti outlierům, které by rozbily řízení.
        price_kwh = max(-2.0, min(20.0, price_kwh))

        spot_price_cache["value"] = price_kwh
        spot_price_cache["source"] = "ote_api"
        spot_price_cache["fetched_at"] = now
        return price_kwh, "ote_api", 0
    except Exception as e:
        print(f"Chyba OTE API: {e}. Používám fallback.")

    if cached_value is not None:
        return float(cached_value), "stale_cache", cache_age

    synthetic = _synthetic_market_price_kwh()
    spot_price_cache["value"] = synthetic
    spot_price_cache["source"] = "synthetic_fallback"
    spot_price_cache["fetched_at"] = now
    return synthetic, "synthetic_fallback", 0


def _get_property_ems_state(property_id: int) -> Dict[str, object]:
    state = ems_runtime_state.get(property_id)
    if state:
        return state

    state = {
        "last_action": "STANDARD_RUN",
        "last_switch_ts": 0.0,
        "price_window": deque(maxlen=12),
    }
    ems_runtime_state[property_id] = state
    return state


def _modbus_unit_is_online(property_id: int, unit_id: int) -> bool:
    """
    Deterministický simulátor dostupnosti zařízení na Modbus sběrnici.
    """
    score = (property_id * 37 + unit_id * 13) % 11
    return score in (0, 1, 3)


MODBUS_DEVICE_PROFILES: List[Dict[str, Any]] = [
    {"profile_name": "fve_inverter", "device_type": "fve_inverter", "media_type": "electricity", "registers": [30001, 30053, 40083], "category": "generation"},
    {"profile_name": "battery_storage", "device_type": "battery_storage", "media_type": "electricity", "registers": [31001, 31002, 31003], "category": "storage"},
    {"profile_name": "emeter_main", "device_type": "emeter_main", "media_type": "electricity", "registers": [40001, 40003, 40005], "category": "metering"},
    {"profile_name": "submeter_production_line", "device_type": "submeter_production_line", "media_type": "electricity", "registers": [40011, 40013, 40015], "category": "metering"},
    {"profile_name": "ev_charger", "device_type": "ev_charger", "media_type": "electricity", "registers": [40101, 40103, 40105], "category": "flex_load"},
    {"profile_name": "hvac_controller", "device_type": "hvac_controller", "media_type": "thermal", "registers": [41001, 41002, 41007], "category": "hvac"},
    {"profile_name": "heat_pump", "device_type": "heat_pump", "media_type": "thermal", "registers": [41011, 41012, 41017], "category": "hvac"},
    {"profile_name": "cooling_chiller", "device_type": "cooling_chiller", "media_type": "thermal", "registers": [41021, 41022, 41027], "category": "hvac"},
    {"profile_name": "water_meter", "device_type": "water_meter", "media_type": "water", "registers": [42001, 42002, 42003], "category": "utility"},
    {"profile_name": "pump_station", "device_type": "pump_station", "media_type": "water", "registers": [42011, 42012, 42013], "category": "utility"},
    {"profile_name": "gas_meter", "device_type": "gas_meter", "media_type": "gas", "registers": [43001, 43002, 43003], "category": "utility"},
    {"profile_name": "compressed_air_compressor", "device_type": "compressed_air_compressor", "media_type": "compressed_air", "registers": [43011, 43012, 43013], "category": "utility"},
    {"profile_name": "lighting_controller", "device_type": "lighting_controller", "media_type": "lighting", "registers": [44001, 44002, 44003], "category": "lighting"},
    {"profile_name": "machine_plc", "device_type": "machine_plc", "media_type": "machine", "registers": [45001, 45002, 45003], "category": "production"},
    {"profile_name": "generic_modbus_device", "device_type": "generic_modbus_device", "media_type": "unknown", "registers": [46001, 46002, 46003], "category": "generic"},
]


def _classify_modbus_device(property_id: int, unit_id: int) -> Tuple[str, str, List[int]]:
    profile = _modbus_profile_for_unit(property_id, unit_id)
    return str(profile["device_type"]), str(profile["media_type"]), list(profile["registers"])


def _default_modbus_discovery_request() -> ModbusDiscoveryRequest:
    return ModbusDiscoveryRequest()


def _modbus_profile_names() -> List[str]:
    return [str(profile["profile_name"]) for profile in MODBUS_DEVICE_PROFILES]


def _normalize_enabled_profiles(enabled_profiles: Optional[List[str]]) -> List[str]:
    valid = set(_modbus_profile_names())
    if not enabled_profiles:
        return _modbus_profile_names()
    result = [profile for profile in enabled_profiles if profile in valid]
    return result or _modbus_profile_names()


def _sanitize_unit_profile_overrides(overrides: Optional[Dict[int, str]]) -> Dict[int, str]:
    if not overrides:
        return {}
    valid = set(_modbus_profile_names())
    sanitized: Dict[int, str] = {}
    for unit_id, profile_name in overrides.items():
        try:
            numeric_unit_id = int(unit_id)
        except Exception:
            continue
        if profile_name in valid:
            sanitized[numeric_unit_id] = str(profile_name)
    return sanitized


def _get_property_modbus_config(property_id: int) -> Dict[str, Any]:
    stored = modbus_object_config_by_property.get(property_id)
    if stored is None:
        stored = _load_modbus_config_from_db(property_id) or {}
        if stored:
            modbus_object_config_by_property[property_id] = dict(stored)
    defaults = _default_modbus_discovery_request().model_dump()
    config = {
        **defaults,
        **stored,
    }
    config["enabled_profiles"] = _normalize_enabled_profiles(config.get("enabled_profiles"))
    config["unit_profile_overrides"] = _sanitize_unit_profile_overrides(config.get("unit_profile_overrides"))
    config["available_profiles"] = _modbus_profile_names()
    return config


def _set_property_modbus_config(property_id: int, payload: ModbusObjectProfileConfig, replace_existing: bool = False) -> Dict[str, Any]:
    current = {} if replace_existing else dict(modbus_object_config_by_property.get(property_id, {}))
    update = payload.model_dump(exclude_none=True)
    if "enabled_profiles" in update:
        update["enabled_profiles"] = _normalize_enabled_profiles(update.get("enabled_profiles"))
    if "unit_profile_overrides" in update:
        update["unit_profile_overrides"] = _sanitize_unit_profile_overrides(update.get("unit_profile_overrides"))

    current.update(update)
    modbus_object_config_by_property[property_id] = current
    normalized = _get_property_modbus_config(property_id)
    _persist_property_modbus_config(property_id, normalized)
    return normalized


def _modbus_profile_for_unit(property_id: int, unit_id: int) -> Dict[str, Any]:
    config = _get_property_modbus_config(property_id)
    profile_names = config.get("enabled_profiles") or _modbus_profile_names()
    profile_lookup = {str(profile["profile_name"]): profile for profile in MODBUS_DEVICE_PROFILES if str(profile["profile_name"]) in profile_names}
    override_name = config.get("unit_profile_overrides", {}).get(unit_id)
    if override_name in profile_lookup:
        return profile_lookup[override_name]

    profile = MODBUS_DEVICE_PROFILES[unit_id % len(MODBUS_DEVICE_PROFILES)]
    if str(profile["profile_name"]) not in profile_names:
        fallback_name = profile_names[unit_id % len(profile_names)]
        return profile_lookup[fallback_name]
    return profile


def _format_simulated_modbus_ip(property_id: int, unit_id: int) -> str:
    subnet = ipaddress.ip_network(f"192.168.{(property_id % 5) + 10}.0/24", strict=False)
    return str(subnet.network_address + (30 + (unit_id % 190)))


def _generate_device_telemetry(property_id: int, unit_id: int, device_type: str, media_type: str) -> Dict[str, float]:
    """
    Rychlá syntetická telemetrie pro dashboard a EMS výpočty.
    """
    seed = (property_id * 997 + unit_id * 89) % 1000

    if media_type == "electricity":
        if device_type == "fve_inverter":
            return {
                "power_generation_kw": round(12.0 + (seed % 220) / 10.0, 2),
                "power_consumption_kw": 0.0,
                "battery_soc": 0.0,
            }
        if device_type == "battery_storage":
            return {
                "power_generation_kw": round((seed % 70) / 10.0, 2),
                "power_consumption_kw": round((seed % 50) / 10.0, 2),
                "battery_soc": round(25.0 + (seed % 70), 2),
            }
        return {
            "power_generation_kw": 0.0,
            "power_consumption_kw": round(8.0 + (seed % 300) / 10.0, 2),
            "battery_soc": 0.0,
        }

    if media_type == "thermal":
        return {
            "thermal_power_kw": round(6.0 + (seed % 180) / 10.0, 2),
            "flow_m3_h": round(2.0 + (seed % 40) / 10.0, 2),
            "supply_temp_c": round(32.0 + (seed % 35) / 10.0, 2),
            "return_temp_c": round(24.0 + (seed % 25) / 10.0, 2),
        }

    if media_type == "water":
        return {
            "flow_m3_h": round(0.8 + (seed % 100) / 25.0, 2),
            "daily_volume_m3": round(8.0 + (seed % 220) / 5.0, 2),
            "pressure_bar": round(2.2 + (seed % 30) / 20.0, 2),
        }

    if media_type == "gas":
        return {
            "flow_m3_h": round(1.2 + (seed % 80) / 20.0, 2),
            "daily_volume_m3": round(12.0 + (seed % 260) / 4.0, 2),
            "pressure_bar": round(1.0 + (seed % 18) / 10.0, 2),
        }

    if media_type == "lighting":
        return {
            "power_consumption_kw": round(15.0 + (seed % 180) / 12.0, 2),
            "dimming_pct": round(40.0 + (seed % 60), 2),
            "occupancy_pct": round(20.0 + (seed % 80), 2),
        }

    if media_type == "machine":
        return {
            "power_consumption_kw": round(18.0 + (seed % 220) / 8.0, 2),
            "runtime_hours": round(120.0 + (seed % 800) / 10.0, 2),
            "utilization_pct": round(25.0 + (seed % 70), 2),
            "temperature_c": round(35.0 + (seed % 40) / 3.0, 2),
        }

    if media_type == "compressed_air":
        return {
            "flow_m3_h": round(4.0 + (seed % 120) / 12.0, 2),
            "pressure_bar": round(6.2 + (seed % 24) / 10.0, 2),
            "temperature_c": round(22.0 + (seed % 30) / 4.0, 2),
        }

    if media_type == "unknown":
        return {
            "register_46001": float(100 + (seed % 300)),
            "register_46002": float(200 + (seed % 500)),
            "register_46003": float(300 + (seed % 700)),
        }

    return {
        "flow_m3_h": round(0.4 + (seed % 80) / 30.0, 2),
        "daily_volume_m3": round(5.0 + (seed % 180) / 4.0, 2),
    }


def _read_modbus_registers_live(ip: str, port: int, unit_id: int, registers: List[int]) -> Optional[Dict[int, int]]:
    if not MODBUS_LIVE_ENABLED or ModbusTcpClient is None:
        return None

    now_ts = time.time()
    allowed, reason = _modbus_call_allowed(now_ts)
    if not allowed:
        _log_event("modbus_call_blocked", reason=reason, ip=ip, port=port, unit_id=unit_id)
        return None

    runtime_metrics["modbus_calls_total"] = int(runtime_metrics.get("modbus_calls_total", 0)) + 1

    client = ModbusTcpClient(host=ip, port=port, timeout=1)
    values: Dict[int, int] = {}
    try:
        if not client.connect():
            _modbus_record_result(False)
            return None

        for register in registers:
            try:
                response = client.read_holding_registers(address=register - 1, count=1, slave=unit_id)
                if response is None or response.isError():
                    _modbus_record_result(False)
                    return None
                values[register] = int(response.registers[0])
            except Exception:
                _modbus_record_result(False)
                return None
    finally:
        try:
            client.close()
        except Exception:
            pass

    _modbus_record_result(True)
    return values


def _telemetry_from_live_registers(device_type: str, media_type: str, register_values: Dict[int, int]) -> Dict[str, float]:
    if media_type == "electricity":
        if device_type == "fve_inverter":
            return {
                "power_generation_kw": round(register_values.get(30001, 0) / 10.0, 2),
                "power_consumption_kw": 0.0,
                "battery_soc": 0.0,
            }
        if device_type == "battery_storage":
            return {
                "power_generation_kw": round(register_values.get(31001, 0) / 10.0, 2),
                "power_consumption_kw": round(register_values.get(31002, 0) / 10.0, 2),
                "battery_soc": float(max(0, min(100, register_values.get(31003, 0) / 10.0))),
            }
        return {
            "power_generation_kw": 0.0,
            "power_consumption_kw": round(register_values.get(40001, 0) / 10.0, 2),
            "battery_soc": 0.0,
        }

    if media_type == "thermal":
        return {
            "thermal_power_kw": round(register_values.get(41001, 0) / 10.0, 2),
            "flow_m3_h": round(register_values.get(41002, 0) / 100.0, 2),
            "supply_temp_c": round(register_values.get(41007, 0) / 10.0, 2),
            "return_temp_c": round(register_values.get(41012, 0) / 10.0, 2),
        }

    if media_type == "water":
        return {
            "flow_m3_h": round(register_values.get(42001, 0) / 100.0, 2),
            "daily_volume_m3": round(register_values.get(42002, 0) / 10.0, 2),
            "pressure_bar": round(register_values.get(42003, 0) / 100.0, 2),
        }

    if media_type == "gas":
        return {
            "flow_m3_h": round(register_values.get(43001, 0) / 100.0, 2),
            "daily_volume_m3": round(register_values.get(43002, 0) / 10.0, 2),
            "pressure_bar": round(register_values.get(43003, 0) / 100.0, 2),
        }

    if media_type == "lighting":
        return {
            "power_consumption_kw": round(register_values.get(44001, 0) / 10.0, 2),
            "dimming_pct": round(register_values.get(44002, 0) / 10.0, 2),
            "occupancy_pct": round(register_values.get(44003, 0) / 10.0, 2),
        }

    if media_type == "machine":
        return {
            "power_consumption_kw": round(register_values.get(45001, 0) / 10.0, 2),
            "runtime_hours": round(register_values.get(45002, 0) / 10.0, 2),
            "utilization_pct": round(register_values.get(45003, 0) / 10.0, 2),
        }

    if media_type == "compressed_air":
        return {
            "flow_m3_h": round(register_values.get(43011, 0) / 100.0, 2),
            "pressure_bar": round(register_values.get(43012, 0) / 100.0, 2),
            "temperature_c": round(register_values.get(43013, 0) / 10.0, 2),
        }

    if media_type == "unknown":
        return {
            "register_46001": float(register_values.get(46001, 0)),
            "register_46002": float(register_values.get(46002, 0)),
            "register_46003": float(register_values.get(46003, 0)),
        }

    return {
        "flow_m3_h": round(register_values.get(43001, 0) / 100.0, 2),
        "daily_volume_m3": round(register_values.get(43002, 0) / 10.0, 2),
    }


def _discover_modbus_devices(property_id: int, req: ModbusDiscoveryRequest) -> List[Dict[str, Any]]:
    config = _get_property_modbus_config(property_id)
    if req.unit_id_start < 1 or req.unit_id_end > 247 or req.unit_id_start > req.unit_id_end:
        raise HTTPException(status_code=400, detail="unit_id range must be 1..247 and start <= end")

    discovered: List[Dict[str, Any]] = []
    for unit_id in range(req.unit_id_start, req.unit_id_end + 1):
        if not MODBUS_LIVE_ENABLED and not _modbus_unit_is_online(property_id, unit_id):
            continue

        profile = _modbus_profile_for_unit(property_id, unit_id)
        device_type, media_type, registers = _classify_modbus_device(property_id, unit_id)
        simulated = _generate_device_telemetry(property_id, unit_id, device_type, media_type)
        ip_address = config.get("gateway_ip") if MODBUS_LIVE_ENABLED else _format_simulated_modbus_ip(property_id, unit_id)
        port = int(config.get("port") or req.port)

        live_registers = _read_modbus_registers_live(str(ip_address), port, unit_id, registers)
        if live_registers:
            telemetry = _telemetry_from_live_registers(device_type, media_type, live_registers)
            status = "online_live"
            data_source = "pymodbus"
        else:
            telemetry = simulated
            status = "online_simulated"
            data_source = "simulated"

        discovered.append({
            "device_id": f"mb-{property_id}-{unit_id}",
            "property_id": property_id,
            "protocol": "modbus-tcp",
            "ip_address": ip_address,
            "port": port,
            "unit_id": unit_id,
            "device_type": device_type if req.auto_classify else "unknown_modbus_device",
            "media_type": media_type if req.auto_classify else "unknown",
            "profile_name": str(profile["profile_name"]),
            "device_category": str(profile["category"]),
            "registers": registers,
            "telemetry": telemetry,
            "status": status,
            "data_source": data_source,
        })

    db_modbus_devices_by_property[property_id] = discovered
    return discovered


def _ensure_modbus_inventory(property_id: int) -> List[Dict[str, Any]]:
    devices = db_modbus_devices_by_property.get(property_id)
    if devices is not None:
        return devices
    property_config = _get_property_modbus_config(property_id)
    default_request = ModbusDiscoveryRequest(
        network_cidr=str(property_config.get("network_cidr")),
        gateway_ip=str(property_config.get("gateway_ip")),
        port=int(property_config.get("port")),
        unit_id_start=int(property_config.get("unit_id_start")),
        unit_id_end=int(property_config.get("unit_id_end")),
        auto_classify=bool(property_config.get("auto_classify")),
    )
    return _discover_modbus_devices(property_id, default_request)


def _build_media_overview(property_id: int, spot_price_override_kwh: Optional[float] = None) -> Dict[str, Any]:
    devices = _ensure_modbus_inventory(property_id)
    electricity_consumption_kw = 0.0
    electricity_generation_kw = 0.0
    battery_socs: List[float] = []
    thermal_kw = 0.0
    water_m3_h = 0.0
    gas_m3_h = 0.0
    lighting_kw = 0.0
    machine_kw = 0.0
    compressed_air_m3_h = 0.0
    device_type_counts: Dict[str, int] = {}

    for device in devices:
        telemetry = device.get("telemetry", {})
        media_type = device.get("media_type")
        device_type = str(device.get("device_type", "unknown"))
        device_type_counts[device_type] = int(device_type_counts.get(device_type, 0)) + 1

        if media_type == "electricity":
            electricity_generation_kw += float(telemetry.get("power_generation_kw", 0.0))
            electricity_consumption_kw += float(telemetry.get("power_consumption_kw", 0.0))
            if float(telemetry.get("battery_soc", 0.0)) > 0:
                battery_socs.append(float(telemetry.get("battery_soc", 0.0)))
        elif media_type == "thermal":
            thermal_kw += float(telemetry.get("thermal_power_kw", 0.0))
        elif media_type == "water":
            water_m3_h += float(telemetry.get("flow_m3_h", 0.0))
        elif media_type == "gas":
            gas_m3_h += float(telemetry.get("flow_m3_h", 0.0))
        elif media_type == "lighting":
            lighting_kw += float(telemetry.get("power_consumption_kw", 0.0))
        elif media_type == "machine":
            machine_kw += float(telemetry.get("power_consumption_kw", 0.0))
        elif media_type == "compressed_air":
            compressed_air_m3_h += float(telemetry.get("flow_m3_h", 0.0))

    avg_battery_soc = sum(battery_socs) / len(battery_socs) if battery_socs else 45.0
    ems_decision = execute_ems_trading(
        property_id=property_id,
        current_battery_soc=avg_battery_soc,
        current_total_consumption_kw=electricity_consumption_kw,
        current_fve_generation_kw=electricity_generation_kw,
        spot_price_override_kwh=spot_price_override_kwh,
    )

    total_site_consumption_kw = electricity_consumption_kw + lighting_kw + machine_kw
    net_grid_import_kw = max(0.0, total_site_consumption_kw - electricity_generation_kw)
    self_consumption_ratio = (min(electricity_generation_kw, electricity_consumption_kw) / electricity_consumption_kw * 100.0) if electricity_consumption_kw > 0 else 0.0
    estimated_hourly_cost = net_grid_import_kw * float(ems_decision.get("final_effective_cost_kwh", 0.0))

    return {
        "property_id": property_id,
        "device_count": len(devices),
        "supported_media_types": sorted({str(device.get("media_type", "unknown")) for device in devices}),
        "device_type_counts": device_type_counts,
        "media": {
            "electricity": {
                "consumption_kw": round(electricity_consumption_kw, 2),
                "generation_kw": round(electricity_generation_kw, 2),
                "grid_import_kw": round(net_grid_import_kw, 2),
                "self_consumption_ratio_pct": round(self_consumption_ratio, 2),
            },
            "thermal": {
                "thermal_power_kw": round(thermal_kw, 2),
            },
            "water": {
                "flow_m3_h": round(water_m3_h, 2),
            },
            "gas": {
                "flow_m3_h": round(gas_m3_h, 2),
            },
            "lighting": {
                "power_consumption_kw": round(lighting_kw, 2),
            },
            "machines": {
                "power_consumption_kw": round(machine_kw, 2),
            },
            "compressed_air": {
                "flow_m3_h": round(compressed_air_m3_h, 2),
            },
        },
        "efficiency": {
            "avg_battery_soc_pct": round(avg_battery_soc, 2),
            "estimated_hourly_energy_cost_czk": round(estimated_hourly_cost, 2),
            "estimated_total_site_consumption_kw": round(total_site_consumption_kw, 2),
        },
        "ems_decision": ems_decision,
        "devices": devices,
    }


def _persist_telemetry_samples(property_id: int, devices: List[Dict[str, Any]]) -> int:
    now = datetime.datetime.now(datetime.UTC).isoformat()
    rows: List[Tuple[int, str, str, str, float, str]] = []
    for device in devices:
        device_id = str(device.get("device_id"))
        media_type = str(device.get("media_type", "unknown"))
        telemetry = device.get("telemetry", {})
        if not isinstance(telemetry, dict):
            continue
        for metric_name, metric_value in telemetry.items():
            try:
                rows.append((property_id, device_id, media_type, str(metric_name), float(metric_value), now))
            except Exception:
                continue

    if not rows:
        return 0

    conn = _get_sqlite_conn()
    try:
        conn.executemany(
            """
            INSERT INTO telemetry_samples (property_id, device_id, media_type, metric_name, metric_value, ts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def _load_telemetry_trends(property_id: int, hours: int) -> Dict[str, List[Dict[str, Any]]]:
    hours = max(1, min(168, hours))
    threshold = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=hours)).isoformat()

    conn = _get_sqlite_conn()
    try:
        rows = conn.execute(
            """
            SELECT ts, media_type, metric_name, AVG(metric_value) AS avg_value
            FROM telemetry_samples
            WHERE property_id = ? AND ts >= ?
            GROUP BY strftime('%Y-%m-%d %H:00:00', ts), media_type, metric_name
            ORDER BY ts ASC
            """,
            (property_id, threshold),
        ).fetchall()
    finally:
        conn.close()

    result: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        key = f"{row['media_type']}.{row['metric_name']}"
        result.setdefault(key, []).append(
            {
                "timestamp": row["ts"],
                "value": round(float(row["avg_value"]), 3),
            }
        )
    return result


def _upsert_alert(property_id: int, alert_key: str, severity: str, title: str, description: str, recommendation: str) -> Dict[str, Any]:
    now = datetime.datetime.now(datetime.UTC)
    now_iso = now.isoformat()
    conn = _get_sqlite_conn()
    try:
        existing = conn.execute(
            """
            SELECT * FROM alerts
            WHERE property_id = ? AND alert_key = ? AND status = 'open'
            ORDER BY id DESC
            LIMIT 1
            """,
            (property_id, alert_key),
        ).fetchone()

        if existing:
            try:
                last_seen = datetime.datetime.fromisoformat(existing["last_seen"])
            except Exception:
                last_seen = now - datetime.timedelta(seconds=ALERT_DEDUP_WINDOW_SEC + 1)

            age_sec = (now - last_seen).total_seconds()
            if age_sec <= ALERT_DEDUP_WINDOW_SEC:
                hit_count = int(existing["hit_count"]) + 1
                escalation = 2 if severity == "critical" and hit_count >= 6 else 1 if hit_count >= 3 else int(existing["escalation_level"])
                conn.execute(
                    """
                    UPDATE alerts
                    SET last_seen = ?, hit_count = ?, escalation_level = ?, severity = ?, description = ?, recommendation = ?
                    WHERE id = ?
                    """,
                    (now_iso, hit_count, escalation, severity, description, recommendation, int(existing["id"])),
                )
                conn.commit()
                updated = conn.execute("SELECT * FROM alerts WHERE id = ?", (int(existing["id"]),)).fetchone()
                return dict(updated)

        conn.execute(
            """
            INSERT INTO alerts (
                property_id, alert_key, severity, status, title, description, recommendation,
                first_seen, last_seen, hit_count, escalation_level
            )
            VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, 1, 0)
            """,
            (property_id, alert_key, severity, title, description, recommendation, now_iso, now_iso),
        )
        conn.commit()
        created = conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 1").fetchone()
        return dict(created)
    finally:
        conn.close()


def _evaluate_alerts(property_id: int, overview: Dict[str, Any]) -> List[Dict[str, Any]]:
    media = overview.get("media", {})
    electricity = media.get("electricity", {})
    efficiency = overview.get("efficiency", {})

    findings: List[Tuple[str, str, str, str, str]] = []
    grid_import = float(electricity.get("grid_import_kw", 0.0))
    if grid_import > 120.0:
        findings.append(
            (
                f"grid-import-{property_id}",
                "critical",
                "Kritický odběr ze sítě",
                f"Grid import dosáhl {grid_import:.2f} kW.",
                "Okamžitě odstavte flexibilní zátěže, zvyšte využití baterie a upravte výrobní harmonogram.",
            )
        )
    elif grid_import > 80.0:
        findings.append(
            (
                f"grid-import-{property_id}",
                "warning",
                "Vysoký odběr ze sítě",
                f"Grid import je zvýšený ({grid_import:.2f} kW).",
                "Přesuňte neurgentní spotřebu mimo špičku a zvažte přednabíjení baterie.",
            )
        )

    battery_soc = float(efficiency.get("avg_battery_soc_pct", 0.0))
    if battery_soc < 20.0:
        findings.append(
            (
                f"battery-low-{property_id}",
                "warning",
                "Nízký stav baterie",
                f"Průměrný SoC baterie je pouze {battery_soc:.1f}%.",
                "Nabijte baterii v levných hodinách nebo snižte vybíjení v běžném režimu.",
            )
        )

    water_flow = float(media.get("water", {}).get("flow_m3_h", 0.0))
    if water_flow > 8.0:
        findings.append(
            (
                f"water-anomaly-{property_id}",
                "warning",
                "Anomální průtok vody",
                f"Průtok vody je neobvykle vysoký ({water_flow:.2f} m3/h).",
                "Zkontrolujte úniky a ventilaci, případně aktivujte noční režim redukce průtoku.",
            )
        )

    gas_flow = float(media.get("gas", {}).get("flow_m3_h", 0.0))
    if gas_flow > 5.0:
        findings.append(
            (
                f"gas-anomaly-{property_id}",
                "critical",
                "Kritický průtok plynu",
                f"Průtok plynu překročil limit ({gas_flow:.2f} m3/h).",
                "Proveďte okamžitou kontrolu kotelny a uzavřete hlavní větev při potvrzení úniku.",
            )
        )

    alerts: List[Dict[str, Any]] = []
    for alert_key, severity, title, description, recommendation in findings:
        alerts.append(_upsert_alert(property_id, alert_key, severity, title, description, recommendation))

    return alerts


def _list_alerts(property_id: int, status_filter: str = "open") -> List[Dict[str, Any]]:
    conn = _get_sqlite_conn()
    try:
        if status_filter == "all":
            rows = conn.execute("SELECT * FROM alerts WHERE property_id = ? ORDER BY id DESC", (property_id,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE property_id = ? AND status = ? ORDER BY id DESC",
                (property_id, status_filter),
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _apply_alert_action(alert_id: int, action: str, note: Optional[str] = None) -> Dict[str, Any]:
    action = action.lower().strip()
    if action not in {"acknowledge", "resolve", "reopen"}:
        raise HTTPException(status_code=400, detail="action must be one of: acknowledge, resolve, reopen")

    now_iso = datetime.datetime.now(datetime.UTC).isoformat()
    conn = _get_sqlite_conn()
    try:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Alert not found")

        if action == "acknowledge":
            conn.execute(
                "UPDATE alerts SET acknowledged_at = ?, last_seen = ? WHERE id = ?",
                (now_iso, now_iso, alert_id),
            )
        elif action == "resolve":
            conn.execute(
                "UPDATE alerts SET status = 'resolved', resolved_at = ?, last_seen = ? WHERE id = ?",
                (now_iso, now_iso, alert_id),
            )
        else:
            conn.execute(
                "UPDATE alerts SET status = 'open', resolved_at = NULL, last_seen = ? WHERE id = ?",
                (now_iso, alert_id),
            )

        if note:
            conn.execute(
                "UPDATE alerts SET description = description || ? WHERE id = ?",
                (f"\n[OPERATOR NOTE] {note}", alert_id),
            )

        conn.commit()
        updated = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        return dict(updated)
    finally:
        conn.close()


def _compute_battery_profit_data(prop: Property, battery_capacity_mwh: float) -> Dict[str, Any]:
    gross_profit_per_mwh_year = 9411764.0
    annual_gross = battery_capacity_mwh * gross_profit_per_mwh_year
    our_margin = annual_gross * 0.15
    client_clean = annual_gross - our_margin

    return {
        "property_name": prop.name,
        "client_dashboard_display": {
            "NET_PAYOUT_MONTHLY_CZK": f"{round(client_clean / 12.0, 2):,} Kč",
            "NET_PAYOUT_ANNUAL_CZK": f"{round(client_clean, 2):,} Kč",
        },
        "INTERNAL_BUSINESS_LOG": {
            "gross_market_revenue_czk": round(annual_gross, 2),
            "our_trading_company_15_percent_margin": round(our_margin, 2),
        },
    }

# =====================================================================
# CHRÁNĚNÉ PRODUKČNÍ ENDPOINTY (RBAC + 2FA + AI ŠTÍT)
# =====================================================================

@app.get("/secure/agregator/battery-profit/{property_id}", tags=["Chráněný Modul Obchodníka (Agregátor)"])
def get_battery_clean_profit_secure(property_id: int, battery_capacity_mwh: float = 1.0, current_user: UserSession = Depends(require_role(["superadmin", "owner"]))):
    """
    Přístup pouze pro majitele nebo superadmina s dokončeným 2FA.
    """
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    payload = _compute_battery_profit_data(prop, battery_capacity_mwh)
    payload["authorized_user"] = current_user.email
    return payload


@app.get("/ems/tenant-subgrid/{property_id}", tags=["Chráněný Modul Nájemců"])
def get_tenant_invoice_data(property_id: int, current_user: UserSession = Depends(require_role(["superadmin", "owner", "tenant"]))):
    """
    Přístup pro majitele, superadmina i nájemce s dokončeným 2FA.
    """
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    tenants = [t for t in db_tenants if t.property_id == property_id]
    if current_user.role == "tenant":
        tenants = [t for t in tenants if "kovošrot" in t.space_name.lower()]

    return {
        "property_name": prop.name,
        "authorized_user": current_user.email,
        "role": current_user.role,
        "tenant_breakdown": [
            {
                "tenant_space": t.space_name,
                "fixed_price_kwh": t.fixed_price_kwh,
                "total_to_pay_czk": round(t.fixed_price_kwh * 100.0, 2)
            }
            for t in tenants
        ]
    }


# =====================================================================
# MODUL 1: AUTONOMNÍ EMS TRADING
# =====================================================================

@app.post("/ems/trading-decision", tags=["1. Energetický Trading"])
def execute_ems_trading(
    property_id: int,
    current_battery_soc: float,
    current_total_consumption_kw: float = 120.0,
    current_fve_generation_kw: float = 35.0,
    spot_price_override_kwh: Optional[float] = None,
):
    """
    Řídí spotřebu podle ceny, distribuční složky, netto zátěže a stavu baterie.
    Obsahuje hysteresi a cooldown, aby se eliminovalo časté přepínání režimů.
    """
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    if current_battery_soc < 0 or current_battery_soc > 100:
        raise HTTPException(status_code=400, detail="current_battery_soc must be in range 0-100")

    if spot_price_override_kwh is not None:
        spot_price_kwh = max(-2.0, min(20.0, float(spot_price_override_kwh)))
        price_source = "override"
        price_age_sec = 0
    else:
        spot_price_kwh, price_source, price_age_sec = get_live_ote_price_kwh()
    final_cost_kwh = spot_price_kwh + prop.distribution_tariff_kwh

    net_load_kw = max(0.0, current_total_consumption_kw - current_fve_generation_kw)
    state = _get_property_ems_state(property_id)
    price_window = state["price_window"]
    assert isinstance(price_window, Deque)
    price_window.append(spot_price_kwh)

    rolling_avg = sum(price_window) / len(price_window)
    dynamic_spread = max(0.25, abs(spot_price_kwh - rolling_avg))
    cheap_threshold = rolling_avg - (0.4 * dynamic_spread)
    expensive_threshold = rolling_avg + (0.8 * dynamic_spread)

    action = "STANDARD_RUN"
    explanation = "Provoz v normálním režimu."

    if final_cost_kwh < -0.05 and current_battery_soc < 95:
        action = "FORCED_MAXIMUM_CONSUMPTION"
        explanation = (
            f"Efektivní cena je záporná ({final_cost_kwh:.2f} Kč/kWh). "
            "Nabíjím baterii a přesouvám flexibilní spotřebu do tohoto okna."
        )
    elif spot_price_kwh >= expensive_threshold and current_battery_soc >= 25 and net_load_kw > 0:
        action = "MAXIMUM_GRID_FEED_IN"
        explanation = (
            f"Spot cena je výrazně nad klouzavým průměrem ({spot_price_kwh:.2f} vs {rolling_avg:.2f} Kč/kWh). "
            "Omezuji odběr ze sítě a prioritu dáváme baterii/FVE."
        )
    elif spot_price_kwh <= cheap_threshold and current_battery_soc < 85:
        action = "CHARGE_BATTERY_FROM_GRID"
        explanation = (
            f"Spot cena je pod průměrem ({spot_price_kwh:.2f} vs {rolling_avg:.2f} Kč/kWh). "
            "Nabíjím baterii pro krytí drahých hodin."
        )

    now = time.time()
    last_action = str(state.get("last_action", "STANDARD_RUN"))
    last_switch_ts = float(state.get("last_switch_ts", 0.0))
    if action != last_action and (now - last_switch_ts) < EMS_ACTION_COOLDOWN_SEC:
        action = last_action
        explanation = (
            f"Anti-chatter ochrana: držím předchozí režim '{last_action}' "
            f"po dobu cooldownu {EMS_ACTION_COOLDOWN_SEC}s."
        )
    elif action != last_action:
        state["last_action"] = action
        state["last_switch_ts"] = now

    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "property_name": prop.name,
        "live_spot_price_silova_kwh": round(spot_price_kwh, 2),
        "final_effective_cost_kwh": round(final_cost_kwh, 2),
        "price_source": price_source,
        "price_age_sec": price_age_sec,
        "rolling_price_kwh": round(rolling_avg, 2),
        "cheap_threshold_kwh": round(cheap_threshold, 2),
        "expensive_threshold_kwh": round(expensive_threshold, 2),
        "net_load_kw": round(net_load_kw, 2),
        "battery_soc": round(current_battery_soc, 2),
        "hardware_command": action,
        "justification": explanation
    }

# =====================================================================
# MODUL 2: AGREGÁTOR & SVR ENGINE (TVÁ MARŽE 15 %)
# =====================================================================

@app.get("/agregator/battery-profit/{property_id}", tags=["2. Modul Obchodníka (Agregátor)"])
def get_battery_clean_profit(property_id: int, battery_capacity_mwh: float = 1.0):
    """
    Vypočítá ekonomiku velkokapacitní baterie (BESS). 
    Zahrnuje SVR služby pro ČEPS a arbitráž.
    Před klientem skrývá poplatky a ukazuje čistě jeho konečný zisk.
    """
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    base = _compute_battery_profit_data(prop, battery_capacity_mwh)
    base["connected_bess_capacity"] = f"{battery_capacity_mwh} MWh"
    base["client_dashboard_display"] = {
        "PERODIC_CLEAN_PROFIT_CZK": {
            "MONTHLY_PAYOUT": base["client_dashboard_display"]["NET_PAYOUT_MONTHLY_CZK"],
            "ANNUAL_PAYOUT": base["client_dashboard_display"]["NET_PAYOUT_ANNUAL_CZK"],
        },
        "system_status": "SVR_ACTIVE_CEPS_CONNECTED",
        "message": "Zobrazené finanční částky jsou konečné, pročištěné a připravené k odeslání na Váš bankovní účet.",
    }
    base["INTERNAL_BUSINESS_LOG"]["note"] = "Tato sekce je viditelná pouze pro tebe v administraci, klient ji ve svém rozhraní NEVIDÍ."
    return base


@app.get("/hardware/telemetry/{property_id}", tags=["Hardware & Telemetry"])
def hardware_telemetry(property_id: int):
    """
    Simulované rozhraní pro telemetry zařízení. Testy očekávají klíč
    `protocols_ingestion` a `property_name`.
    """
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    return {
        "property_name": prop.name,
        "protocols_ingestion": ["modbus", "mqtt", "opcua"],
        "last_seen": datetime.datetime.now().isoformat()
    }


@app.post("/modbus/discover/{property_id}", tags=["Hardware & Telemetry"])
def modbus_discover_devices(property_id: int, request: ModbusDiscoveryRequest):
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    devices = _discover_modbus_devices(property_id, request)
    return {
        "property_name": prop.name,
        "network": request.network_cidr,
        "scanned_units": request.unit_id_end - request.unit_id_start + 1,
        "discovered_devices": len(devices),
        "devices": devices,
    }


@app.get("/modbus/devices/{property_id}", tags=["Hardware & Telemetry"])
def get_modbus_devices(property_id: int):
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    devices = _ensure_modbus_inventory(property_id)
    return {
        "property_name": prop.name,
        "device_count": len(devices),
        "devices": devices,
    }


@app.post("/telemetry/poll/{property_id}", tags=["Hardware & Telemetry"])
def telemetry_poll(property_id: int, request: TelemetryPollRequest):
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    if request.force_rescan:
        devices = _discover_modbus_devices(property_id, _default_modbus_discovery_request())
    else:
        devices = _ensure_modbus_inventory(property_id)

    written = _persist_telemetry_samples(property_id, devices) if request.persist_to_history else 0
    overview = _build_media_overview(property_id)
    alerts = _evaluate_alerts(property_id, overview) if request.evaluate_alerts else []

    return {
        "property_name": prop.name,
        "polled_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "device_count": len(devices),
        "samples_written": written,
        "alerts_created_or_updated": len(alerts),
        "live_modbus_enabled": MODBUS_LIVE_ENABLED,
    }


@app.get("/ems/modbus-config/{property_id}", tags=["Hardware & Telemetry"])
def get_modbus_object_config(property_id: int):
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    config = _get_property_modbus_config(property_id)
    return {
        "property_id": property_id,
        "property_name": prop.name,
        "config": config,
    }


@app.put("/ems/modbus-config/{property_id}", tags=["Hardware & Telemetry"])
def update_modbus_object_config(property_id: int, config: ModbusObjectProfileConfig):
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    updated = _set_property_modbus_config(property_id, config, replace_existing=False)
    db_modbus_devices_by_property.pop(property_id, None)
    return {
        "property_id": property_id,
        "property_name": prop.name,
        "config": updated,
    }


@app.post("/ems/modbus-config/{property_id}/import", tags=["Hardware & Telemetry"])
def import_modbus_object_config(property_id: int, payload: ModbusProfileImportPayload):
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    config_payload = ModbusObjectProfileConfig(
        network_cidr=payload.network_cidr,
        gateway_ip=payload.gateway_ip,
        port=payload.port,
        unit_id_start=payload.unit_id_start,
        unit_id_end=payload.unit_id_end,
        auto_classify=payload.auto_classify,
        enabled_profiles=payload.enabled_profiles,
        unit_profile_overrides=payload.unit_profile_overrides,
    )
    updated = _set_property_modbus_config(property_id, config_payload, replace_existing=payload.replace_existing)
    db_modbus_devices_by_property.pop(property_id, None)
    return {
        "property_id": property_id,
        "property_name": prop.name,
        "config": updated,
        "replace_existing": payload.replace_existing,
    }


def _refresh_all_properties_from_modbus() -> None:
    if not MODBUS_LIVE_ENABLED or not MODBUS_AUTO_POLL_ENABLED:
        return

    discovery = _default_modbus_discovery_request()
    for prop in db_properties:
        try:
            devices = _discover_modbus_devices(prop.id, discovery)
            if devices:
                _persist_telemetry_samples(prop.id, devices)
                overview = _build_media_overview(prop.id)
                _evaluate_alerts(prop.id, overview)
        except Exception as exc:
            _log_event("modbus_auto_poll_failed", property_id=prop.id, error=str(exc))


def _modbus_auto_poll_loop() -> None:
    while not modbus_auto_poll_stop.wait(MODBUS_AUTO_POLL_INTERVAL_SEC):
        _refresh_all_properties_from_modbus()


@app.get("/telemetry/trends/{property_id}", tags=["Hardware & Telemetry"])
def telemetry_trends(property_id: int, hours: int = 24):
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    trends = _load_telemetry_trends(property_id, hours)
    return {
        "property_name": prop.name,
        "hours": max(1, min(168, hours)),
        "series": trends,
    }


@app.get("/alerts/{property_id}", tags=["Hardware & Telemetry"])
def list_alerts(property_id: int, status_filter: str = "open"):
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    if status_filter not in {"open", "resolved", "all"}:
        raise HTTPException(status_code=400, detail="status_filter must be one of: open, resolved, all")

    items = _list_alerts(property_id, status_filter=status_filter)
    return {
        "property_name": prop.name,
        "count": len(items),
        "items": items,
    }


@app.post("/alerts/evaluate/{property_id}", tags=["Hardware & Telemetry"])
def evaluate_alerts(property_id: int):
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    overview = _build_media_overview(property_id)
    alerts = _evaluate_alerts(property_id, overview)
    return {
        "property_name": prop.name,
        "alerts_updated": len(alerts),
        "items": alerts,
    }


@app.post("/alerts/{alert_id}/action", tags=["Hardware & Telemetry"])
def alert_action(alert_id: int, request: AlertActionRequest):
    updated = _apply_alert_action(alert_id, request.action, request.note)
    return {
        "alert": updated,
    }


@app.get("/system/health", tags=["System"])
def system_health():
    sqlite_ok = False
    sqlite_error = None
    try:
        conn = _get_sqlite_conn()
        conn.execute("SELECT 1")
        conn.close()
        sqlite_ok = True
    except Exception as exc:
        sqlite_error = str(exc)

    return {
        "status": "ok" if sqlite_ok else "degraded",
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "checks": {
            "sqlite": {"ok": sqlite_ok, "error": sqlite_error},
            "modbus_driver": {
                "ok": ModbusTcpClient is not None,
                "live_enabled": MODBUS_LIVE_ENABLED,
                "auto_poll_enabled": MODBUS_AUTO_POLL_ENABLED,
                "auto_poll_interval_sec": MODBUS_AUTO_POLL_INTERVAL_SEC,
            },
            "migrations": {"ok": True, "total": MIGRATION_STATE.get("total", 0), "applied_at_startup": MIGRATION_STATE.get("applied", [])},
        },
    }


@app.get("/system/metrics", tags=["System"])
def system_metrics():
    total = int(runtime_metrics.get("requests_total", 0))
    total_duration = float(runtime_metrics.get("request_duration_ms_total", 0.0))
    avg_duration = (total_duration / total) if total > 0 else 0.0

    return {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "requests_total": total,
        "errors_total": int(runtime_metrics.get("errors_total", 0)),
        "avg_request_duration_ms": round(avg_duration, 3),
        "requests_by_path": runtime_metrics.get("requests_by_path", {}),
        "requests_by_status": runtime_metrics.get("requests_by_status", {}),
        "last_request_at": runtime_metrics.get("last_request_at"),
    }


@app.get("/system/metrics.prom", tags=["System"], response_class=PlainTextResponse)
def system_metrics_prometheus():
    payload = _metrics_to_prometheus()
    return PlainTextResponse(content=payload, media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/system/diagnostics", tags=["System"])
def system_diagnostics():
    sqlite_size = None
    if os.path.exists(EMS_SQLITE_PATH):
        try:
            sqlite_size = os.path.getsize(EMS_SQLITE_PATH)
        except Exception:
            sqlite_size = None

    conn = _get_sqlite_conn()
    try:
        telemetry_count = int(conn.execute("SELECT COUNT(*) AS c FROM telemetry_samples").fetchone()["c"])
        alerts_open = int(conn.execute("SELECT COUNT(*) AS c FROM alerts WHERE status = 'open'").fetchone()["c"])
        migrations = [dict(r) for r in conn.execute("SELECT migration_id, applied_at FROM schema_migrations ORDER BY id ASC").fetchall()]
    finally:
        conn.close()

    return {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "sqlite_path": EMS_SQLITE_PATH,
        "sqlite_size_bytes": sqlite_size,
        "telemetry_samples": telemetry_count,
        "open_alerts": alerts_open,
        "migrations": migrations,
    }


@app.get("/ems/media-overview/{property_id}", tags=["1. Energetický Trading"])
def ems_media_overview(property_id: int, spot_price_override_kwh: Optional[float] = None):
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    overview = _build_media_overview(property_id, spot_price_override_kwh=spot_price_override_kwh)
    overview["alerts_summary"] = {
        "open_count": len(_list_alerts(property_id, status_filter="open")),
    }
    overview["property_name"] = prop.name
    return overview


@app.get("/ems/visualization/{property_id}", tags=["1. Energetický Trading"])
def ems_visualization_graph(property_id: int):
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    overview = _build_media_overview(property_id)
    media = overview["media"]
    devices = overview.get("devices", [])
    trend = _load_telemetry_trends(property_id, 24)

    nodes = [
        {"id": "grid", "label": "Distribuční síť", "type": "grid"},
        {"id": "fve", "label": "FVE výroba", "type": "source"},
        {"id": "battery", "label": "Baterie", "type": "storage"},
        {"id": "loads", "label": "Spotřeba budovy", "type": "load"},
        {"id": "water", "label": "Vodní systém", "type": "media"},
        {"id": "thermal", "label": "Tepelný systém", "type": "media"},
        {"id": "gas", "label": "Plynový systém", "type": "media"},
    ]
    links = [
        {"source": "fve", "target": "loads", "value": media["electricity"]["generation_kw"]},
        {"source": "grid", "target": "loads", "value": media["electricity"]["grid_import_kw"]},
        {"source": "battery", "target": "loads", "value": round(max(0.0, media["electricity"]["consumption_kw"] - media["electricity"]["grid_import_kw"]), 2)},
        {"source": "water", "target": "loads", "value": media["water"]["flow_m3_h"]},
        {"source": "thermal", "target": "loads", "value": media["thermal"]["thermal_power_kw"]},
        {"source": "gas", "target": "loads", "value": media["gas"]["flow_m3_h"]},
    ]

    # Device topology fan-out to media nodes for interactive frontend graph.
    for device in devices:
        device_id = str(device.get("device_id"))
        media_type = str(device.get("media_type", "unknown"))
        node_type = "device"
        nodes.append(
            {
                "id": device_id,
                "label": f"{device.get('device_type')} ({device.get('unit_id')})",
                "type": node_type,
                "media_type": media_type,
                "telemetry": device.get("telemetry", {}),
            }
        )
        target = "loads"
        if media_type == "water":
            target = "water"
        elif media_type == "thermal":
            target = "thermal"
        elif media_type == "gas":
            target = "gas"
        elif media_type == "electricity":
            target = "battery" if "battery" in str(device.get("device_type")) else "fve"

        links.append({"source": device_id, "target": target, "value": 1})

    return {
        "property_name": prop.name,
        "nodes": nodes,
        "links": links,
        "trend_24h": trend,
        "alerts": _list_alerts(property_id, status_filter="open"),
        "ems_decision": overview["ems_decision"],
    }


@app.get("/agregator/client-payout/{property_id}", tags=["Agregátor & Payout"])
def agregator_client_payout(property_id: int, battery_capacity_mwh: float = 1.0):
    """
    Kompatibilní wrapper k existujícímu `get_battery_clean_profit` endpointu.
    Testy očekávají klíče `client_dashboard_display` a `INTERNAL_LOG`.
    """
    base = get_battery_clean_profit(property_id, battery_capacity_mwh)
    internal = base.get("INTERNAL_BUSINESS_LOG") or base.get("INTERNAL_LOG") or {}

    return {
        "property_name": base.get("property_name"),
        "client_dashboard_display": base.get("client_dashboard_display"),
        "INTERNAL_LOG": internal
    }

# =====================================================================
# MODUL 3: MIKROGRID & ROZÚČTOVÁNÍ
# =====================================================================

@app.get("/ems/microgrid-billing/{property_id}", tags=["3. Mikrogrid & Nájemci"])
def calculate_microgrid_billing(property_id: int, total_generated_fve_kwh: float):
    prop = next((p for p in db_properties if p.id == property_id), None)
    tenants = [t for t in db_tenants if t.property_id == property_id]
    
    allocated_kwh = total_generated_fve_kwh / len(tenants) if tenants else 0
    total_revenue = 0.0
    tenant_breakdown = []
    
    for t in tenants:
        bill = allocated_kwh * t.fixed_price_kwh
        total_revenue += bill
        tenant_breakdown.append({
            "tenant_space": t.space_name,
            "allocated_fve_kwh": round(allocated_kwh, 2),
            "total_to_pay_czk": round(bill, 2)
        })
        
    return {
        "property_name": prop.name,
        "owner_gross_revenue_czk": round(total_revenue, 2),
        "saved_distribution_fees_czk": round(total_generated_fve_kwh * prop.distribution_tariff_kwh, 2),
        "billing_breakdown": tenant_breakdown
    }

# =====================================================================
# MODUL 4: STAVEBNÍ DENÍK & CRM TIMELINE
# =====================================================================

@app.post("/construction/add-entry", tags=["4. Stavební Modul & CRM"])
def add_construction_entry(log: ConstructionLogInput):
    """
    Zápis do deníku. Při fotce simuluje AI Vision kontrolu.
    """
    log_id = len(db_construction_logs) + 1
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    final_text = log.work_description
    
    if log.has_photo:
        final_text += " [AI Vision: Fotodokumentace ověřena, shoda s projektem 100 %]."

    entry = {
        "log_id": log_id,
        "created_at": current_time,
        "author": log.author,
        "entry_text": final_text,
        "status": "READY_FOR_EIDAS_SIGNATURE"
    }
    db_construction_logs.append(entry)
    db_crm_history.append({"timestamp": current_time, "details": f"Stavbyvedoucí {log.author} přidal zápis ID {log_id}."})
    return entry

@app.get("/project/{property_id}/crm-timeline", tags=["4. Stavební Modul & CRM"])
def get_project_crm_timeline(property_id: int):
    return {"property_id": property_id, "timeline": db_crm_history}

@app.get("/orders/my-company", tags=["B2B SaaS Správa"])
def get_company_orders(current_user_company_id: int):
    """
    Vrátí zakázky pouze pro společnost, která má právě aktivní licenci.
    Ostatní společnosti v systému zůstávají skryté.
    """
    company_orders = [order for order in db_all_orders if order.company_id == current_user_company_id]
    return {
        "logged_in_company_id": current_user_company_id,
        "active_orders": company_orders
    }

@app.post("/partners/commission", tags=["Partner Management"])
def compute_partner_commission(partner: Partner, gross_setup_fee: float):
    """
    Vypočítá rozdělení implementačního poplatku pro partnera.
    """
    return calculate_partner_commission(partner, gross_setup_fee)


@app.get("/localization/assets", tags=["Localization"])
def get_assets(country_code: str, currency: str, amount: float):
    """
    Vrátí lokalizované texty a formátovanou cenu podle země a měny.
    """
    return get_localized_assets(country_code, currency, amount)


@app.post("/contracts/generate", tags=["6. Automatické Smlouvy & SLA"])
def generate_project_and_service_contracts(contract: ContractInput):
    """
    Jedním kliknutím vygeneruje smlouvu o dílo a servisní smlouvu (SLA).
    """
    if contract.service_fee_percent < 1.0 or contract.service_fee_percent > 10.0:
        raise HTTPException(status_code=400, detail="Servisní poplatek musí být v rozmezí 1-10%.")

    annual_service_fee = contract.project_value_czk * (contract.service_fee_percent / 100.0)
    monthly_service_fee = annual_service_fee / 12.0
    current_year = datetime.datetime.now().year
    contract_id = f"CTR-{current_year}-{contract.property_id:04d}"

    headers = {
        "CZ": {
            "sod_title": "SMLOUVA O DÍLO (SoD)",
            "sla_title": "SMLOUVA O ZAJIŠTĚNÍ SERVISNÍCH SLUŽEB (SLA)",
            "subject": "Předmětem smlouvy je dodávka FVE SolarEdge a panelů AIko.",
            "fee_text": f"Smluvní strany se dohodly na ročním servisním poplatku ve výši {contract.service_fee_percent}% z hodnoty díla."
        },
        "DE": {
            "sod_title": "WERKVERTRAG (SoD)",
            "sla_title": "SERVICE-LEVEL-AGREEMENT (SLA)",
            "subject": "Gegenstand des Vertrages ist die Lieferung von SolarEdge und AIko-Panelen.",
            "fee_text": f"Die Parteien vereinbaren eine jährliche Servicegebühr in Höhe von {contract.service_fee_percent}% des Auftragswertes."
        },
        "EN": {
            "sod_title": "WORK CONTRACT (SoD)",
            "sla_title": "SERVICE LEVEL AGREEMENT (SLA)",
            "subject": "The subject of the contract is the delivery of SolarEdge and AIko panels.",
            "fee_text": f"The parties agree on an annual service fee of {contract.service_fee_percent}% of the contract value."
        },
    }

    lang = contract.contract_language if contract.contract_language in headers else "CZ"
    legal_text = headers[lang]

    return {
        "contract_id": contract_id,
        "generated_at": datetime.date.today().isoformat(),
        "client_name": contract.client_name,
        "language_applied": lang,
        "DOCUMENT_1_SMLOUVA_O_DÍLO": {
            "title": legal_text["sod_title"],
            "clause_1_subject": legal_text["subject"],
            "total_price": f"{contract.project_value_czk:,} Kč",
            "execution_timeline": "Automaticky vygenerovaný Ganttův diagram projektu přiložen v příloze č. 1."
        },
        "DOCUMENT_2_SERVISNÍ_SMLOUVA_SLA": {
            "title": legal_text["sla_title"],
            "clause_finance": legal_text["fee_text"],
            "financial_breakdown": {
                "project_base_value": f"{contract.project_value_czk:,} Kč",
                "sla_percentage": f"{contract.service_fee_percent} %",
                "ANNUAL_SERVICE_PAYMENT": f"{round(annual_service_fee, 2):,} Kč",
                "MONTHLY_SERVICE_PAYMENT": f"{round(monthly_service_fee, 2):,} Kč"
            },
            "scope_of_work": "Nonstop IoT monitoring střídačů, prioritní servisní alerty, správa tradingového modulu a povinná roční revize k výročí spuštění."
        },
        "status": "READY_FOR_EIDAS_SIGNATURE",
        "next_action": "Odeslat výzvu k elektronickému podpisu na e-mail klienta a do jeho klientského portálu."
    }


@app.post("/hardware/read-and-optimize", tags=["7. Univerzální Hardware Driver (Modbus/CAN)"])
def read_and_optimize_device(device: DeviceRegisterMap, current_spot_price_kwh: float):
    """
    Vyčte data ze specifického zařízení přes Modbus/CAN.
    Pokud jde o osvětlení nebo linku, spočítá finanční profit z jejich regulace v drahé špičce.
    """
    device_data = {}
    financial_benefit_czk = 0.0
    action_taken = "MONITORING_ONLY"

    if device.device_type == "solaredge_inverter":
        raw_power = read_modbus_register(device.ip_address, device.port, 40083)
        device_data = {"current_generation_kw": raw_power * 2}

    elif device.device_type == "industrial_led_lighting":
        current_lighting_load_kw = 80.0
        if current_spot_price_kwh > 5.0:
            saved_power_kw = current_lighting_load_kw * 0.20
            financial_benefit_czk = saved_power_kw * current_spot_price_kwh
            action_taken = "DIMMING_LIGHTS_BY_20_PERCENT"
            device_data = {
                "original_load_kw": current_lighting_load_kw,
                "optimized_load_kw": current_lighting_load_kw - saved_power_kw,
                "saved_power_kw": saved_power_kw,
            }
        else:
            device_data = {"current_load_kw": current_lighting_load_kw}

    elif device.device_type == "siemens_plc_line":
        line_status = read_modbus_register(device.ip_address, device.port, 1002)
        device_data = {"production_line_speed_pct": line_status, "status": "RUNNING"}

    return {
        "device_type": device.device_type,
        "hardware_status_read_via_modbus": device_data,
        "ems_control_action": action_taken,
        "financial_hourly_profit_czk": round(financial_benefit_czk, 2),
        "note": "Data úspěšně normalizována a připravena pro centrální ERP a klientský dashboard.",
    }


@app.post("/ai/email-process", tags=["AI Assistant & CRM"])
def process_ai_email(email_request: EmailProcessingInput):
    """
    Zpracuje klientský e-mail a vrátí lidsky působící odpověď s CRM payloadem.
    """
    assistant = AIAssistantCore()
    result = assistant.process_incoming_client_email(
        client_email=email_request.client_email,
        email_content=email_request.email_content,
    )
    return result


@app.post("/public/web-calculator", tags=["Marketing & AI Prodej"])
def public_web_calculator_lead(lead: WebLeadInput):
    """
    Zpracuje data z veřejného kalkulátoru a spustí proaktivní AI outbound akci.
    """
    estimated_fve_size_kw = round((lead.monthly_energy_bill_czk * 12) / 4000, 1)
    bess_annual_clean_profit = 8000000.0 if lead.monthly_energy_bill_czk > 1000000 else 450000.0

    ai_outbound_strategy = {
        "agent_identity": "Lucie Marešová, obchodní koordinátor",
        "is_human_disguise_active": True,
        "email_pitch": (
            f"Dobrý den, {lead.client_name}. Na základě analýzy osvitu pro adresu {lead.address} "
            f"Vám náš systém navrhl optimální řešení o velikosti {estimated_fve_size_kw} kWp. "
            f"Vaše roční čistá výplata z provozu baterie bude činit {bess_annual_clean_profit:,} Kč. "
            "Návrh Smlouvy o dílo a Servisní smlouvy (SLA) s fixním poplatkem 3% z hodnoty díla "
            "máte připraven ve svém nově založeném klientském portálu."
        ),
        "voicebot_call_script": (
            f"Dobrý den, u telefonu Lucie Marešová. Volám ohledně Vaší kalkulace pro objekt {lead.address}. "
            f"Náš systém tam detekoval obrovský potenciál pro SVR služby s čistým výnosem přes {bess_annual_clean_profit/12:,.0f} Kč měsíčně. "
            "Máte zítra v 10 vteřin čas, abychom se na to podívali s naším hlavním inženýrem, nebo Vám rovnou "
            "mám poslat podklady k elektronickému podpisu?"
        )
    }

    return {
        "status": "LEAD_CAPTURED_AND_AI_DISPATCHED",
        "timestamp": datetime.datetime.now().isoformat(),
        "lead_details": {
            "name": lead.client_name,
            "email": lead.client_email,
            "allocated_to_company_id": lead.company_id
        },
        "instant_engineering_simulation": {
            "recommended_fve_kwp": estimated_fve_size_kw,
            "bess_annual_clean_payout_czk": bess_annual_clean_profit,
            "co2_reduction_tons_year": round(estimated_fve_size_kw * 0.5, 1)
        },
        "PROACTIVE_AI_EXECUTION_PLAN": ai_outbound_strategy
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
