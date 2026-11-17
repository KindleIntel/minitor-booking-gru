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


## Monitor de preços NVIDIA RTX 5070 Ti

O mesmo disparo do cron-job.org executa também `price_monitor.py`, a cada 10 minutos.

- Produto monitorado: NVIDIA GeForce RTX 5070 Ti (16 GB).
- Limite: alerta somente para preço anunciado **inferior a R$ 8.000,00**.
- Pagamento: considera o preço total anunciado, inclusive à vista/Pix; o alerta inclui o link para conferir a condição na loja.
- Condição: ignora anúncios que indiquem usado, seminovo, recondicionado ou Open Box.
- Fontes: PCFinder (comparador que reúne ofertas de KaBuM!, Patoloco, Pichau, Terabyte e outros varejistas) e uma página de produto da TNT Info.
- Outras lojas que podem aparecer no comparador: Amazon, Microgem, Guerra Digital, Setup Ninja, Login, Magalu, ITX Gamer, entre outras.
- Alertas: envia no Telegram quando uma oferta abaixo do limite aparece pela primeira vez ou quando o preço cai. Não repete o mesmo alerta a cada execução.
- O histórico de preços/alertas fica em `price_state.json`.


### Fontes da pesquisa RTX 5070 Ti

Além do comparador PCFinder, o monitor abre páginas próprias de:
- KaBuM! — busca por RTX 5070 Ti;
- TNT Info — categoria de placas de vídeo;
- Patoloco — página inicial/ofertas;
- Pichau — categoria NVIDIA;
- TerabyteShop — busca por RTX 5070 Ti.

O script tenta extrair o preço anunciado em cada cartão de produto e prioriza o valor promocional indicado após "por:", ou o valor mais próximo de Pix/boleto/à vista. Cartões sem URL de produto, sem preço legível ou marcados como indisponíveis são descartados. Preços e estoque podem mudar entre as consultas.

A disponibilidade, o preço final, o vendedor, a condição do produto e o frete devem ser confirmados na página da loja antes da compra. Comparadores podem apresentar preço desatualizado ou link intermediário. A verificação atual filtra termos de produto usado/recondicionado, mas não consegue garantir automaticamente todos os detalhes de cada vendedor/marketplace.

## Segurança
O repositório é público; código, arquivos e logs do projeto são visíveis para qualquer pessoa. Os valores dos secrets do GitHub Actions não são exibidos quando usados corretamente. O Fine-grained token usado pelo cron-job.org deve ser restrito a este repositório e apenas à permissão Actions: Read and write.
