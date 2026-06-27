import datetime
import json
from typing import Dict, Any


def generate_human_like_prompt(client_message: str) -> str:
    """
    Vytváří transparentní systémový pokyn pro CRM asistenta.
    Zajišťuje profesionální a přirozený tón bez zamlčování toho,
    že jde o AI pomocníka.
    """
    system_instruction = (
        "Jsi profesionální asistentka CRM. Piš stručně, přirozeně a profesionálně. "
        "Dávej přednost jasným a užitečným odpovědím. "
        "Nevypisuj falešné informace o své identitě. "
        f"Zpráva od klienta: {client_message}"
    )
    return system_instruction


class AIAssistantEngine:
    def __init__(self, target_erp_api_url: str):
        self.erp_url = target_erp_api_url
        # Zde by v produkci byly API klíče pro OpenAI, ElevenLabs nebo Twilio
        self.llm_model = "gpt-4o"

    def process_incoming_email(self, client_email: str, email_body: str) -> Dict[str, Any]:
        """
        AI analyzuje příchozí e-mail od klienta, pochopí kontext, 
        automaticky navrhne odpověď a zapíše interakci do CRM.
        """
        print(f"\n[AI] Přijat nový e-mail od: {client_email}")
        
        intent = "UNKNOWN"
        if "stavební povolení" in email_body.lower() or "stavba" in email_body.lower():
            intent = "CONSTRUCTION_STATUS_INQUIRY"
        elif "revize" in email_body.lower() or "servis" in email_body.lower():
            intent = "SERVICE_REQUEST"

        ai_reply = ""
        if intent == "CONSTRUCTION_STATUS_INQUIRY":
            ai_reply = "Dobrý den, Váš požadavek na stav stavebního povolení byl předán projektovému manažerovi. Aktuální stav můžete sledovat ve svém klientském portálu v sekci Ganttův diagram."
        elif intent == "SERVICE_REQUEST":
            ai_reply = "Dobrý den, evidujeme Váš požadavek na roční revizi elektrárny SolarEdge. Náš systém Vám během dnešního dne zašle SMS s návrhem termínů, které má technik volné."
        else:
            ai_reply = "Dobrý den, děkujeme za zprávu. Náš tým se jí bude ihned věnovat."

        crm_payload = {
            "timestamp": datetime.datetime.now().isoformat(),
            "channel": "email",
            "direction": "inbound",
            "summary": f"Klient se dotazuje na: {intent}. AI automaticky odpověděla.",
            "raw_transcript": email_body
        }
        
        return {
            "detected_intent": intent,
            "crm_logged_data": crm_payload,
            "automated_reply_draft": ai_reply
        }

    def process_voice_call_transcript(self, phone_number: str, raw_audio_transcript: str) -> Dict[str, Any]:
        """
        Tato funkce se spustí ihned poté, co klient zavěsí hovor na VoIP ústředně.
        Vezme přepis řeči (Speech-to-Text), udělá z něj stručné shrnutí a vyvolá akci v ERP.
        """
        print(f"\n[AI Voicebot] Zpracovávám přepis hovoru z čísla: {phone_number}")
        
        is_emergency = "nefunguje" in raw_audio_transcript.lower() or "střídač hlásí chybu" in raw_audio_transcript.lower()
        
        summary = ""
        action_required = "NONE"
        
        if is_emergency:
            summary = "URGENTNÍ: Klient volá, že mu nefunguje střídač SolarEdge a systém hlásí chybu."
            action_required = "CREATE_SERVICE_TICKET_HIGH_PRIORITY"
        else:
            summary = "Běžný dotaz klienta na termín realizace a montáže AIko panelů."
            action_required = "NOTIFY_PROJECT_MANAGER"

        crm_payload = {
            "timestamp": datetime.datetime.now().isoformat(),
            "channel": "phone_ai",
            "direction": "inbound",
            "summary": summary,
            "raw_transcript": raw_audio_transcript
        }

        return {
            "call_summary": summary,
            "triggered_erp_action": action_required,
            "crm_logged_data": crm_payload
        }

# =====================================================================
# SIMULACE BĚHU AI ASISTENTKY V PRAXI
# =====================================================================
if __name__ == "__main__":
    ai = AIAssistantEngine(target_erp_api_url="http://127.0.0.1:8000")

    email_result = ai.process_incoming_email(
        client_email="novak@fabrika.cz",
        email_body="Dobrý den, chci se zeptat, kdy u nás proběhne ta povinná roční revize na ty čínské baterie? Blíží se výročí elektrárny."
    )
    print(f"-> Detekovaný záměr: {email_result['detected_intent']}")
    print(f"-> Návrh AI odpovědi: {email_result['automated_reply_draft']}")

    voice_result = ai.process_voice_call_transcript(
        phone_number="+420 777 123 456",
        raw_audio_transcript="Dobrý den, já tady stojím u střídače SolarEdge a ono to vůbec nefunguje. Na displeji to svítí červeně a hlásí to nějakou chybu komunikace, prosím pošlete někoho."
    )
    print(f"-> Shrnutí hovoru pro CRM: {voice_result['call_summary']}")
    print(f"-> Vyvolaná akce v systému: {voice_result['triggered_erp_action']}")
