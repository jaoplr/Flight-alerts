# Alerta de preços de voo (Google Flights → ntfy)

Script que consulta o Google Flights (via biblioteca não-oficial `fast-flights`,
sem API key) e avisa por notificação ntfy o preço mais barato encontrado —
a cada execução, mesmo que esteja acima do limite. Quando o preço está
dentro do limite definido, a notificação vem com prioridade **urgente** e
o título "🚨 ALERTA PREÇO ABAIXO DO QUE VC DESEJA!".

**Status: já implantado e rodando sozinho** na VPS (Oracle Cloud, Oracle
Linux 9), via cron, a cada 3 horas — não depende do seu PC estar ligado.

## Arquitetura

- `config.py` — único arquivo que você deveria precisar editar no dia a
  dia: rotas monitoradas (origem, destino, data, preço máximo, escala) e
  o tópico ntfy.
- `monitor.py` — a lógica em si. Usa `fast-flights==2.2` (versão travada
  no `requirements.txt` porque a VPS roda Python 3.9, e versões mais
  novas da lib exigem Python 3.10+).
- `requirements.txt` — dependências.
- Roda via cron na VPS: `0 */3 * * * cd /home/opc/flight-alert &&
  venv/bin/python3 monitor.py >> log.txt 2>&1` (a cada 3h, nas horas
  cheias: 00h, 03h, 06h, 09h, 12h, 15h, 18h, 21h no horário da VPS —
  confirme o fuso da VPS com `timedatectl`).

## Como atualizar as rotas monitoradas (origem, destino, preço, escala)

Não precisa entrar na VPS pra isso. Só dois passos, sempre no
**PowerShell do seu PC**, na pasta do projeto local:

1. Edite `config.py` no seu editor normalmente e salve.
2. Envie o arquivo atualizado pra VPS:
   ```powershell
   scp -i "C:\Users\johnn\Downloads\ssh-key-2026-08-29 (1).key" config.py opc@168.75.82.60:~/flight-alert/
   ```

Pronto — a próxima execução do cron (dentro de até 3h) já vai usar o
`config.py` novo automaticamente, sem precisar reiniciar nada.

## Se precisar mexer no monitor.py ou no cron em si

Aí sim é preciso entrar na VPS:

```powershell
ssh -i "C:\Users\johnn\Downloads\ssh-key-2026-08-29 (1).key" opc@168.75.82.60
```

- Editar `monitor.py`: edite local, `scp` igual ao `config.py` acima, e
  se mudou dependências rode `source venv/bin/activate && pip install -r
  requirements.txt` na VPS.
- Editar o agendamento do cron: `crontab -e` (use `export EDITOR=nano`
  antes se preferir nano em vez de vim). Ver agendamento atual:
  `crontab -l`.
- Ver o log de execuções: `tail -f log.txt` (Ctrl+C pra sair).
- Testar manualmente: `source venv/bin/activate && python3 monitor.py`.

## Pausar ou desativar

- **Parar de receber notificação sem mexer no servidor**: no app ntfy,
  cancele a inscrição (unsubscribe) do tópico. O script continua rodando
  na VPS de fundo (sem custo), só ninguém recebe o aviso. Pra voltar, é
  só se inscrever de novo no mesmo tópico.
- **Pausar o script de vez** (via SSH na VPS): `crontab -e`, coloque `#`
  no início da linha do cron pra comentá-la, salve. Reative depois
  removendo o `#`. Confirme com `crontab -l`.
- **Apagar de vez**: `crontab -e` e apague a linha inteira (ou
  `crontab -r` remove todo o crontab do usuário — cuidado, remove tudo,
  não só essa linha).

## Rotas com data já passada

O script não remove sozinho rotas cuja data já passou — ele só não vai
encontrar voos e vai ficar quieto pra aquela rota (sem erro), mas
continua tentando consultá-la a cada execução até você tirar do
`config.py`. Depois que a data passa (ou você já comprou a passagem),
apague ou comente o bloco daquela rota em `config.py` e reenvie pra VPS
com o `scp` (seção acima).

## Receber as notificações

- App: instale o **ntfy** (Android/iOS) e inscreva-se no tópico definido
  em `NTFY_TOPIC` no `config.py`.
- Sem app: `https://ntfy.sh/<seu-topico>` no navegador (só funciona
  enquanto a aba estiver aberta).

## Observações importantes

- **Sem API oficial**: o `fast-flights` faz scraping da página do
  Google Flights. Pode quebrar se o Google mudar o layout — se um dia
  parar de funcionar, o primeiro passo é checar se saiu uma versão nova
  compatível (`pip index versions fast-flights` na VPS, considerando
  que ela está presa no Python 3.9).
- **Notificação a cada execução**: diferente de um alerta "só quando
  cai", esse script sempre notifica, com urgência diferente conforme o
  preço. Se achar chato demais, é só aumentar o intervalo no cron (ex:
  `0 */6 * * *` pra 6 em 6h).
- **Preços de ida e volta**: se preencher `return_date` na rota, busca
  o pacote ida+volta; deixando `None`, busca só ida.