# Guia do dono: como vender e operar o Agendador

## O que o cliente recebe
Um site com login. Ele se cadastra (teste grátis de `TESTE_DIAS` dias), conecta o Instagram dele pelo
assistente e agenda Reels e Stories em lote. O servidor publica na hora, com o PC dele desligado.

## Por que o cliente cria o próprio "app" na Meta
Para uma ferramenta publicar no Instagram de **outras pessoas** com um app só (o seu), a Meta exige
**Análise do App** + **verificação da empresa** (semanas, com CNPJ, vídeo demonstrando, política de
privacidade etc.). Com cada cliente usando o **app dele mesmo**, isso não é necessário: dono do app
pode publicar na própria conta. É o que permite vender **já**.

O custo é um passo de configuração a mais para o cliente (~10 min, uma vez). O assistente em
`/conectar` guia clique a clique e mostra erros em português. **Ofereça fazer junto por
chamada/WhatsApp nos primeiros clientes.** Isso vira diferencial ("a gente configura pra você").

**Evolução natural:** quando tiver clientes pagando, submeta o seu app à Análise da Meta. Aprovado,
dá para trocar o assistente por um botão "Entrar com Facebook" (sem o cliente criar app).

## Rotina de vendas (cobrança manual)
1. Cliente se cadastra sozinho no site → ganha o teste.
2. Você vê em **/admin** quem entrou (nome, e-mail, WhatsApp, se já conectou a conta, quantos posts agendou).
3. Ele paga (Pix / link de pagamento) → em /admin clique **+30 dias** e anote na nota ("pagou Pix 22/09").
4. O card "vencem em 7 dias" mostra quem cobrar. Vencido, o cliente continua entrando, mas não agenda
   nada novo e os agendados ficam pausados. A faixa vermelha no painel dele tem o botão "Renovar pelo WhatsApp".
5. Plano agência: em /admin mude **contas** para 3, 5, 10… (quantos Instagrams ele pode conectar).
6. Esqueceu a senha: /admin → **nova senha** → mande a senha provisória pelo WhatsApp.

## Antes de vender (checklist)
- [ ] Nome do produto, preço, WhatsApp de suporte e razão social/CNPJ no `.env`
- [ ] Revisar **Termos de uso** e **Privacidade** (`templates/legal.html`) com um advogado e tirar a faixa "MODELO"
- [ ] Domínio próprio + HTTPS
- [ ] Backup diário do banco (ver DEPLOY.md)
- [ ] Fazer o passo a passo de conexão do zero numa conta de teste, para saber guiar o cliente
- [ ] `PUBLICAR_DE_VERDADE=1` depois do teste

## Limites que é bom saber (e dizer ao cliente)
- Só **vídeo** (Reels e Stories). Foto e carrossel precisam do vídeo/imagem numa URL pública; dá para
  adicionar depois, porque a VPS já tem URL pública.
- Story: até 60s. Reels: 3s a 15min. Legenda até 2.200 caracteres e 30 hashtags (a tela avisa antes).
- A API não põe música, figurinha, enquete nem link em Story. Para isso, só pelo app do Instagram.
- O Instagram limita cerca de 50 publicações por conta a cada 24h (a tela avisa se passar).
- Se o cliente trocar a senha do Facebook ou remover o app, a conta fica "desconectada": os posts dela
  vão para erro e ele precisa refazer o passo 5 do assistente. O /admin mostra isso em vermelho.
