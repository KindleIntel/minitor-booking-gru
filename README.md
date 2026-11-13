# Monitor Bookings GRU

Monitor de disponibilidade do agendamento público de selagem de celulares, com alertas via Telegram.

## Configuração
1. Em Settings > Secrets and variables > Actions, configure:
   - TELEGRAM_BOT_TOKEN
   - TELEGRAM_CHAT_ID
2. No Telegram, abra o bot e envie /start.
3. Em Actions, habilite workflows se o GitHub solicitar.
4. Execute "Monitorar Bookings GRU" com Run workflow para testar.

## Frequência e limites
O agendamento está configurado para a cada 30 minutos. O GitHub Actions aceita no mínimo 5 minutos, mas execuções agendadas podem atrasar. Em repositórios privados, o uso consome a franquia mensal de computação da conta.

O monitor visita a página pública, verifica dias/horários selecionáveis e envia Telegram somente para novas combinações detectadas. A automação não reserva horários.
