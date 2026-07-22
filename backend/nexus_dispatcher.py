import asyncio
import datetime
import random
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import requests


OTE_URL = "https://ote-cr.cz"
MAX_ALLOWED_LATENCY_MS = 500.0
TELEPHONE_DISPECINK = "+420 777 999 111"
INTEGRATION_WEBHOOK_URL = "https://discord.com"


MONITORED_ASSETS = [
    {"id": 1, "city": "Praha", "inverter": "solaredge", "bess_mwh": 3.76, "technician": "Ing. Jan Roman", "tech_phone": "+420 601 111 222"},
    {"id": 2, "city": "Brno", "inverter": "huawei", "bess_mwh": 7.52, "technician": "Marek Svoboda", "tech_phone": "+420 602 222 333"},
    {"id": 3, "city": "Ostrava", "inverter": "solaredge", "bess_mwh": 3.76, "technician": "Petr Ostravský", "tech_phone": "+420 603 333 444"},
    {"id": 4, "city": "Plzeň", "inverter": "sunspec_universal", "bess_mwh": 3.76, "technician": "Tomáš Plzeňský", "tech_phone": "+420 604 444 555"},
    {"id": 5, "city": "Mladá Boleslav", "inverter": "huawei", "bess_mwh": 3.76, "technician": "Jiří Škodovka", "tech_phone": "+420 605 555 666"},
    {"id": 6, "city": "Hradec Králové", "inverter": "solaredge", "bess_mwh": 3.76, "technician": "Lukáš Hradecký", "tech_phone": "+420 606 666 777"},
    {"id": 7, "city": "Jihlava", "inverter": "sunspec_universal", "bess_mwh": 3.76, "technician": "Zdeněk Vysočina", "tech_phone": "+420 607 777 888"},
    {"id": 8, "city": "České Budějovice", "inverter": "solaredge", "bess_mwh": 3.76, "technician": "Martin Budvar", "tech_phone": "+420 608 888 999"},
]


db_service_tickets: Dict[str, dict] = {}
router = APIRouter(prefix="/nexus", tags=["NEXUS Dispatcher"])


class TicketRequest(BaseModel):
    branch_id: int
    error_title: str
    error_desc: str
    severity: str


class HardwareInspector:
    @staticmethod
    def inspect_bess_battery(branch: dict, rng: Optional[random.Random] = None) -> Optional[dict]:
        generator = rng or random
        if generator.random() < 0.01:
            return {
                "title": "KRITICKÉ PŘEHŘÁTÍ ČLÁNKŮ BATERIE (BESS)",
                "desc": f"CAN bus řadič u kontejneru {branch['bess_mwh']} MWh detekoval teplotu 62°C na článku č. 42. AI Security Shield okamžitě dálkově odpojil úložiště od sítě v rámci požární prevence.",
                "severity": "CRITICAL",
            }
        return None

    @staticmethod
    def inspect_inverter(branch: dict, rng: Optional[random.Random] = None) -> Optional[dict]:
        generator = rng or random
        if generator.random() < 0.01:
            return {
                "title": "VÝPADEK KOMUNIKACE MĚNIČE (OFFLINE)",
                "desc": f"Střídač {branch['inverter'].upper()} přestal odpovídat na Modbus TCP dotazy. Zařízení vykazuje nulový výkon při plném slunečním osvitu.",
                "severity": "WARNING",
            }
        return None


class AutoTicketingEngine:
    @staticmethod
    def create_and_assign_ticket(branch: dict, error_title: str, error_desc: str, severity: str):
        ticket_id = f"TCK-2026-{random.randint(10000, 99999)}"
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        eta_hours = 2 if severity == "CRITICAL" else 24
        scheduled_arrival = (datetime.datetime.now() + datetime.timedelta(hours=eta_hours)).strftime("%Y-%m-%d %H:%M:%S")

        new_ticket = {
            "ticket_id": ticket_id,
            "created_at": current_time,
            "facility_location": branch["city"],
            "error_type": error_title,
            "detailed_description": error_desc,
            "priority_level": severity,
            "assigned_field_technician": branch["technician"],
            "technician_contact": branch["tech_phone"],
            "scheduled_arrival_deadline": scheduled_arrival,
            "ticket_status": "DISPATCHED_TO_TECHNICIAN_MOBILE_APP",
        }

        db_service_tickets[ticket_id] = new_ticket
        print(f"🎫 [ERP TIKET - {ticket_id}] Automaticky vytvořen úkol v systému!")
        print(f"   Lokalita: Hala {branch['city']} | Přidělený technik: {branch['technician']} (Deadline příjezdu: {scheduled_arrival})")
        return new_ticket


async def dispatch_webhook_alert(alert_title: str, alert_description: str, branch_city: str, tech_name: str, severity: str = "CRITICAL"):
    color_map = {"CRITICAL": 15158332, "WARNING": 15105570, "INFO": 3447003}
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    discord_payload = {
        "username": "NEXUS AI Dispatcher Bot",
        "avatar_url": "https://unsplash.com",
        "embeds": [{
            "title": f"🚨 {alert_title}",
            "description": f"**Popis:** {alert_description}\n\n**Zásah:** Systém automaticky vygeneroval servisní tiket a vyslal technika na místo.",
            "color": color_map.get(severity, 3447003),
            "fields": [
                {"name": "Lokalita", "value": f"Hala {branch_city}", "inline": True},
                {"name": "Závažnost", "value": f"**{severity}**", "inline": True},
                {"name": "Vyjíždějící technik", "value": f"👷 {tech_name}", "inline": False},
            ],
            "footer": {"text": f"NEXUS Field Service Core | Incident log: {current_time}"},
        }]
    }

    try:
        await asyncio.to_thread(requests.post, INTEGRATION_WEBHOOK_URL, json=discord_payload, timeout=2.0)
    except Exception as exc:
        print(f"[WEBHOOK ERROR] Nelze odeslat zprávu do chatu: {exc}")


async def send_emergency_sms_to_dispecer(message_text: str):
    print(f"\n📱 [🔴 KRIZOVÁ SMS] Pro číslo: {TELEPHONE_DISPECINK}")
    print(f"   TEXT: {message_text}\n")


async def check_ote_connection(use_live_check: bool = False) -> Optional[dict]:
    if not use_live_check:
        return None

    start_time = asyncio.get_event_loop().time()
    try:
        response = await asyncio.to_thread(requests.get, OTE_URL, timeout=3.0)
        latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000.0
        if response.status_code != 200 or latency_ms > MAX_ALLOWED_LATENCY_MS:
            return {
                "title": "PORUCHA SYSTÉMU: Zpomalení burzy OTE ČR.",
                "severity": "CRITICAL",
            }
    except Exception:
        return {
            "title": "PORUCHA SYSTÉMU: Výpadek spojení s trhem OTE ČR.",
            "severity": "CRITICAL",
        }
    return None


def run_monitor_cycle(seed: Optional[int] = None) -> dict:
    rng = random.Random(seed) if seed is not None else random
    incidents: List[dict] = []

    for branch in MONITORED_ASSETS:
        inverter_issue = HardwareInspector.inspect_inverter(branch, rng=rng)
        if inverter_issue:
            incidents.append({"branch": branch["city"], **inverter_issue})
            AutoTicketingEngine.create_and_assign_ticket(branch, inverter_issue["title"], inverter_issue["desc"], inverter_issue["severity"])

        battery_issue = HardwareInspector.inspect_bess_battery(branch, rng=rng)
        if battery_issue:
            incidents.append({"branch": branch["city"], **battery_issue})
            AutoTicketingEngine.create_and_assign_ticket(branch, battery_issue["title"], battery_issue["desc"], battery_issue["severity"])

    return {
        "checked_assets": len(MONITORED_ASSETS),
        "incident_count": len(incidents),
        "incidents": incidents,
        "open_ticket_count": len(db_service_tickets),
    }


@router.get("/status")
def nexus_status():
    return {
        "dispatcher": "ONLINE",
        "monitored_assets": len(MONITORED_ASSETS),
        "open_tickets": len(db_service_tickets),
        "live_ote_check_url": OTE_URL,
        "webhook_target": INTEGRATION_WEBHOOK_URL,
    }


@router.get("/tickets")
def list_tickets():
    return {"tickets": list(db_service_tickets.values())}


@router.post("/scan-cycle")
async def scan_cycle(use_live_ote_check: bool = Query(default=False), seed: Optional[int] = Query(default=None)):
    ote_issue = await check_ote_connection(use_live_check=use_live_ote_check)
    report = run_monitor_cycle(seed=seed)

    if ote_issue:
        report["ote_issue"] = ote_issue
        report["incidents"].append({"branch": "OTE", **ote_issue})
        await send_emergency_sms_to_dispecer(ote_issue["title"])

    return report


@router.post("/dispatch-ticket")
def dispatch_ticket(request: TicketRequest):
    branch = next((asset for asset in MONITORED_ASSETS if asset["id"] == request.branch_id), None)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    ticket = AutoTicketingEngine.create_and_assign_ticket(branch, request.error_title, request.error_desc, request.severity)
    return {"ticket": ticket}
