#!/usr/bin/env python3
"""
Gera o refresh token OAuth da API do Google Ads — rode isso UMA VEZ, na sua
máquina (nunca no GitHub Actions), depois de criar as credenciais OAuth
("App para computador") no Google Cloud Console.

Abre seu navegador padrão, você loga com a conta Google dona/vinculada ao
Google Ads e autoriza — o script captura o retorno localmente e imprime o
refresh token, que você cola no .env (GOOGLE_ADS_REFRESH_TOKEN) e, quando for
rodar em produção, também como Secret do GitHub.

Rodar:
    pip install -r requirements.txt
    python3 scripts/generate_refresh_token.py --client-id SEU_CLIENT_ID --client-secret SEU_CLIENT_SECRET

(ou defina GOOGLE_ADS_CLIENT_ID / GOOGLE_ADS_CLIENT_SECRET no ambiente/`.env`
e rode sem argumentos.)
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

SCOPES = ["https://www.googleapis.com/auth/adwords"]


def _load_dotenv():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() and key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip()


def main():
    _load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-id", default=os.environ.get("GOOGLE_ADS_CLIENT_ID"))
    parser.add_argument("--client-secret", default=os.environ.get("GOOGLE_ADS_CLIENT_SECRET"))
    args = parser.parse_args()

    if not args.client_id or not args.client_secret:
        sys.exit(
            "Faltou --client-id/--client-secret (ou GOOGLE_ADS_CLIENT_ID / "
            "GOOGLE_ADS_CLIENT_SECRET no .env) — pegue no Google Cloud "
            "Console, em APIs e Serviços > Credenciais, no cliente OAuth "
            "tipo 'App para computador'."
        )

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        sys.exit("Faltou instalar as dependências: pip install -r requirements.txt")

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": args.client_id,
                "client_secret": args.client_secret,
                "redirect_uris": ["http://localhost"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
    )
    print("Abrindo o navegador para você logar e autorizar... (se não abrir sozinho, copie o link que vai aparecer)")
    flow.run_local_server(port=0, prompt="consent")

    print("\nToken gerado com sucesso. Cole isto no seu .env:\n")
    print(f"GOOGLE_ADS_REFRESH_TOKEN={flow.credentials.refresh_token}")
    print(f"GOOGLE_ADS_CLIENT_ID={args.client_id}")
    print(f"GOOGLE_ADS_CLIENT_SECRET={args.client_secret}")
    print("\nFalta só GOOGLE_ADS_LOGIN_CUSTOMER_ID (o Customer ID da conta, sem hífen).")


if __name__ == "__main__":
    main()
