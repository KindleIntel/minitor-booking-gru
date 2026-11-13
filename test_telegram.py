import json
import os
import urllib.parse
import urllib.request

token = os.environ["TELEGRAM_BOT_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]

message = (
    "✅ TESTE DO MONITOR BOOKING GRU\n\n"
    "A conexão do GitHub Actions com seu bot do Telegram está funcionando.\n"
    "Este é apenas um teste; nenhuma vaga foi identificada ou reservada."
)

data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
request = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/sendMessage",
    data=data,
    method="POST",
)
with urllib.request.urlopen(request, timeout=20) as response:
    result = json.loads(response.read().decode())

if not result.get("ok"):
    raise RuntimeError("Telegram não confirmou o envio.")

print("Mensagem de teste enviada e confirmada pela API do Telegram.")
