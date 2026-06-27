import datetime
from pydantic import BaseModel


class Partner(BaseModel):
    id: int
    company_name: str
    installations_count: int
    joined_date: datetime.date


def calculate_partner_commission(partner: Partner, gross_setup_fee: float) -> dict:
    """
    Dynamicky počítá rozdělení implementačního poplatku.
    - Noví partneři nebo do 5 instalací: 50:50.
    - Zavedení partneři nebo od 6. instalace: 70:30.
    """
    commission_shift_threshold = 5
    future_strategy_date = datetime.date(2027, 1, 1)
    current_date = datetime.date.today()

    if partner.installations_count >= commission_shift_threshold or current_date >= future_strategy_date:
        partner_percentage = 30.0
        our_percentage = 70.0
    else:
        partner_percentage = 50.0
        our_percentage = 50.0

    partner_share = gross_setup_fee * (partner_percentage / 100.0)
    our_share = gross_setup_fee * (our_percentage / 100.0)

    return {
        "partner_name": partner.company_name,
        "total_installations_done": partner.installations_count,
        "applied_model_ratio": f"{int(our_percentage)}:{int(partner_percentage)}",
        "financial_breakdown": {
            "gross_setup_fee_paid_by_client": f"{gross_setup_fee:,} Kč",
            "partner_payout_commission": f"{partner_share:,} Kč",
            "OUR_COMPANY_NET_REVENUE": f"{our_share:,} Kč",
        },
    }


if __name__ == "__main__":
    new_partner = Partner(id=1, company_name="SolarMontáže s.r.o.", installations_count=2, joined_date=datetime.date(2026, 5, 1))
    result_1 = calculate_partner_commission(new_partner, gross_setup_fee=500000.0)
    print(f"Partner: {result_1['partner_name']} ({result_1['applied_model_ratio']})")
    print(f"-> Výplata partnerovi: {result_1['financial_breakdown']['partner_payout_commission']}")
    print(f"-> Zůstává nám: {result_1['financial_breakdown']['OUR_COMPANY_NET_REVENUE']}\n")

    loyal_partner = Partner(id=1, company_name="SolarMontáže s.r.o.", installations_count=6, joined_date=datetime.date(2026, 5, 1))
    result_2 = calculate_partner_commission(loyal_partner, gross_setup_fee=500000.0)
    print(f"Partner: {result_2['partner_name']} ({result_2['applied_model_ratio']})")
    print(f"-> Výplata partnerovi: {result_2['financial_breakdown']['partner_payout_commission']}")
    print(f"-> Zůstává nám: {result_2['financial_breakdown']['OUR_COMPANY_NET_REVENUE']}")
