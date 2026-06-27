LOCALIZATION_DICTIONARY = {
    "CZ": {
        "welcome": "Dobrý den, vítáme vás v systému.",
        "invoice_title": "Fakturační podklad za energetické služby",
    },
    "DE": {
        "welcome": "Guten Tag, willkommen im System.",
        "invoice_title": "Abrechnungsbeleg für Energiedienstleistungen",
    },
    "EN": {
        "welcome": "Hello, welcome to the system.",
        "invoice_title": "Billing document for energy services",
    },
}


def get_localized_assets(country_code: str, currency: str, amount: float) -> dict:
    """
    Dynamicky formátuje výstupy pro klienta podle jeho země a měny.
    """
    lang = country_code if country_code in LOCALIZATION_DICTIONARY else "EN"
    texts = LOCALIZATION_DICTIONARY[lang]

    if currency == "EUR":
        formatted_price = f"€{amount:,.2f}"
    elif currency == "USD":
        formatted_price = f"${amount:,.2f}"
    else:
        formatted_price = f"{amount:,.2f} Kč"

    return {
        "welcome_message": texts["welcome"],
        "document_title": texts["invoice_title"],
        "display_price": formatted_price,
    }


if __name__ == "__main__":
    print(get_localized_assets(country_code="DE", currency="EUR", amount=250000.0))
    print(get_localized_assets(country_code="CZ", currency="CZK", amount=250000.0))
