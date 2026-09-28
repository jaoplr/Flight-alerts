# Alerta de preços de voo (Google Flights → ntfy)

Script que consulta o Google Flights (via lib `google-flights-search` /
`gf_search`, sem API key) e avisa por notificação ntfy o preço mais
barato encontrado — a cada execução, mesmo que esteja acima do limite.
Quando o preço está dentro do limite definido, a notificação vem com
prioridade **urgente** e o título "🚨 ALERTA PREÇO ABAIXO DO QUE VC DESEJA!".

Pega o preço real da aba **"Menores preços"** do site (não só "Melhor
opção") — confirmado manualmente: bateu exatamente R$1007 com o que o
navegador mostrava, incluindo ofertas de agências de viagem que uma
abordagem mais simples de scraping não pegava.

**Status: já implantado e rodando sozinho** na VPS (Oracle Cloud, Oracle
Linux 9), via cron, a cada 3 horas — não depende do seu PC estar ligado.

## Arquitetura

- `config.py` — único arquivo que você deveria precisar editar no dia a
  dia: rotas monitoradas (origem, destino, data, preço máximo, escala) e
  o tópico ntfy.
- `monitor.py` — a lógica em si. Usa a lib `google-flights-search`
  (`gf_search`), que exige **Python 3.10+** — por isso a VPS tem uma
  venv separada `venv311` (criada com `python3.11 -m venv venv311`),
  diferente da venv padrão do sistema (que continua em Python 3.9).
  Chamamos a lib de forma customizada (não a função `search()` pronta
  dela) porque por padrão ela vem fixada em TWD/chinês — sobrescrevemos
  com `hl=pt-BR`, `gl=BR`, `curr=BRL` e um parâmetro `tfu` específico
  que força os dados da aba "Menores preços". Detalhes nos comentários
  do próprio `monitor.py`.
- `requirements.txt` — dependências (`google-flights-search`, `requests`
  — não precisa de `playwright`, só usamos o modo SSR simples da lib).
- Roda via cron na VPS: `0 */3 * * * cd /home/opc/flight-alert &&
  venv311/bin/python3 monitor.py >> log.txt 2>&1` (a cada 3h, nas horas
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

Depois que o prompt virar `[opc@instance-...]$`, entre na pasta do
projeto e ative o venv certo (Python 3.11, não o padrão do sistema):

```bash
cd flight-alert
source venv311/bin/activate
```

- Editar `monitor.py`: edite local, `scp` igual ao `config.py` acima, e
  se mudou dependências rode `pip install -r requirements.txt` (com o
  venv311 já ativado) na VPS.
- Editar o agendamento do cron: `crontab -e` (use `export EDITOR=nano`
  antes se preferir nano em vez de vim — no nano, salva com Ctrl+O,
  Enter, sai com Ctrl+X; no vim, `i` pra editar, `Esc` depois `:wq` pra
  salvar e sair). Ver agendamento atual: `crontab -l`.
- Ver o log de execuções: `tail -f log.txt` (Ctrl+C pra sair).
- Testar manualmente: `source venv311/bin/activate && python3
  monitor.py`.

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

- **Sem API oficial**: o `gf_search` lê os dados que o Google já embute
  na própria página (SSR), sem precisar de navegador headless. Pode
  quebrar se o Google mudar o formato da página — a lib documenta que
  isso pode acontecer a qualquer momento.
- **Rótulo de moeda com bug conhecido**: o campo `price` que a lib
  retorna vem sempre com o texto `"TWD ..."` na frente, mesmo pedindo
  `curr=BRL` — é um bug de rótulo fixo no código deles, mas o **número**
  já vem correto na moeda pedida (confirmado manualmente). Por isso
  ignoramos esse rótulo e só extraímos o número no `monitor.py`.
- **Filtro de escalas embutido na busca**: a função `build_tfs()` da lib
  não aceita restrição de escalas, então implementamos nossa própria
  versão (`build_tfs_with_stops`, no topo do `monitor.py`) que adiciona
  esse campo no protobuf antes de mandar pro Google. Isso importa porque
  o Google só mostra certas ofertas (principalmente de agências) quando
  a busca já pede "só direto" — filtrar depois, no nosso código, em cima
  de uma busca sem essa restrição, não é a mesma coisa e pode perder a
  oferta mais barata.
- **Cache frio do Google**: às vezes a resposta vem sem a seção de
  ofertas extras (comportamento documentado pela própria lib). Por isso
  `cheapest_flight()` tenta até 3 vezes e junta os resultados de cada
  tentativa antes de escolher o mais barato. Não elimina 100% a
  inconsistência, mas reduz bastante — se ainda notar diferença grande
  vs o navegador, dá pra aumentar esse número de tentativas no código.
- **Memória**: essa versão consulta uma página SSR simples (não é
  navegador headless), então não deve pesar mais que a versão anterior
  — mesmo cuidado de RAM continua valendo (VPS com só 1GB + swap extra).
- **Notificação a cada execução**: diferente de um alerta "só quando
  cai", esse script sempre notifica, com urgência diferente conforme o
  preço. Se achar chato demais, é só aumentar o intervalo no cron (ex:
  `0 */6 * * *` pra 6 em 6h).
- **Preços de ida e volta**: se preencher `return_date` na rota, busca
  o pacote ida+volta; deixando `None`, busca só ida.
- **Python 3.11 residual**: ficou instalado na VPS de um teste anterior
  com outra lib que abandonamos. Não atrapalha nada rodando junto com o
  3.9 padrão; pode remover com `sudo dnf remove python3.11` se quiser
  limpar, mas cuidado — isso quebraria a venv `venv311` que este projeto
  usa agora, então só remova se também recriar a venv de outra forma.