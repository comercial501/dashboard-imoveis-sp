# Torre de Controle no celular — passo a passo na Cloudflare

Tudo aqui é feito por você, em ordem. Eu não crio conta nem digito senha por você. Cada etapa diz **o que você vai ver** e **o que me mandar** quando precisar. Se algum menu estiver com nome um pouco diferente do que está escrito (a Cloudflare muda os nomes de vez em quando), procure pela palavra em **negrito**.

O acesso que você já tem pelo Tailscale **continua igual**. Nada aqui mexe nele.

## Como vai funcionar (em 3 linhas)
1. Toda vez que a atualização diária termina bem, o GitHub envia o site para a Cloudflare.
2. Quem abrir o endereço da Cloudflare cai numa tela pedindo o e-mail; a Cloudflare manda um **código de 6 dígitos** para esse e-mail (só se ele estiver na sua lista).
3. Além disso, o próprio site confere o login antes de entregar qualquer arquivo. Se alguém tentar abrir um arquivo direto, sem login, recebe "Acesso negado".

---

## Parte 1 — Conta e chaves (uns 10 minutos)

**1. Criar a conta.** Entre em https://dash.cloudflare.com/sign-up, use o e-mail `comercial@topio.com.br` (ou outro que você controle), crie uma senha forte e confirme o e-mail que a Cloudflare enviar. O plano é o **Free** (gratuito).

**2. Anotar o "Account ID".** No painel, clique em **Workers & Pages** (menu da esquerda). Na lateral direita aparece **Account ID** (uma sequência de letras e números). Clique em copiar e guarde — é o dado nº 1.

**3. Criar a chave de publicação.**
- Clique no seu ícone (canto superior direito) → **My Profile** → **API Tokens** → **Create Token**.
- Escolha **Create Custom Token**.
- Nome: `torre-de-controle-github`.
- Em **Permissions**: **Account** · **Cloudflare Pages** · **Edit**. (Só essa. Nada mais.)
- Em **Account Resources**: Include · sua conta.
- **Continue to summary** → **Create Token**. Copie o token (a Cloudflare só mostra **uma vez**) — é o dado nº 2.

**4. Escolher o nome do endereço.** O site vai ficar em `NOME.pages.dev`. Escolha um nome sem acento e sem espaço (ex.: `torre-topio`). É o dado nº 3. (O nome não é segredo, mas não use algo óbvio como "topio".)

## Parte 2 — Entregar as chaves ao GitHub (uns 5 minutos)
Abra https://github.com/comercial501/dashboard-imoveis-sp/settings/secrets/actions → **New repository secret**. Crie **três**, com **exatamente** estes nomes:

| Nome do segredo | Valor |
|---|---|
| `CLOUDFLARE_ACCOUNT_ID` | o Account ID (dado nº 1) |
| `CLOUDFLARE_API_TOKEN` | o token (dado nº 2) |
| `CLOUDFLARE_PAGES_PROJECT` | o nome do endereço (dado nº 3), ex.: `torre-topio` |

## Parte 3 — Primeira publicação (2 minutos)
No GitHub: aba **Actions** → **Publicar na Cloudflare (manual)** → **Run workflow**. Em 1–2 minutos termina. No final do passo "Publicar na Cloudflare Pages" aparecem dois endereços, parecidos com `https://torre-topio.pages.dev` e `https://a1b2c3d4.torre-topio.pages.dev`. **Me mande os dois.**

Neste ponto o site ainda **não está liberado para ninguém**: sem a Parte 4 ele responde "Acesso ainda não configurado" (503). É de propósito — o padrão é fechado.

## Parte 4 — Login por código no e-mail (uns 15 minutos)

**5. Abrir o Zero Trust.** No painel da Cloudflare, menu da esquerda: **Zero Trust**. Na primeira vez a Cloudflare pede para **criar o nome da sua equipe** (ex.: `topio`) e escolher o plano **Free** (até 50 pessoas). Pode pedir um cartão para ativar — no plano Free não há cobrança, mas confirme o que a tela disser antes de continuar. O endereço da equipe será `https://NOME-DA-EQUIPE.cloudflareaccess.com` — é o dado nº 4.

**6. Ligar o login por código.** Zero Trust → **Integrations** → **Identity providers** → **Add new identity provider** → **One-time PIN**. Salve. (Se a Cloudflare disser que o e-mail dos códigos pode cair no spam, avise a quem vai usar para liberar o remetente `noreply@notify.cloudflare.com`.)

**7. Criar o aplicativo protegido.** Zero Trust → **Access controls** (ou **Access**) → **Applications** → **Add an application** → **Self-hosted**.
- Nome: `Torre de Controle`.
- Duração da sessão: **1 month** (no celular você não precisa pedir código toda hora).
- **Public hostname / Application domain**: adicione **dois** endereços:
  1. `NOME.pages.dev` (o do dado nº 3, ex.: `torre-topio.pages.dev`)
  2. `*.NOME.pages.dev` (com o asterisco — cobre o endereço único de cada publicação)
- **Policies** → **Add a policy** → ação **Allow** → regra **Include** → **Emails** → digite **um por linha** os e-mails liberados (o seu e os de quem mais deve ver). Quem não estiver na lista não recebe nem o código.
- Em **Login methods**, deixe só **One-time PIN**.
- Salve. Depois abra o aplicativo criado e copie o **Application Audience (AUD) Tag** (uma sequência longa de letras e números) — é o dado nº 5.

**8. Avisar o site quem é o dono da porta.** Workers & Pages → clique no projeto `NOME` → **Settings** → **Variables and Secrets** → **Add** (ambiente **Production**; se pedir, faça também em **Preview**):

| Nome | Valor |
|---|---|
| `TEAM_DOMAIN` | `https://NOME-DA-EQUIPE.cloudflareaccess.com` (dado nº 4, **sem barra no final**) |
| `POLICY_AUD` | o AUD Tag (dado nº 5) |

Salve e publique de novo: GitHub → **Actions** → **Publicar na Cloudflare (manual)** → **Run workflow**. (Sem esse passo as variáveis novas não valem.)

## Parte 5 — Testes
- **Eu testo (sem login):** me mande os endereços; eu rodo `scripts/testar_acesso_anonimo.py` em cada um e confirmo que nenhum arquivo de dados abre.
- **Você testa numa aba anônima do navegador:** abra `https://NOME.pages.dev` — deve aparecer a tela da Cloudflare pedindo o e-mail. Tente abrir direto `https://NOME.pages.dev/data.json` e `https://NOME.pages.dev/raw.json` — deve pedir login (nunca mostrar os dados).
- **No celular:** abra `https://NOME.pages.dev`, digite o e-mail liberado, abra o e-mail, digite o código de 6 dígitos. Depois me diga: abriu? quanto tempo demorou? o menu e as tabelas ficaram legíveis?

## Se algo der errado
- **Tela "Acesso ainda não configurado"** → falta (ou está errada) uma das duas variáveis da etapa 8, ou você não publicou de novo depois de criá-las.
- **Tela "Acesso negado"** logo depois de logar → o `POLICY_AUD` não é o do aplicativo certo, ou o `TEAM_DOMAIN` está com barra no final / endereço errado.
- **O código não chega** → o e-mail não está na lista da etapa 7 (por segurança a Cloudflare nem envia), ou caiu no spam.
- **Para tirar alguém do acesso**: apague o e-mail da lista (etapa 7) e, se quiser derrubar sessões abertas, em Zero Trust → Access → Applications → o aplicativo → revogue as sessões.
