import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

URL = "https://bookings.cloud.microsoft/book/SELAGEMDECELULARESESIMILARESPARAACESSOSREASRESTRITASCpia@gru.com.br/?ismsaljsauthenabled=true"
STATE_FILE = Path("state.json")
TIME_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")

def notify(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    import urllib.request
    import urllib.parse
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        result = json.loads(response.read().decode())
    if not result.get("ok"):
        raise RuntimeError("Telegram recusou o envio da mensagem")

def main():
    old = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"seen": []}
    seen = set(old.get("seen", []))
    found = {}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="pt-BR", timezone_id="America/Sao_Paulo")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(5000)

        # Diagnóstico temporário para validar a estrutura real do calendário.
        print("DIAG_URL:", page.url)
        print("DIAG_TITLE:", page.title())
        try:
            print("DIAG_BODY:", page.locator("body").inner_text(timeout=5000)[:5000])
        except Exception as exc:
            print("DIAG_BODY_ERROR:", type(exc).__name__)
        try:
            controls = page.locator("button, [role='button'], [role='gridcell']")
            print("DIAG_CONTROLS_COUNT:", min(controls.count(), 250))
            for k in range(min(controls.count(), 80)):
                el = controls.nth(k)
                try:
                    if el.is_visible():
                        print("DIAG_CONTROL:", k, "tag=", el.evaluate("(e) => e.tagName"), "text=", (el.inner_text(timeout=300) or "").strip()[:80], "aria=", el.get_attribute("aria-label"), "disabled=", el.get_attribute("disabled"), "aria-disabled=", el.get_attribute("aria-disabled"), "class=", (el.get_attribute("class") or "")[:120])
                except Exception:
                    pass
        except Exception as exc:
            print("DIAG_CONTROLS_ERROR:", type(exc).__name__)

        # A página pública pode mostrar mais de um mês. Só clicamos em botões
        # de dia habilitados; controles de navegação e dias desabilitados ficam de fora.
        for month_index in range(6):
            candidates = page.locator("button:not([disabled]), [role='button']:not([aria-disabled='true'])")
            count = min(candidates.count(), 300)
            day_buttons = []
            for i in range(count):
                el = candidates.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    label = (el.get_attribute("aria-label") or el.get_attribute("title") or "").strip()
                    text = (el.inner_text(timeout=500) or "").strip()
                    if re.fullmatch(r"\d{1,2}", text) and 1 <= int(text) <= 31:
                        day_buttons.append((i, label, text))
                except Exception:
                    continue

            for original_index, label, day in day_buttons:
                try:
                    # Re-query because the DOM may have changed after each selection.
                    current = page.locator("button:not([disabled]), [role='button']:not([aria-disabled='true'])")
                    if original_index >= current.count():
                        continue
                    el = current.nth(original_index)
                    if not el.is_visible():
                        continue
                    el.click(timeout=1500)
                    page.wait_for_timeout(900)
                    body = page.locator("body").inner_text(timeout=3000)
                    # Collect explicit time-slot controls, not incidental text in the page.
                    slot_labels = []
                    slots = page.locator("button:not([disabled]), [role='button']:not([aria-disabled='true'])")
                    for j in range(min(slots.count(), 250)):
                        item = slots.nth(j)
                        try:
                            if not item.is_visible():
                                continue
                            value = (item.inner_text(timeout=300) or "").strip()
                            if TIME_RE.fullmatch(value):
                                slot_labels.append(value)
                        except Exception:
                            continue
                    if slot_labels:
                        date_label = label or f"Dia {day}"
                        key = f"{date_label}|{','.join(sorted(set(slot_labels)))}"
                        found[key] = {"date": date_label, "times": sorted(set(slot_labels))}
                except Exception:
                    continue

            if month_index < 5:
                # Try common accessible names for the next-month control.
                next_button = None
                for selector in [
                    "button[aria-label*='Próximo']",
                    "button[aria-label*='próximo']",
                    "button[aria-label*='Next']",
                    "button[title*='Próximo']",
                    "button[title*='Next']",
                ]:
                    loc = page.locator(selector).first
                    try:
                        if loc.is_visible() and loc.is_enabled():
                            next_button = loc
                            break
                    except Exception:
                        pass
                if next_button is None:
                    break
                try:
                    next_button.click(timeout=1500)
                    page.wait_for_timeout(700)
                except Exception:
                    break

        browser.close()

    new_items = [item for key, item in found.items() if key not in seen]
    if new_items:
        lines = ["🚨 NOVA DISPONIBILIDADE NO BOOKING", "Selagem de celulares e similares para acesso às áreas restritas", ""]
        for item in new_items:
            lines.append(f"{item['date']}: {', '.join(item['times'])}")
        lines.extend(["", "Abra o agendamento para reservar:", URL])
        notify("\n".join(lines))

    old["seen"] = sorted(seen.union(found.keys()))
    old["last_check_utc"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(old, ensure_ascii=False, indent=2) + "\n")

    print(f"Disponibilidades encontradas: {len(found)}; novas: {len(new_items)}")

if __name__ == "__main__":
    main()
