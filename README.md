# Monitor Bookings GRU

Monitor de disponibilidade do agendamento público de selagem de celulares e similares, com alertas via Telegram.

## Como a execução automática é disparada
O agendamento periódico é feito externamente pelo cron-job.org, que chama a API oficial do GitHub para iniciar o workflow "Monitorar Bookings GRU - Automático" a cada 10 minutos.

O workflow do GitHub usa somente workflow_dispatch. Isso evita depender do evento schedule nativo do GitHub, que não estava criando execuções neste repositório.

## Configuração do monitor
Em Settings > Secrets and variables > Actions, mantenha estes dois secrets:
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

No Telegram, abra o bot e envie /start.

## Disparo externo (cron-job.org)
- Método: POST
- URL: https://api.github.com/repos/KindleIntel/minitor-booking-gru/actions/workflows/monitor-agendado.yml/dispatches
- Headers:
  - Accept: application/vnd.github+json
  - Authorization: Bearer <FINE_GRAINED_GITHUB_TOKEN>
  - X-GitHub-Api-Version: 2022-11-28
  - Content-Type: application/json
- Body: {"ref":"main","inputs":{"origem":"cron-job.org"}}
- Agendamento: a cada 10 minutos, fuso America/Sao_Paulo.

O token deve ser Fine-grained, limitado somente a este repositório, com a permissão Actions: Read and write. Nunca incluir o token em arquivos públicos ou logs.

## Funcionamento
O monitor verifica o mês apresentado inicialmente e o mês seguinte, procura dias selecionáveis e, para cada dia, tenta identificar horários disponíveis. O estado é salvo em state.json para evitar alertas repetidos; combinações de data/horário que desaparecem e voltam poderão gerar novo alerta.

A automação apenas notifica; não realiza reservas.

## Segurança
O repositório é público; código, arquivos e logs do projeto são visíveis para qualquer pessoa. Os valores dos secrets do GitHub Actions não são exibidos quando usados corretamente. O Fine-grained token usado pelo cron-job.org deve ser restrito a este repositório e apenas à permissão Actions: Read and write.
