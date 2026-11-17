import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

LIMIT = 8000.00
STATE_FILE = Path("price_state.json")
PCFINDER_URL = "https://pcfinder.com.br/placas-de-video/rtx-5070-ti"

# Fontes diretas das lojas solicitadas. O PCFinder continua como fonte agregadora.
DIRECT_SOURCES = [
    ("KaBuM", "https://www.kabum.com.br/busca/rtx-5070-ti"),
    ("TNT Info", "https://www.tntinfo.com.br/hardwares/placa-de-video"),
    ("Patoloco", "https://patoloco.com.br/"),
    ("Pichau", "https://www.pichau.com.br/hardware/placa-de-video/nvidia"),
    ("Terabyte", "https://www.terabyteshop.com.br/busca?str=rtx+5070+ti"),
]

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
UNAVAILABLE_TERMS = ("indisponível", "indisponivel", "esgotado", "sem estoque")


def notify(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": "false",
    }).encode()
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
    if "," in value and "." in value:
        # O último separador é o decimal: aceita 7.999,90 e 7,999.90.
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(".", "").replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None


def is_target_title(title):
    normalized = re.sub(r"\s+", " ", title).lower()
    if "5070 ti" not in normalized and "5070ti" not in normalized:
        return False
    if not any(term in normalized for term in ("rtx", "geforce", "nvidia")):
        return False
    if any(term in normalized for term in ("pc gamer", "notebook", "workstation", "computador")):
        return False
    return True


def excluded(text):
    lowered = text.lower()
    return any(term in lowered for term in EXCLUDE_TERMS)


def unavailable(text):
    lowered = text.lower()
    return any(term in lowered for term in UNAVAILABLE_TERMS)


def store_in_text(text):
    lowered = text.lower()
    for store in KNOWN_STORES:
        if store.lower() in lowered:
            return store
    return None


def extract_price(text):
    """Escolhe o preço de venda, dando preferência ao valor atual à vista/Pix."""
    matches = list(re.finditer(r"R\$\s*([0-9][0-9.,]*)", text, re.IGNORECASE))
    if not matches:
        return None, "não identificado"

    def parsed(match):
        return parse_brl(match.group(1))

    # Nas lojas, o preço promocional normalmente vem depois de "por:".
    por = re.search(r"\bpor\s*:\s*", text, re.IGNORECASE)
    if por:
        after = [m for m in matches if m.start() >= por.end()]
        if after:
            chosen = after[0]
            price = parsed(chosen)
            if price is not None:
                window = text[chosen.start():min(len(text), chosen.end() + 90)].lower()
                method = "Pix/boleto" if ("pix" in window or "boleto" in window) else "preço anunciado"
                return price, method

    # Se a página destaca Pix ou boleto, usa o valor mais próximo desse marcador.
    markers = list(re.finditer(r"\b(?:no\s+pix|pix|boleto)\b", text, re.IGNORECASE))
    if markers:
        marker = markers[0]
        nearest = min(matches, key=lambda m: abs(m.start() - marker.start()))
        price = parsed(nearest)
        if price is not None:
            return price, "Pix/boleto"

    # Formato "à vista R$ 9.599,99" ou "R$ 7.999,00 à vista".
    vista = re.search(r"à\s+vista", text, re.IGNORECASE)
    if vista:
        nearest = min(matches, key=lambda m: abs(m.start() - vista.start()))
        price = parsed(nearest)
        if price is not None:
            return price, "à vista"

    price = parsed(matches[0])
    return (price, "preço anunciado") if price is not None else (None, "não identificado")


def extract_target_title(text):
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if is_target_title(line):
            # Evita salvar o bloco inteiro quando a loja entrega texto numa única linha.
            title = re.split(r"\s+(?:R\$|de R\$|por:)", line, maxsplit=1, flags=re.IGNORECASE)[0]
            if is_target_title(title):
                return title[:240]
    match = re.search(
        r"(?i)((?:Placa\s+de\s+(?:V[ií]deo|Video)|NVIDIA|GeForce|RTX)[^\n]{0,240}?(?:RTX\s*)?5070\s*Ti[^\n]{0,120})",
        text,
    )
    if match:
        return re.split(r"\s+(?:R\$|de R\$|por:)", match.group(1), maxsplit=1, flags=re.IGNORECASE)[0][:240]
    return ""


def extract_card_links(page):
    # Sobe do link do produto até o menor contêiner que contenha título e preço.
    return page.locator("a[href]").evaluate_all(r"""els => els.map(a => {
      let el = a;
      let best = "";
      for (let i = 0; i < 9 && el; i++, el = el.parentElement) {
        const t = (el.innerText || "").trim();
        if (/5070\s*ti/i.test(t) && /R\s*\$/i.test(t) && t.length >= 25 && t.length <= 2200) {
          best = t;
          break;
        }
      }
      return {href: a.href, text: best};
    }).filter(x => x.text && x.href && /^https?:/i.test(x.href))""")


def offer_from_card(store, block, href, source):
    if not block or not href or excluded(block) or unavailable(block):
        return None
    title = extract_target_title(block)
    if not title or not is_target_title(title):
        return None
    price, payment = extract_price(block)
    if price is None or price <= 0:
        return None
    return {
        "store": store,
        "title": title,
        "price": round(price, 2),
        "payment": payment,
        "url": href,
        "source": source,
    }


def extract_pcfinder(page):
    offers = []
    anchors = page.locator("a").evaluate_all(r"""els => els
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
        store = store_in_text(block)
        if not store:
            continue
        offer = offer_from_card(store, block, item.get("href") or "", "PCFinder")
        if offer:
            offers.append(offer)
    return offers


def extract_direct_source(page, store, url):
    offers = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=50000)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(1800)
        cards = extract_card_links(page)
        for item in cards:
            href = item.get("href") or ""
            # O link de cada item deve permanecer na própria loja.
            if store.lower().replace(" ", "") not in (urlparse_host(href).lower().replace("www.", "").replace(".", "")):
                # Algumas lojas usam links internos com domínio alternativo/CDN; valida pelo host da origem abaixo.
                if urlparse_host(href) and not same_shop_host(url, href, store):
                    continue
            offer = offer_from_card(store, item.get("text") or "", href, store)
            if offer:
                offers.append(offer)
        # Algumas páginas têm um produto em destaque sem link envolvendo o card inteiro.
        body = page.locator("body").inner_text(timeout=7000)
        if is_target_title(extract_target_title(body)) and not excluded(body) and not unavailable(body):
            # Não cria oferta sem URL específica; evita mandar o usuário para uma busca genérica.
            title = extract_target_title(body)
            price, payment = extract_price(body)
            product_links = [
                item.get("href") for item in cards
                if item.get("href") and is_target_title(extract_target_title(item.get("text") or ""))
            ]
            if price is not None and product_links:
                offer = {
                    "store": store, "title": title, "price": round(price, 2),
                    "payment": payment, "url": product_links[0], "source": store,
                }
                offers.append(offer)
        print(f"OFERTAS_{store.upper().replace(' ', '_')}: {len(offers)}")
    except Exception as exc:
        print(f"ERRO_{store.upper().replace(' ', '_')}: {type(exc).__name__}: {exc}")
    return offers


def urlparse_host(url):
    from urllib.parse import urlparse
    try:
        return urlparse(url).netloc
    except Exception:
        return ""


def same_shop_host(source_url, product_url, store):
    a = urlparse_host(source_url).lower().replace("www.", "")
    b = urlparse_host(product_url).lower().replace("www.", "")
    if not a or not b:
        return False
    if store == "KaBuM":
        return "kabum.com.br" in b
    if store == "TNT Info":
        return "tntinfo.com.br" in b
    if store == "Patoloco":
        return "patoloco.com.br" in b
    if store == "Pichau":
        return "pichau.com.br" in b
    if store == "Terabyte":
        return "terabyteshop.com.br" in b
    return a == b


def main():
    old = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {"offers": {}}
    old_offers = old.get("offers", {})
    current = {}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="pt-BR", timezone_id="America/Sao_Paulo")

        try:
            page.goto(PCFINDER_URL, wait_until="domcontentloaded", timeout=50000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(1800)
            discovered = extract_pcfinder(page)
            print(f"PCFINDER_OFERTAS_LIDAS: {len(discovered)}")
            for offer in discovered:
                key = f"{offer['store']}|{offer['title']}|{offer['url']}"
                current[key] = offer
        except Exception as exc:
            print(f"ERRO_PCFINDER: {type(exc).__name__}: {exc}")

        for store, source_url in DIRECT_SOURCES:
            for offer in extract_direct_source(page, store, source_url):
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
        # Evita duas mensagens para o mesmo modelo/loja quando ele aparece no comparador e na fonte direta.
        unique_alerts = {}
        for offer in alerts:
            signature = (offer["store"].lower(), re.sub(r"\W+", "", offer["title"].lower()))
            if signature not in unique_alerts or offer["price"] < unique_alerts[signature]["price"]:
                unique_alerts[signature] = offer
        alerts = sorted(unique_alerts.values(), key=lambda item: item["price"])
        lines = [
            "🚨 OFERTA RTX 5070 Ti ABAIXO DE R$ 8.000",
            "Somente anúncios sem indicação de usado/recondicionado/Open Box.",
            "",
        ]
        for offer in alerts:
            formatted = f"R$ {offer['price']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            lines.extend([
                f"💰 {formatted} ({offer.get('payment', 'preço anunciado')})",
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

    # Conserva ofertas por até 30 dias para não gerar alertas duplicados em falhas transitórias.
    now = datetime.now(timezone.utc)
    merged = dict(old_offers)
    for key, offer in current.items():
        merged[key] = {
            "price": offer["price"], "store": offer["store"], "title": offer["title"],
            "url": offer["url"], "payment": offer.get("payment", ""),
            "last_seen": now.isoformat(),
        }
    cutoff = now - timedelta(days=30)
    kept = {}
    for key, value in merged.items():
        try:
            last_seen = datetime.fromisoformat(value.get("last_seen", old.get("last_check_utc", now.isoformat())))
            if last_seen >= cutoff:
                kept[key] = value
        except Exception:
            kept[key] = value

    old["offers"] = kept
    old["last_check_utc"] = now.isoformat()
    STATE_FILE.write_text(json.dumps(old, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OFERTAS_MONITORADAS_TOTAL: {len(current)}")


if __name__ == "__main__":
    main()
