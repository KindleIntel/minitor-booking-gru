import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

LIMIT = 8000.00
STATE_FILE = Path("price_state.json")
PCFINDER_URL = "https://pcfinder.com.br/placas-de-video/rtx-5070-ti"
TNT_URL = "https://www.tntinfo.com.br/produto/placa-de-video-nvidia-geforce-gigabyte-rtx5070ti-aero-oc-16gb-gddr7-256-bits-gv-n507taero-oc-16gd-150193"

# Lojas solicitadas e outros varejistas nacionais identificados no comparador.
KNOWN_STORES = [
    "KaBuM", "TNT Info", "Patoloco", "Pichau", "Terabyte",
    "Amazon", "Microgem", "Guerra Digital", "Setup Ninja", "Login",
    "Aeroluz", "Magalu", "ITX Gamer", "Oficina dos Bits",
    "Livestore Online", "Carrefour", "CiaPC",
]

EXCLUDE_TERMS = (
    "usado", "seminovo", "semi-novo", "recondicionado",
    "open box", "openbox", "mostruario", "mostruário",
)


def notify(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message, "disable_web_page_preview": "false"}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        result = json.loads(response.read().decode())
    if not result.get("ok"):
        raise RuntimeError("Telegram recusou o envio da mensagem")


def parse_brl(value):
    value = value.replace("R$", "").replace("\xa0", " ").strip()
    value = re.sub(r"[^0-9,.]", "", value)
    if not value:
        return None
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None


def is_target_title(title):
    normalized = re.sub(r"\s+", " ", title).lower()
    return "5070 ti" in normalized and ("rtx" in normalized or "geforce" in normalized)


def excluded(text):
    lowered = text.lower()
    return any(term in lowered for term in EXCLUDE_TERMS)


def store_in_text(text):
    lowered = text.lower()
    for store in KNOWN_STORES:
        if store.lower() in lowered:
            return store
    return None


def extract_pcfinder(page):
    offers = []
    anchors = page.locator("a").evaluate_all("""els => els
      .filter(a => (a.innerText || "").trim().toLowerCase().includes("ver na loja"))
      .map(a => {
        let el = a;
        let best = "";
        for (let i = 0; i < 9 && el; i++, el = el.parentElement) {
          const t = (el.innerText || "").trim();
          if (/5070\s*ti/i.test(t) && /R\s*\$/i.test(t) && t.length < 1800) {
            best = t;
            break;
          }
        }
        return {href: a.href, text: best};
      })""")

    for item in anchors:
        block = item.get("text") or ""
        href = item.get("href") or ""
        if not block or not href or excluded(block):
            continue
        lines = [re.sub(r"\s+", " ", line).strip() for line in block.splitlines() if line.strip()]
        title = next((line for line in lines if is_target_title(line)), "")
        store = store_in_text(block)
        if not title or not store:
            continue

        prices = []
        for match in re.finditer(r"R\$\s*([0-9.]+,[0-9]{2})", block, re.IGNORECASE):
            price = parse_brl(match.group(1))
            if price is not None:
                prices.append(price)
        if not prices:
            continue
        price = min(prices)

        # O comparador agrega ofertas de varejistas; remove linhas sem preço real ou indisponíveis.
        if re.search(r"indispon[ií]vel|esgotado|sem estoque", block, re.IGNORECASE):
            continue

        offers.append({
            "store": store,
            "title": title[:220],
            "price": round(price, 2),
            "url": href,
            "source": "PCFinder",
        })
    return offers


def extract_tnt(page):
    offers = []
    try:
        page.goto(TNT_URL, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(1500)
        body = page.locator("body").inner_text(timeout=7000)
        title = next((line.strip() for line in body.splitlines() if is_target_title(line)), "")
        if not title or excluded(body) or re.search(r"indispon[ií]vel|esgotado|sem estoque", body, re.IGNORECASE):
            return offers

        prices = []
        for match in re.finditer(r"R\$\s*([0-9.]+,[0-9]{2})", body, re.IGNORECASE):
            price = parse_brl(match.group(1))
            if price is not None:
                prices.append(price)
        if prices:
            offers.append({
                "store": "TNT Info",
                "title": title[:220],
                "price": round(min(prices), 2),
                "url": TNT_URL,
                "source": "TNT Info",
            })
    except Exception as exc:
        print(f"ERRO_TNT: {type(exc).__name__}: {exc}")
    return offers


def main():
    old = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {"offers": {}}
    old_offers = old.get("offers", {})
    current = {}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="pt-BR", timezone_id="America/Sao_Paulo")
        try:
            page.goto(PCFINDER_URL, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(1500)
            discovered = extract_pcfinder(page)
            print(f"PCFINDER_OFERTAS_LIDAS: {len(discovered)}")
            for offer in discovered:
                key = f"{offer['store']}|{offer['title']}|{offer['url']}"
                current[key] = offer
        except Exception as exc:
            print(f"ERRO_PCFINDER: {type(exc).__name__}: {exc}")

        tnt_offers = extract_tnt(page)
        print(f"TNT_OFERTAS_LIDAS: {len(tnt_offers)}")
        for offer in tnt_offers:
            key = f"{offer['store']}|{offer['title']}|{offer['url']}"
            current[key] = offer
        browser.close()

    alerts = []
    for key, offer in current.items():
        previous = old_offers.get(key)
        price = offer["price"]
        if price < LIMIT and (previous is None or price < float(previous.get("price", 999999)) - 0.009):
            alerts.append(offer)

    if alerts:
        alerts.sort(key=lambda item: item["price"])
        lines = [
            "🚨 OFERTA RTX 5070 Ti ABAIXO DE R$ 8.000",
            "Somente anúncios sem indicação de usado/recondicionado.",
            "",
        ]
        for offer in alerts:
            lines.extend([
                f"💰 R$ {offer['price']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                f"🏪 {offer['store']}",
                offer["title"],
                offer["url"],
                "",
            ])
        lines.append("Confira estoque, vendedor, frete e condição final no site antes de comprar.")
        notify("\n".join(lines))
        print(f"ALERTAS_ENVIADOS: {len(alerts)}")
    else:
        print("SEM_NOVAS_OFERTAS_ABAIXO_DO_LIMITE")

    old["offers"] = {
        key: {"price": offer["price"], "store": offer["store"], "title": offer["title"], "url": offer["url"]}
        for key, offer in current.items()
    }
    old["last_check_utc"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(old, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OFERTAS_MONITORADAS: {len(current)}")


if __name__ == "__main__":
    main()
