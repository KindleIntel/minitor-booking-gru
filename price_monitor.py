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
    if not re.search(r"rtx\s*5070\s*ti|geforce\s*rtx\s*5070\s*ti", normalized):
        return False
    if any(term in normalized for term in ("pc gamer", "notebook", "workstation", "computador")):
        return False
    # Exige fabricante/modelo específico da placa; "RTX 5070 Ti" isolado não basta.
    board_brands = ("asus", "gigabyte", "msi", "zotac", "pny", "palit", "gainward",
                    "galax", "inno3d", "colorful", "acer", "manli", "kfa2", "asrock")
    return any(brand in normalized for brand in board_brands)


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
    """Extrai preço total; rejeita valores de parcelas e preços implausíveis."""
    matches = list(re.finditer(r"R\$\s*([0-9][0-9.,]*)", text, re.IGNORECASE))
    if not matches:
        return None, "não identificado"

    def valid_total(match):
        prefix = text[max(0, match.start() - 45):match.start()].lower()
        # Não aceitar "10x de R$ 824,92", "12x R$..." ou valor mensal.
        if re.search(r"\b\d{1,2}\s*x\s*(?:de\s*)?$", prefix):
            return None
        if re.search(r"\bpor\s+m[eê]s\s*$", prefix):
            return None
        value = parse_brl(match.group(1))
        # Piso de sanidade para impedir parcelas/erros de extração.
        if value is None or value < 2500 or value > 20000:
            return None
        return value

    candidates = [(m, valid_total(m)) for m in matches]
    candidates = [(m, value) for m, value in candidates if value is not None]
    if not candidates:
        return None, "não identificado"

    # Preferir preço explicitamente ligado a Pix/boleto/à vista.
    for marker in re.finditer(r"\b(?:no\s+pix|pix|boleto|à\s+vista)\b", text, re.IGNORECASE):
        preceding = [(m, value) for m, value in candidates if m.end() <= marker.start()]
        following = [(m, value) for m, value in candidates if m.start() >= marker.end()]
        chosen = preceding[-1] if preceding else (following[0] if following else None)
        if chosen:
            return chosen[1], "Pix/boleto" if "pix" in marker.group(0).lower() or "boleto" in marker.group(0).lower() else "à vista"

    # Preferir preço após "por:", mas apenas se passar pelos filtros de parcela.
    por = re.search(r"\bpor\s*:\s*", text, re.IGNORECASE)
    if por:
        after = [(m, value) for m, value in candidates if m.start() >= por.end()]
        if after:
            return after[0][1], "preço anunciado"

    return candidates[0][1], "preço anunciado"


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
    if price is None or price < 2500 or price >= 20000:
        return None
    # Nunca alertar URL genérica de busca, campanha ou categoria como se fosse produto.
    from urllib.parse import urlparse
    path = urlparse(href).path.lower()
    if any(term in path for term in ("/busca", "/promocao", "/categoria", "/hardware/placa-de-video")):
        return None
    if len(title.split()) < 4:
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
