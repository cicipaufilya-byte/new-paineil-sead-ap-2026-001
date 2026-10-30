"""Serviço de e-mail transacional (Emergent managed email / Resend).

Dois gatilhos:
  - inscrição realizada  -> build_inscricao_email_html
  - pagamento PIX gerado -> build_pix_email_html

Os destinatários vêm SEMPRE de registros do servidor (e-mail que o próprio
candidato informou na inscrição) e os corpos de e-mail de templates fixos
no servidor. Nunca aceite HTML/recipiente vindo do cliente (G4).
"""
import os
import re
import ipaddress
import logging
import httpx
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Proxy gerenciado da Emergent. É uma CONSTANTE — nunca ler do os.environ.
EMAIL_BASE_URL = "https://integrations.emergentagent.com"
EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "SEAD/AP 2026 - IDCAP")
# BYOK Resend (conta própria do usuário). Se definido, usa Resend direto.
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
RESEND_FROM = os.environ.get("RESEND_FROM")  # ex: "SEAD/AP 2026 <no-reply@seudominio.com>"
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO")
APP_PUBLIC_URL = os.environ.get("APP_PUBLIC_URL", "").rstrip("/")
EMAIL_LOGO_URL = os.environ.get("EMAIL_LOGO_URL", "")

# Nome completo do concurso exibido no corpo do e-mail
CONCURSO_NOME = "SEAD/AP 2026 - IDCAP"
ORGAO = "Secretaria de Estado da Administração do Amapá"
ORGANIZADORA = "Organização: IDCAP"
EDITAL = "Edital nº 001/2026 · Organização: IDCAP"
PRAZO = "30/10/2026, às 23h59 (horário de Brasília)"

# ----------------------------------------------------------------------------
# Guardrail gate (copiado do playbook — chamar em todo envio)
# ----------------------------------------------------------------------------
_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} != real link host {real!r} (G3)")


# ----------------------------------------------------------------------------
# Envio (assíncrono / não bloqueante)
# ----------------------------------------------------------------------------
async def send_email(*, to: str, subject: str, html: str) -> str | None:
    _assert_safe_email(subject, html)
    # BYOK: conta Resend própria do usuário
    if RESEND_API_KEY and RESEND_FROM:
        body = {"from": RESEND_FROM, "to": [to], "subject": subject, "html": html}
        if EMAIL_REPLY_TO:
            body["reply_to"] = EMAIL_REPLY_TO
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json=body,
            )
        resp.raise_for_status()
        return resp.json().get("id")
    # Fallback: e-mail gerenciado pela Emergent
    payload = {"to": [to], "subject": subject, "html": html, "from_name": EMAIL_FROM_NAME}
    if EMAIL_REPLY_TO:
        payload["contact_email"] = EMAIL_REPLY_TO
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{EMAIL_BASE_URL}/api/v1/email/send",
            headers={"X-Email-Key": EMAIL_KEY},
            json=payload,
        )
    resp.raise_for_status()
    return resp.json().get("id")


async def try_send_email(*, to: str, subject: str, html: str) -> bool:
    """Envia sem quebrar o fluxo principal. Retorna True se enviou."""
    if not to or "@" not in to:
        return False
    if not ((RESEND_API_KEY and RESEND_FROM) or EMAIL_KEY):
        logger.info("[email] envio desativado: nenhum provedor configurado")
        return False
    try:
        await send_email(to=to, subject=subject, html=html)
        logger.info(f"[email] enviado: {subject!r} -> {to}")
        return True
    except httpx.HTTPStatusError as e:
        try:
            code = e.response.json().get("code", "")
            msg = e.response.json().get("message", "")
        except ValueError:
            code, msg = "", e.response.text
        logger.warning(f"[email] falha {e.response.status_code} {code}: {msg}")
        return False
    except Exception as e:
        logger.error(f"[email] erro: {e}")
        return False


# ----------------------------------------------------------------------------
# Templates (HTML inline, layout em tabela)
# ----------------------------------------------------------------------------
def _fmt_valor(valor) -> str:
    try:
        v = float(valor or 0)
    except Exception:
        v = 0.0
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _safe_base(*urls: str) -> str:
    for u in urls:
        u = (u or "").strip().rstrip("/")
        if u.lower().startswith("https://") and _host_ok(urlparse(u.lower()).hostname or ""):
            return u
    return ""


def _hoje() -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(hours=3)).strftime('%d/%m/%Y')


def _shell(inner: str, base: str = "") -> str:
    base = _safe_base(APP_PUBLIC_URL, base)
    logo_url = _safe_base(EMAIL_LOGO_URL) or (f"{base}/idcap/email-logo-idcap.png" if base else "")
    logo = (
        f'<img src="{escape(logo_url)}" width="135" alt="IDCAP" '
        'style="display:block;margin:0 auto 16px;width:160px;max-width:100%;height:auto;border:0;outline:none;text-decoration:none" />'
        if logo_url else ""
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#f5f5f5;padding:28px 0;font-family:Arial,Helvetica,sans-serif">'
        '<tr><td align="center">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:600px;width:100%;background:#ffffff;border:1px solid #e0e0e0;border-radius:6px;overflow:hidden">'
        '<tr><td style="height:6px;background:#1b3c82;font-size:0;line-height:0">&nbsp;</td></tr>'
        '<tr><td align="center" style="padding:28px 28px 20px;border-bottom:1px solid #e5e5e5;background:#ffffff">'
        f'{logo}'
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:22px;font-weight:bold;color:#1b3c82;line-height:1.3">SEAD/AP 2026</div>'
        f'<div style="font-size:13px;color:#33475b;margin-top:4px">{escape(ORGAO)}</div>'
        f'<div style="font-size:12px;color:#7a869a;margin-top:6px">{escape(EDITAL)}</div>'
        '</td></tr>'
        f'<tr><td style="padding:30px 32px">{inner}</td></tr>'
        '<tr><td style="padding:18px 32px;border-top:1px solid #eeeeee;background:#fafafa">'
        '<p style="margin:0;font-size:11px;color:#7d8b82;line-height:1.6">'
        f'Enviado por {escape(CONCURSO_NOME)}. Este é um e-mail automático de confirmação; não é necessário respondê-lo. '
        'Por segurança, nunca solicitamos senha, código ou dados de cartão por e-mail.'
        '</p></td></tr>'
        '<tr><td style="height:6px;background:#1b3c82;font-size:0;line-height:0">&nbsp;</td></tr>'
        '</table></td></tr></table>'
    )


def _button(label: str, href: str) -> str:
    if not href:
        return ""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px 0 6px">'
        f'<tr><td style="border-radius:4px;background:#1b3c82">'
        f'<a href="{escape(href)}" style="display:inline-block;padding:14px 32px;font-size:15px;'
        'font-weight:bold;color:#ffffff;text-decoration:none;font-family:Arial,Helvetica,sans-serif">'
        f'{escape(label)}</a>'
        '</td></tr></table>'
    )


def _row(label: str, value: str) -> str:
    return (
        '<tr>'
        f'<td style="padding:9px 0;font-size:13px;color:#111;font-weight:bold;white-space:nowrap;vertical-align:top">{escape(label)}</td>'
        f'<td style="padding:9px 0 9px 12px;font-size:14px;color:#2b3a30;vertical-align:top">{escape(value)}</td>'
        '</tr>'
    )


def build_inscricao_email_html(*, nome: str, cpf: str, protocolo: str, cargo: str,
                               concurso: str, valor, base_url: str = "", lembrete_prazo: str = "") -> str:
    base = _safe_base(APP_PUBLIC_URL, base_url)
    pagamento_url = f"{base}/pagamento-pix.html" if base else ""
    cargo = re.sub(r"^\s*\d+\s*-\s*", "", re.sub(r"\s*-\s*R\$\s*[\d.,]+\s*$", "", cargo or "")).strip()
    rows = _row("Número da inscrição:", protocolo or "-")
    rows += _row("Nome:", nome or "-")
    _c = re.sub(r"\D", "", cpf or "")
    rows += _row("CPF:", f"{_c[:3]}.{_c[3:6]}.{_c[6:9]}-{_c[9:]}" if len(_c) == 11 else (cpf or "-"))
    if cargo:
        rows += _row("Cargo:", cargo)
    rows += _row("Concurso:", f"{ORGAO} - Edital nº 001/2026" + (" (Analista)" if "ANALISTA" in cargo.upper() else " (Assistente Administrativo)"))
    rows += _row("Valor da inscrição:", _fmt_valor(valor))
    primeiro = escape(nome.split()[0].capitalize()) if (nome or "").strip() else "candidato(a)"
    inner = (
        f'<p style="margin:0 0 14px;font-size:17px;color:#111">Olá, {primeiro}!</p>'
        + ('<p style="margin:0 0 18px;font-size:14px;color:#2b3a30;line-height:1.6">'
           + ('Sua inscrição está <strong>pendente de pagamento</strong> e o prazo termina <strong>hoje</strong>. Veja o resumo abaixo:' if lembrete_prazo.startswith(_hoje()) else 'Sua inscrição está <strong>pendente de pagamento</strong>. Veja o resumo abaixo:')
           + '</p>' if lembrete_prazo else
           '<p style="margin:0 0 18px;font-size:14px;color:#2b3a30;line-height:1.6">'
           'Sua <strong>inscrição foi realizada com sucesso</strong>. Veja o resumo abaixo:'
           '</p>') +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="border:1px solid #e5e5e5;border-radius:6px;padding:8px 18px;background:#fafafa">'
        f'{rows}</table>'
        '<p style="margin:20px 0 0;font-size:14px;color:#2b3a30;line-height:1.6">'
        f'Sua inscrição está <strong>pendente</strong>, para confirmar, realize o pagamento da taxa até dia <strong>{escape(lembrete_prazo or PRAZO)}</strong>.'
        '</p>'
        f'{_button("Pagar inscrição", (pagamento_url + "?cpf=" + re.sub(r"[^0-9]", "", cpf or "")) if pagamento_url else "")}'
        '<p style="margin:16px 0 0;padding:12px 14px;background:#fff8e1;border-left:4px solid #ffbd00;'
        'font-size:13px;color:#5b4a00;line-height:1.5">'
        'As inscrições e o pagamento da taxa encerram-se em <strong>30/10/2026, às 23h59</strong> (horário de Brasília). '
        'A inscrição só é confirmada após o pagamento.'
        '</p>'
    )
    return _shell(inner, base)


def build_pix_email_html(*, nome: str, cpf: str, cargo: str, valor, pix_code: str) -> str:
    rows = _row("Nome:", nome or "-")
    _c = re.sub(r"\D", "", cpf or "")
    rows += _row("CPF:", f"{_c[:3]}.{_c[3:6]}.{_c[6:9]}-{_c[9:]}" if len(_c) == 11 else (cpf or "-"))
    if cargo:
        rows += _row("Cargo:", cargo)
    rows += _row("Valor:", _fmt_valor(valor))
    inner = (
        f'<p style="margin:0 0 14px;font-size:16px;color:#111">Olá, {escape((nome or "candidato(a)").split()[0] if nome else "candidato(a)")}!</p>'
        '<p style="margin:0 0 18px;font-size:14px;color:#2b3a4d;line-height:1.6">'
        'Aqui está o <strong>pagamento PIX</strong> da sua inscrição. Resumo:'
        '</p>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="border:1px solid #e6eaf1;border-radius:8px;padding:6px 16px">'
        f'{rows}</table>'
        '<p style="margin:20px 0 8px;font-size:13px;color:#111;font-weight:bold">PIX copia e cola:</p>'
        '<div style="background:#f4f7fb;border:1px dashed #9fb3cc;border-radius:8px;padding:14px;'
        'font-family:Consolas,monospace;font-size:13px;color:#174d87;word-break:break-all;line-height:1.5;'
        '-webkit-user-select:all;user-select:all">'
        f'{escape(pix_code)}'
        '</div>'
        '<p style="margin:10px 0 0;font-size:12px;color:#8a96a8;line-height:1.5">'
        'Toque e segure (celular) ou clique e selecione (computador) o código acima para copiar '
        'e cole no app do seu banco, na opção PIX &gt; Copia e Cola.'
        '</p>'
    )
    return _shell(inner)


def _fmt_data(d: str) -> str:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", d or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else (d or "-")


def build_cadastro_email_html(*, nome: str, cpf: str, nascimento: str, email: str,
                              cidade: str, base_url: str = "", sessao: str = "") -> str:
    base = _safe_base(APP_PUBLIC_URL, base_url)
    finalizar = f"{base}/dados-inscricao.html?sessao={sessao}" if base and sessao else ""
    logo_url = _safe_base(EMAIL_LOGO_URL) or (f"{base}/idcap/email-logo-idcap.png" if base else "")
    logo = (f'<img src="{escape(logo_url)}" width="250" alt="IDCAP" style="display:block;margin:0 auto;width:250px;max-width:80%;height:auto;border:0" />'
            if logo_url else '<div style="font-size:32px;font-weight:bold;color:#1b3c82">IDCAP</div>')
    p = 'margin:0 0 18px;font-size:16px;color:#2b3a4a;line-height:1.5'
    s = 'margin:0 0 18px;font-size:15px;color:#333;line-height:1.7;text-align:justify'
    hl = ('margin:0 0 22px;font-size:20px;font-weight:bold;color:#ff0000;line-height:1.6;text-decoration:underline;'
          'text-align:justify')
    mark = 'background:#ffff00'
    nome_e = escape(nome or "-")
    inner = (
        f'<p style="{p}">Prezado(a) <strong>{nome_e}</strong>,</p>'
        f'<p style="{p}">Seu CADASTRO foi recebido com sucesso.</p>'
        f'<p style="margin:0 0 18px;font-size:15px;color:#2b3a4a">Nome: <strong>{nome_e}</strong></p>'
        f'<p style="{p}">CPF: <strong>{escape(re.sub(r"[^0-9]", "", cpf or "") or "-")}</strong></p>'
        f'<p style="{p}">Data de Nascimento: <strong>{escape(_fmt_data(nascimento))}</strong></p>'
        f'<p style="{p}">E-mail: <strong><a href="mailto:{escape(email)}" style="color:#1155cc">{escape(email)}</a></strong></p>'
        f'<p style="{p}">Cidade: <strong>{escape(cidade or "-")}</strong></p>'
        f'<p style="{hl}"><span style="{mark}">O cadastro no site não é inscrição! Para se inscrever no concurso público/processo seletivo pretendido, o candidato deve seguir o passo a passo abaixo:</span></p>'
        f'<p style="{s}"><strong>a)</strong> Acessar o site oficial e localizar a área destinada ao concurso público/processo seletivo pretendido, acessando a página específica do concurso público/processo seletivo;</p>'
        f'<p style="{s}"><strong>b)</strong> Ler e estar de acordo com as normas do edital;</p>'
        f'<p style="{s}"><strong>c)</strong> Clicar em "inscrição online", conforme ilustração a seguir;</p>'
        f'<p style="{s}"><strong>d)</strong> Preencher total e corretamente a Ficha de Inscrição e, em seguida, enviá-la de acordo com as respectivas instruções;</p>'
        f'<p style="{s}"><strong>e)</strong> Após o envio online da ficha de inscrição, automaticamente será gerado o documento de pagamento do valor de inscrição, que deverá ser pago em qualquer agência bancária ou por meio eletrônico, sendo de inteira responsabilidade do candidato a impressão e guarda do comprovante de pagamento e do cartão de confirmação de inscrição.</p>'
        f'<p style="{hl};margin:0"><span style="{mark}">O processamento do pagamento pode levar até 3 dias ÚTEIS, mesmo sendo realizado via PIX.</span></p>'
        + (f'<table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:30px auto 0"><tr><td style="border-radius:6px;background:#1b3c82">'
           f'<a href="{escape(finalizar)}" style="display:inline-block;padding:15px 38px;font-size:16px;font-weight:bold;color:#ffffff;text-decoration:none;font-family:Arial,Helvetica,sans-serif">Finalizar a inscrição</a>'
           '</td></tr></table>' if finalizar else '')
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#eef2f5;padding:36px 0;font-family:Arial,Helvetica,sans-serif"><tr><td align="center">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:4px">'
        f'<tr><td align="center" style="padding:40px 28px 40px;border-bottom:1px solid #e8ecef">{logo}</td></tr>'
        f'<tr><td style="padding:44px 40px 36px">{inner}</td></tr>'
        '</table>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">'
        '<tr><td align="center" style="padding:28px 24px 8px;font-size:13px;color:#444;line-height:1.6">'
        'Esta mensagem foi enviada de um endereço de e-mail exclusivo para notificações que não recebe e-mails. Portanto <strong>NÃO</strong> responda a esta mensagem.'
        '<br><br>Enviado por <strong>Instituto IDCAP.</strong></td></tr></table>'
        '</td></tr></table>'
    )
