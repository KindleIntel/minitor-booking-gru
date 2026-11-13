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
O agendamento está configurado para tentar executar a cada 10 minutos. O GitHub Actions permite agendamento por cron a partir de 5 minutos, mas execuções agendadas podem atrasar ou ser enfileiradas.

Em repositórios públicos, os executores padrão hospedados pelo GitHub são gratuitos. Em repositórios privados, o consumo é descontado da franquia mensal da conta e pode gerar cobrança ao excedê-la.

O monitor consulta o mês inicial e o seguinte, verifica os dias selecionáveis e procura horários. O Telegram recebe notificações quando uma combinação de data e horário aparece pela primeira vez ou volta a ficar disponível. A automação não realiza reservas.

## Segurança
O token do bot e o identificador do chat devem permanecer exclusivamente em GitHub Actions Secrets; nunca os coloque nos arquivos do repositório.
