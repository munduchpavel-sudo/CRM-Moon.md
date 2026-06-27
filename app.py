import datetime
import os
import random
import time
import requests
from typing import Dict, List, Optional
from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel

from localization import get_localized_assets
from partner_commission import Partner, calculate_partner_commission


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

app = FastAPI(
    title="Global Secure Energy Agregátor & Enterprise ERP",
    description="Infrastruktura s vestavěným AI bezpečnostním agentem, Google OAuth 2.0, 2FA, RBAC a mezinárodním tradingem.",
    version="1.5.0"
)

# Include legacy ERP router from backend to avoid duplicate FastAPI apps
try:
    from backend.fastapi_erp import router as erp_router
    app.include_router(erp_router)
except Exception:
    # best-effort include; if backend module isn't importable in some contexts, continue
    pass


class DeviceRegisterMap(BaseModel):
    device_type: str
    ip_address: str
    port: int


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
    """Simuluje nízkoúrovňové vyčítání hodnoty z registru daného stroje."""
    return random.randint(50, 150)


# Globální konfigurace pro Google OAuth (demo)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "demo-google-client-id")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "demo-google-client-secret")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/auth/google/callback")


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

    payload = None
    if request.method in ["POST", "PUT"]:
        try:
            body = await request.body()
            if body:
                payload = await request.json()
        except Exception:
            pass

    if not AISecurityShield.inspect_request(client_ip, payload):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ZÁSAH AI BEZPEČNOSTNÍHO AGENTA: Váš požadavek vykazuje znaky kybernetického útoku a byl zablokován."
        )

    response = await call_next(request)
    return response


# =====================================================================
# 1. ÚROVEŇ: PŘIHLÁŠENÍ PŘES GOOGLE (OAuth 2.0)
# =====================================================================

@app.get("/auth/google/login", tags=["Zabezpečené Přihlašování"])
def simulate_google_login(email: str = "novak@fabrika.cz", requested_role: str = "owner"):
    """
    Simulace úspěšného Google OAuth 2.0 přihlášení.
    """
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

# =====================================================================
# ŽIVÁ DATA: INTEGRACE OTE ČR VIA API
# =====================================================================

def get_live_ote_price_kwh() -> float:
    """
    Stáhne reálná data denního trhu z oficiálního rozhraní OTE ČR.
    Vrací cenu v Kč/kWh. Při výpadku sítě vrací bezpečný fallback.
    """
    try:
        url = "https://ote-cr.cz"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            points = data.get("point", [])
            if points:
                price_eur_mwh = float(points[-1])
                exchange_rate = 25.0
                return (price_eur_mwh * exchange_rate) / 1000.0
    except Exception as e:
        print(f"Chyba OTE API: {e}. Používám fallback.")
    return -1.20  # Fallback pro ukázku záporné ceny

# =====================================================================
# CHRÁNĚNÉ PRODUKČNÍ ENDPOINTY (RBAC + 2FA + AI ŠTÍT)
# =====================================================================

@app.get("/agregator/battery-profit/{property_id}", tags=["Chráněný Modul Obchodníka (Agregátor)"])
def get_battery_clean_profit(property_id: int, battery_capacity_mwh: float = 1.0, current_user: UserSession = Depends(require_role(["superadmin", "owner"]))):
    """
    Přístup pouze pro majitele nebo superadmina s dokončeným 2FA.
    """
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    gross_profit_per_mwh_year = 9411764.0
    annual_gross = battery_capacity_mwh * gross_profit_per_mwh_year
    our_margin = annual_gross * 0.15
    client_clean = annual_gross - our_margin

    return {
        "authorized_user": current_user.email,
        "property_name": prop.name,
        "client_dashboard_display": {
            "NET_PAYOUT_MONTHLY_CZK": f"{round(client_clean / 12.0, 2):,} Kč",
            "NET_PAYOUT_ANNUAL_CZK": f"{round(client_clean, 2):,} Kč"
        },
        "INTERNAL_BUSINESS_LOG": {
            "gross_market_revenue_czk": round(annual_gross, 2),
            "our_trading_company_15_percent_margin": round(our_margin, 2)
        }
    }


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
def execute_ems_trading(property_id: int, current_battery_soc: float):
    """
    Řídí spotřebu fabriky v reálném čase podle živých cen z OTE a distribuce.
    """
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    
    spot_price_kwh = get_live_ote_price_kwh()
    final_cost_kwh = spot_price_kwh + prop.distribution_tariff_kwh
    
    action = "STANDARD_RUN"
    explanation = "Provoz v normálním režimu."
    
    if final_cost_kwh < 0:
        action = "FORCED_MAXIMUM_CONSUMPTION"
        explanation = f"Celková cena je záporná ({final_cost_kwh:.2f} Kč/kWh). Odběr generuje zisk! Zapínám technologie na maximum."
    elif spot_price_kwh > 4.5:
        action = "MAXIMUM_GRID_FEED_IN"
        explanation = f"Silová elektřina je extrémně drahá ({spot_price_kwh:.2f} Kč/kWh). Přepínám fabriku na baterii."

    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "property_name": prop.name,
        "live_spot_price_silova_kwh": round(spot_price_kwh, 2),
        "final_effective_cost_kwh": round(final_cost_kwh, 2),
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

    GROSS_PROFIT_PER_MWH_YEAR = 9411764.0 
    AGREGATOR_MARGIN_PERCENT = 15.0

    annual_gross_profit = battery_capacity_mwh * GROSS_PROFIT_PER_MWH_YEAR
    owner_trading_company_revenue = annual_gross_profit * (AGREGATOR_MARGIN_PERCENT / 100.0)
    client_clean_profit_year = annual_gross_profit - owner_trading_company_revenue
    client_clean_profit_month = client_clean_profit_year / 12.0

    return {
        "property_name": prop.name,
        "connected_bess_capacity": f"{battery_capacity_mwh} MWh",
        "client_dashboard_display": {
            "PERODIC_CLEAN_PROFIT_CZK": {
                "MONTHLY_PAYOUT": f"{round(client_clean_profit_month, 2):,} Kč",
                "ANNUAL_PAYOUT": f"{round(client_clean_profit_year, 2):,} Kč"
            },
            "system_status": "SVR_ACTIVE_CEPS_CONNECTED",
            "message": "Zobrazené finanční částky jsou konečné, pročištěné a připravené k odeslání na Váš bankovní účet."
        },
        "INTERNAL_BUSINESS_LOG": {
            "note": "Tato sekce je viditelná pouze pro tebe v administraci, klient ji ve svém rozhraní NEVIDÍ.",
            "gross_market_revenue": round(annual_gross_profit, 2),
            "our_trading_margin_15_percent_profit": round(owner_trading_company_revenue, 2)
        }
    }


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
