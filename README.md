# Monitor Bookings GRU

Monitor da agenda pública de selagem de celulares e similares, com notificações pelo Telegram.

## Workflows
- **Monitorar Bookings GRU - Automático**: verifica a agenda a cada 10 minutos.
- **Monitorar Bookings GRU**: permite executar a verificação manualmente.
- **Testar Telegram**: envia uma mensagem isolada de teste.

## Configuração
Em Settings > Secrets and variables > Actions, mantenha estes dois secrets:
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

No Telegram, abra o bot e envie /start.

## Funcionamento
O monitor verifica o mês apresentado inicialmente e o mês seguinte, procura dias selecionáveis e, para cada dia, tenta identificar os horários disponíveis. O estado é salvo em state.json para que uma combinação de data e horário nova (ou que volte a aparecer depois de desaparecer) possa gerar um novo alerta.

A automação apenas notifica; não realiza reservas.

## Frequência e limites
O workflow automático tenta executar a cada 10 minutos, em horários deslocados dos minutos redondos. O GitHub pode atrasar ou, em situações de alta carga, descartar execuções agendadas. O workflow também executa uma vez na publicação/alteração do seu próprio arquivo, para validar que o gatilho de publicação está ativo.

## Segurança
O token do bot e o identificador do chat devem permanecer exclusivamente em GitHub Actions Secrets; nunca os coloque nos arquivos do repositório.

Como o repositório é público, todos os arquivos, código e logs de execução podem ser vistos por qualquer pessoa. Os valores dos secrets não são exibidos nos logs quando usados corretamente.
