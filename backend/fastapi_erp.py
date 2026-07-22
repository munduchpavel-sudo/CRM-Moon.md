import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/erp", tags=["ERP Legacy"])

# =====================================================================
# DATOVÉ MODELY (DB SCHÉMA V IN-MEMORY PAMĚTI)
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
    space_name: str  # Např. "Dílna A", "Sklad B"
    fixed_price_kwh: float  # Smluvní cena pro nájemce (např. 7.00 Kč)

class TelemetryInput(BaseModel):
    property_id: int
    fve_generation_kw: float
    total_consumption_kw: float
    battery_soc: float
    spot_price_mwh: float  # Aktuální cena silové elektřiny na OTE v Kč/MWh

class ConstructionLogInput(BaseModel):
    property_id: int
    author: str
    work_description: str
    has_photo: bool

# Fake DB (Lokální úložiště dat pro běh aplikace)
db_properties = [
    Property(id=1, name="Skladová Hala Sever", address="Průmyslová 12, Praha", ean="CZ000123456", distribution_tariff_kwh=1.50)
]

db_tenants = [
    Tenant(id=1, property_id=1, space_name="Dílna A - Kovošrot", fixed_price_kwh=7.00),
    Tenant(id=2, property_id=1, space_name="Sklad B - Chlazení", fixed_price_kwh=7.00)
]

db_crm_history = []
db_construction_logs = []

# =====================================================================
# MODUL 1: EMS & ALGORITMICKÝ TRADING (ZÁPORNÉ CENY)
# =====================================================================

@router.post("/ems/analyze-and-control", tags=["Energetika & Trading"])
def ems_analyze_and_control(telemetry: TelemetryInput):
    """
    Vyhodnocuje spotové ceny a dává autonomní příkazy technologiím (FVE, Baterie).
    Zohledňuje silovou elektřinu i distribuční poplatky.
    """
    prop = next((p for p in db_properties if p.id == telemetry.property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    spot_price_kwh = telemetry.spot_price_mwh / 1000.0
    final_cost_kwh = spot_price_kwh + prop.distribution_tariff_kwh

    action = "STANDARD_RUN"
    reason = "Ceny jsou v běžném rozmezí. Systém běží v hybridním automatickém režimu."

    if final_cost_kwh < 0:
        action = "FORCED_MAXIMUM_CONSUMPTION"
        reason = (
            f"Celková cena je ZÁPORNÁ ({final_cost_kwh:.2f} Kč/kWh s distribucí). "
            "Odběr generuje zisk! Zapínám nabíjení baterií ze sítě, wallboxy na max a dálkově omezuji přetoky z FVE, "
            "abychom neplatili pokutu."
        )
    elif spot_price_kwh > 5.0:
        action = "MAXIMUM_GRID_FEED_IN"
        reason = (
            f"Cena na spotu je extrémně vysoká ({spot_price_kwh:.2f} Kč/kWh). "
            "Vypínám zbytné spotřebiče, přepínám objekt na baterii a veškerou výrobu + kapacitu baterie prodávám do sítě."
        )
    elif spot_price_kwh < 1.0 and telemetry.battery_soc < 80:
        action = "CHARGE_BATTERY_FROM_GRID"
        reason = (
            f"Silová elektřina je velmi levná ({spot_price_kwh:.2f} Kč/kWh). "
            "Nabíjím baterii ze sítě pro večerní špičku (Arbitráž)."
        )

    return {
        "property_name": prop.name,
        "spot_price_kwh": round(spot_price_kwh, 2),
        "distribution_tariff_kwh": prop.distribution_tariff_kwh,
        "final_client_cost_kwh": round(final_cost_kwh, 2),
        "recommended_action": action,
        "explanation": reason
    }

# =====================================================================
# MODUL 2: ROZÚČTOVÁNÍ ENERGIÍ PRO NÁJEMCE (MIKROGRID)
# =====================================================================

@router.get("/ems/billing/{property_id}", tags=["Energetika & Trading"])
def calculate_tenant_billing(property_id: int, total_generated_fve_kwh: float):
    """
    Vypočítá finanční bilanci pro majitele objektu při prodeji vnitřním nájemcům.
    Ukazuje výhodu obcházení distribuční soustavy (Mikrogrid).
    """
    prop = next((p for p in db_properties if p.id == property_id), None)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    tenants = [t for t in db_tenants if t.property_id == property_id]
    if not tenants:
        return {"message": "Žádní nájemci v objektu."}

    fve_per_tenant = total_generated_fve_kwh / len(tenants)
    total_owner_profit = 0.0
    tenant_reports = []

    for t in tenants:
        profit_from_tenant = fve_per_tenant * t.fixed_price_kwh
        total_owner_profit += profit_from_tenant
        tenant_reports.append({
            "space": t.space_name,
            "allocated_fve_kwh": round(fve_per_tenant, 2),
            "price_per_kwh": t.fixed_price_kwh,
            "tenant_bill_czk": round(profit_from_tenant, 2)
        })

    return {
        "property_name": prop.name,
        "total_fve_generated_kwh": total_generated_fve_kwh,
        "total_owner_profit_czk": round(total_owner_profit, 2),
        "saved_distribution_fees_czk": round(total_generated_fve_kwh * prop.distribution_tariff_kwh, 2),
        "billing_breakdown": tenant_reports
    }

# =====================================================================
# MODUL 3: STAVEBNÍ DENÍK & AI AUTOMATIZACE (MOCK)
# =====================================================================

@router.post("/construction/log", tags=["Stavební modul & CRM"])
def create_construction_log(log: ConstructionLogInput):
    """
    Vytvoří záznam do stavebního deníku. Pokud je přítomna fotografie,
    simuluje Vision AI a automaticky doplňuje zápis o technickou kontrolu.
    """
    log_id = len(db_construction_logs) + 1
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    description = log.work_description
    ai_note = None

    if log.has_photo:
        ai_note = (
            "[AI Vision Note]: Detekována shoda s projektovou dokumentací na základě analýzy fotografie. "
            "Záznam automaticky ověřen a GPS souřadnice uloženy."
        )
        description += " (Ověřeno AI Vision: Fotodokumentace schválena)."

    log_entry = {
        "id": log_id,
        "property_id": log.property_id,
        "date": timestamp,
        "author": log.author,
        "description": description,
        "ai_verification": ai_note,
        "status": "Ready_for_Electronic_Signature_eIDAS"
    }

    db_construction_logs.append(log_entry)
    db_crm_history.append({
        "property_id": log.property_id,
        "timestamp": timestamp,
        "type": "CONSTRUCTION_LOG",
        "summary": f"Uživatel {log.author} přidal zápis do stavebního deníku s ID {log_id}."
    })

    return log_entry

@router.get("/project/{property_id}/timeline", tags=["Stavební modul & CRM"])
def get_project_timeline(property_id: int):
    """
    Zobrazí kompletní klientskou historii (Timeline) – hovory, maily, stavební zápisy.
    """
    filtered_events = [event for event in db_crm_history if event.get("property_id") == property_id]
    return {
        "property_id": property_id,
        "timeline_events": filtered_events
    }

# This module exposes an APIRouter to be mounted into the main application.
# Run the main FastAPI app from the project's entrypoint (e.g. app.py).
