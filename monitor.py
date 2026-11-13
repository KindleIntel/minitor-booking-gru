import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

URL = "https://bookings.cloud.microsoft/book/SELAGEMDECELULARESESIMILARESPARAACESSOSREASRESTRITASCpia@gru.com.br/?ismsaljsauthenabled=true"
STATE_FILE = Path("state.json")
WEEKDAYS = r"(?:Domingo|Segunda-feira|Terça-feira|Quarta-feira|Quinta-feira|Sexta-feira|Sábado)"
DATE_LABEL_RE = re.compile(rf"^{WEEKDAYS}, .+")
TIME_RE = re.compile(r"^(?:(?:[01]?\d|2[0-3]):[0-5]\d|(?:0?[1-9]|1[0-2]):[0-5]\d\s*[APap][Mm])$")

def notify(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
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

def visible_times(page):
    times = set()
    # O Bookings pode renderizar horários como botões, opções ou elementos acessíveis.
    candidates = page.locator("button, [role='button'], [role='option'], [role='radio'], [aria-label]")
    for i in range(min(candidates.count(), 500)):
        el = candidates.nth(i)
        try:
            if not el.is_visible():
                continue
            text = (el.inner_text(timeout=250) or "").strip()
            aria = (el.get_attribute("aria-label") or "").strip()
            for value in (text, aria):
                value = value.replace("\n", " ").strip()
                if TIME_RE.fullmatch(value):
                    times.add(value)
        except Exception:
            continue
    # Fallback: horários podem aparecer como linhas de texto sem botão acessível.
    try:
        for line in page.locator("body").inner_text(timeout=3000).splitlines():
            value = line.strip()
            if TIME_RE.fullmatch(value):
                times.add(value)
    except Exception:
        pass
    return sorted(times)

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

        # Verifica exatamente dois meses: o mês inicial e o seguinte.
        for month_index in range(2):
            heading = page.locator("body").inner_text(timeout=5000)
            month_match = re.search(
                r"(Janeiro|Fevereiro|Março|Abril|Maio|Junho|Julho|Agosto|Setembro|Outubro|Novembro|Dezembro)\s+\d{4}",
                heading,
                re.IGNORECASE,
            )
            month_name = month_match.group(0) if month_match else f"Mês {month_index + 1}"
            print(f"VERIFICANDO_MES: {month_name}")

            # Os dias são DIVs com aria-label e aria-disabled, não botões HTML.
            date_cells = page.locator("[aria-label]")
            dates = []
            for i in range(min(date_cells.count(), 500)):
                el = date_cells.nth(i)
                try:
                    label = (el.get_attribute("aria-label") or "").strip()
                    disabled = (el.get_attribute("aria-disabled") or "").lower() == "true"
                    if DATE_LABEL_RE.match(label) and not disabled and el.is_visible():
                        dates.append(label)
                except Exception:
                    continue

            print(f"DIAS_SELECIONAVEIS_{month_index + 1}: {len(dates)}")

            for label in sorted(set(dates)):
                try:
                    # Seleciona o elemento pelo aria-label exato encontrado no calendário.
                    cell = page.locator(f'[aria-label="{label.replace(chr(34), chr(92) + chr(34))}"]').first
                    if not cell.is_visible():
                        continue
                    cell.click(timeout=3000)
                    page.wait_for_timeout(1200)
                    times = visible_times(page)
                    if times:
                        for time_value in times:
                            key = f"{label}|{time_value}"
                            found[key] = {"date": label, "time": time_value}
                        print(f"HORARIOS_{label}: {', '.join(times)}")
                    else:
                        print(f"SEM_HORARIOS_IDENTIFICADOS: {label}")
                except Exception as exc:
                    print(f"ERRO_DATA {label}: {type(exc).__name__}")

            if month_index == 0:
                next_month = page.locator('[aria-label="Próximo mês"]').first
                if not next_month.is_visible():
                    raise RuntimeError("Não foi possível localizar o controle 'Próximo mês'.")
                next_month.click(timeout=3000)
                page.wait_for_timeout(1200)

        browser.close()

    new_items = [item for key, item in found.items() if key not in seen]
    if new_items:
        lines = [
            "🚨 NOVA DISPONIBILIDADE NO BOOKING",
            "Selagem de celulares e similares para acesso às áreas restritas",
            "",
        ]
        for item in new_items:
            lines.append(f"{item['date']}: {item['time']}")
        lines.extend(["", "Abra o agendamento para reservar:", URL])
        notify("\n".join(lines))

    old["seen"] = sorted(seen.union(found.keys()))
    old["last_check_utc"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(old, ensure_ascii=False, indent=2) + "\n")
    print(f"Disponibilidades encontradas: {len(found)}; novas: {len(new_items)}")

if __name__ == "__main__":
    main()
