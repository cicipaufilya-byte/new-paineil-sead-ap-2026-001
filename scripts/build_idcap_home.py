import base64
import hashlib
import io
import os
import re

from PIL import Image

PUB = '/app/frontend/public/'
CARGO_SRC = '/app/memory/idcap/source.html'
HOME_SRC = '/app/memory/idcap/home_source.html'

STYLE = '''
<style>
a[href="#"]{cursor:default}
.site__header .header__btn{min-width:44px;justify-content:center}
@media (max-width:767px){input[name=busca]{font-size:16px!important}}
.footer__copyright,.footer__copyright p,.footer__copyright a{color:#c9d8ff!important}
@media (min-width:992px) and (max-width:1199px){.site__header .container-fluid{padding:0 16px!important}.site__header .header__logo img{height:52px!important}.site__header .header__menu{padding:0 10px!important}.site__header .header__menu>ul{gap:14px!important}.site__header .header__menu>ul>li>a{font-size:12px!important}.site__header .header__panel .default__btn{font-size:12px!important;padding-left:14px!important;padding-right:14px!important;white-space:nowrap}}
.menu-on .header__toggle{opacity:1!important;visibility:visible!important}
.menu-on .header__toggle .toggle__content{margin:0!important}
#home-loader{position:fixed;inset:0;z-index:2147483647;background:rgba(255,255,255,.94);display:none;flex-direction:column;align-items:center;justify-content:center;gap:16px}
#home-loader.on{display:flex}
#home-loader .spin{width:52px;height:52px;border:5px solid #e8e8e8;border-top-color:#3576fb;border-radius:50%;animation:hlspin .8s linear infinite}
#home-loader p{margin:0;font-size:16px;color:#253654;font-weight:600;letter-spacing:.3px}
@keyframes hlspin{to{transform:rotate(360deg)}}
</style>
<div id=home-loader aria-hidden=true data-testid=home-loader><div class=spin></div><p>Carregando...</p></div>
'''

NAV_JS = '''
<script>
(function(){
  var root = document.documentElement, loader = document.getElementById('home-loader');
  function setMenu(on){ root.classList.toggle('menu-on', on); }
  function go(url){ setMenu(false); loader.classList.add('on'); setTimeout(function(){ window.location.href = url; }, 1200); }
  function bind(sel, url){ document.querySelectorAll(sel).forEach(function(a){ a.addEventListener('click', function(e){ e.preventDefault(); e.stopPropagation(); go(url || a.getAttribute('href')); }); }); }
  bind('#btn-inscreva-se, .js-inscricao', '/termos.html');
  bind('a.home-menu-link', '/');
  bind('a.js-nav');
  bind('a[href="/minhas-inscricoes.html"]', '/minhas-inscricoes.html');
  document.querySelectorAll('a[href="#"]').forEach(function(a){ a.addEventListener('click', function(e){ e.preventDefault(); }); });
  document.querySelectorAll('form').forEach(function(f){ f.addEventListener('submit', function(e){ e.preventDefault(); }); });
  var acts = document.querySelectorAll('a.js-action');
  if (acts[0]) acts[0].addEventListener('click', function(){ history.back(); });
  if (acts[1]) acts[1].addEventListener('click', function(){ window.print(); });
  var top = document.getElementById('back-to-top-link');
  if (top) top.addEventListener('click', function(){ window.scrollTo({top:0, behavior:'smooth'}); });
  document.getElementById('menu-toggle').addEventListener('click', function(){ setMenu(!root.classList.contains('menu-on')); });
  document.querySelector('.header__toggle').addEventListener('click', function(e){ if (e.target === this) setMenu(false); });
  document.addEventListener('keydown', function(e){ if(e.key === 'Escape') setMenu(false); });
  window.addEventListener('pageshow', function(ev){ if (ev.persisted) loader.classList.remove('on'); });
})();
</script>
'''

TRACK_JS = '''
<script>
(function(){
  try {
    var v = localStorage.getItem('visitor_id');
    if(!v){ v = 'v_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2,10); localStorage.setItem('visitor_id', v); }
    fetch('/api/track/access', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ page: window.location.pathname, user_agent: navigator.userAgent, extra: { visitor_id: v } })
    }).catch(function(){});
  } catch(e) {}
})();
</script>
'''

MODAL = '''
<style>
dialog#aviso-modal::backdrop{background:rgba(10,20,40,.55);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px)}
dialog#aviso-modal{border:0;padding:0;max-width:520px;width:calc(100% - 40px);background:transparent;overflow:visible}
dialog#aviso-modal[open]{animation:avpop .28s cubic-bezier(.2,.8,.25,1)}
@keyframes avpop{from{transform:translateY(14px) scale(.97);opacity:0}to{transform:none;opacity:1}}
#aviso-modal .av-card{background:#fff;border-radius:22px;box-shadow:0 24px 70px rgba(0,0,0,.35);padding:38px 34px 34px;text-align:center}
#aviso-modal img.av-logo{display:block;margin:0 auto 20px;height:48px;width:auto}
#aviso-modal h2{margin:0 0 16px;font-size:28px;font-weight:800;color:#1d3a6e;font-family:Arial,Helvetica,sans-serif}
#aviso-modal p{margin:0 0 28px;font-size:16px;line-height:1.6;color:#30415a;font-family:Arial,Helvetica,sans-serif}
#aviso-modal .av-btn{appearance:none;border:0;cursor:pointer;background:#3576fb;color:#fff;font-size:17px;font-weight:700;font-family:Arial,Helvetica,sans-serif;padding:14px 40px;border-radius:999px;transition:background .15s,transform .15s}
#aviso-modal .av-btn:hover{background:#1f5ad6;transform:translateY(-1px)}
@media(max-width:480px){#aviso-modal .av-card{padding:30px 22px 26px}#aviso-modal h2{font-size:23px}#aviso-modal p{font-size:15px}}
</style>
<dialog id="aviso-modal" aria-labelledby="aviso-modal-title" data-testid="aviso-importante-modal">
  <div class="av-card">
    <img class="av-logo" src="__LOGO__" alt="Instituto IDCAP" />
    <h2 id="aviso-modal-title">Aviso importante</h2>
    <p>As inscrições para o Concurso Público 001/2026 da Secretaria de Estado da Administração do Amapá (SEAD) encerram-se no dia <strong>30/10/2026</strong>, às <strong>23h59</strong> (horário de Brasília).</p>
    <button type="button" class="av-btn" id="aviso-modal-ok" data-testid="aviso-importante-ok">OK, entendi</button>
  </div>
</dialog>
<script>
(function(){
  var KEY='idcap_aviso_modal_shown';
  try{ if(sessionStorage.getItem(KEY)==='1') return; }catch(e){}
  var dlg=document.getElementById('aviso-modal'), btn=document.getElementById('aviso-modal-ok');
  function mark(){ try{sessionStorage.setItem(KEY,'1');}catch(e){} }
  function close(){ mark(); if(dlg.open) dlg.close(); }
  btn.addEventListener('click', close);
  dlg.addEventListener('click', function(e){ if(e.target===dlg) close(); });
  setTimeout(function(){ mark(); if(typeof dlg.showModal==='function') dlg.showModal(); else dlg.setAttribute('open',''); }, 300);
})();
</script>
'''


def common(s):
    s = re.sub(r'<meta http-equiv=content-security-policy[^>]*>', '', s, flags=re.I)
    s = re.sub(r'<!--\s*Page saved with SingleFile.*?-->', '', s, flags=re.S)
    s = re.sub(r'\s*rel=canonical href=\S+?(?=>)', '', s)
    s = s.replace('<a href=https://idcap.selecao.net.br/painel/ class=default__btn>',
                  '<a href=/minhas-inscricoes.html class=default__btn data-testid=header-area-candidato-btn>')
    s = s.replace('<a href=https://idcap.selecao.net.br/painel/>',
                  '<a href=/minhas-inscricoes.html data-testid=footer-area-candidato-link>')
    s = s.replace('<a href=https://idcap.selecao.net.br/>', '<a href=/ class=home-menu-link>')
    s = s.replace('<a class=header__btn>', '<a class=header__btn id=menu-toggle data-testid=mobile-menu-toggle>')
    return s


def externalize(s):
    os.makedirs(PUB + 'idcap/img', exist_ok=True)

    def rep(m):
        mime, b64 = m.group(1), m.group(2)
        raw = base64.b64decode(b64)
        h = hashlib.md5(raw).hexdigest()[:12]
        if mime in ('image/png', 'image/jpeg', 'image/webp'):
            im = Image.open(io.BytesIO(raw))
            im.thumbnail((960, 960))
            name = f'idcap/img/{h}.webp'
            if not os.path.exists(PUB + name):
                im.save(PUB + name, 'WEBP', quality=88)
        else:
            name = f'idcap/img/{h}.{mime.split("/")[1].split("+")[0]}'
            if not os.path.exists(PUB + name):
                open(PUB + name, 'wb').write(raw)
        return '/' + name

    return re.sub(r'data:(image/(?:png|jpeg|webp|svg\+xml));base64,([A-Za-z0-9+/=]{40000,})', rep, s)


def finish(s, extra):
    s = externalize(s)
    s = re.sub(r'/\*!\s*\* Bootstrap.*?\*/', '', s, flags=re.S)
    s = re.sub(r'\s*target=_blank(?! rel=noopener)', '', s)
    s = re.sub(r'href="?https?://[^\s>"]+"?', 'href=#', s)
    s = re.sub(r'action=/index/todos/', 'action=#', s)
    s = re.sub(r'<div vw class=enabled>.*?</div>\s*</div>\s*</div>', '', s, flags=re.S)
    s = re.sub(r'<div id=vlibras-access-wrapper>.*?</template></div>', '', s, flags=re.S)
    logo = re.search(r'<div class=header__logo>\s*<a[^>]*>\s*<img src="(data:[^"]+)"', s).group(1)
    extra = extra.replace('__LOGO__', logo)
    i = s.rfind('</body>')
    return (s[:i] + extra + s[i:]) if i != -1 else (s + extra + '</body></html>')


def build_cargo(src, kind, concurso_id, pdf_dir, pdfs, title):
    s = common(open(src, encoding='utf-8').read())
    s = s.replace(f'<a href="https://idcap.selecao.net.br/login/sair/?redir=%2Ftermo%2F{concurso_id}%2F" class=information__btn>',
                  f'<a href=/termos.html?c={kind} id=btn-inscreva-se class=information__btn data-testid=home-fazer-inscricao-btn>')
    s = s.replace('<a href=#back-to-top>', '<a href=# id=back-to-top-link data-testid=back-to-top-link>')
    s = s.replace('<a href=javascript:void(0)>\n', '<a href=# class=js-action>\n')
    it = iter(pdfs)
    s = re.sub(r'href=https://anexos-r2\.selecao\.net\.br/\S+?\.pdf target=_blank',
               lambda m: (lambda n: f'href=/docs/{pdf_dir}/{n}.pdf target=_blank rel=noopener data-testid=pub-{n}')(next(it)), s)
    s = s.replace('<title>Instituto IDCAP</title>', f'<title>{title} - SEAD/AP 2026 | Instituto IDCAP</title>')
    cargo_css = ('<style>@media (max-width:767px){'
                 '.contest__information .information__logo{width:110px!important;height:110px!important;padding:8px!important;margin:0 auto!important;display:flex!important;align-items:center!important;justify-content:center!important}'
                 '.contest__information .information__logo img{max-width:100%!important;max-height:100%!important;width:auto!important;height:auto!important;margin:0 auto!important;object-fit:contain}'
                 '.contest__information .information__left{width:120px!important;margin:0 auto 18px!important;background:#fff!important}'
                 '.contest__information .information__label{font-size:12px!important;margin-bottom:6px!important}'
                 '.contest__information .information__title{font-size:18px!important;line-height:1.35!important;margin-bottom:12px!important}'
                 '.contest__information .information__info p{font-size:11px!important;letter-spacing:-.15px;white-space:nowrap;line-height:1.5!important;margin:0 0 6px!important}'
                 '.contest__information .information__info{margin-bottom:14px!important}'
                 '.contest__information .information__btn{padding:12px 26px!important;font-size:14px!important}'
                 '}</style>')
    return finish(s, STYLE + cargo_css + NAV_JS.replace("bind('#btn-inscreva-se, .js-inscricao', '/termos.html');", "bind('#btn-inscreva-se');"))


def build_home():
    s = common(open(HOME_SRC, encoding='utf-8').read())
    s = re.sub(r'<div class="col-xl-4 col-lg-6 col-md-6 col-12 pb-4">\s*<div class=list__item>\s*'
               r'<a href=https://idcap\.selecao\.net\.br/informacoes/(?:253|251)/>.*?</a>\s*</div>\s*</div>', '', s, flags=re.S)
    s = s.replace('<a href=https://idcap.selecao.net.br/informacoes/263/>',
                  '<a href=/assistente-administrativo.html class=js-nav data-testid=card-sead-assistente>')
    s = s.replace('<a href=https://idcap.selecao.net.br/informacoes/262/>',
                  '<a href=/analista.html class=js-nav data-testid=card-sead-analista>')
    s = s.replace('<div class="footer__status footer__item status__opened">Inscrições abertas</div>',
                  '<div class="footer__status footer__item status__opened" data-testid=card-inscreva-se>Inscreva-se</div>')
    home_css = ('<style>@media (max-width:767px){'
                '.home__contests .header__filter{display:none!important}'
                '.home__contests .contests__header{padding-top:0!important;margin:0!important;min-height:0!important}'
                '.home__contests .container.pt-5{padding-top:22px!important}'
                '.contests__list .list__item .item__logo{width:100px!important;height:100px!important;padding:8px!important;margin-bottom:4px!important}'
                '.contests__list .list__item .item__logo img{max-width:100%!important;max-height:100%!important}'
                '.contests__list .list__item .item__content{padding:10px 16px 14px!important}'
                '.contests__list .list__item .content__label{font-size:12px!important;margin-bottom:6px!important}'
                '.contests__list .list__item .content__title{font-size:16px!important;line-height:1.35!important;margin-bottom:10px!important}'
                '.contests__list .list__item .content__infos{font-size:12px!important;line-height:1.7!important;white-space:normal}'
                '.contests__list .list__item .item__footer .footer__item{padding-top:12px!important;padding-bottom:12px!important;min-height:0!important}'
                '.contests__list .list__item .item__footer .footer__job h4{font-size:22px!important}'
                '}</style>')
    return finish(s, STYLE + home_css + NAV_JS + TRACK_JS + MODAL)


PDFS_ASSIST = ['edital-abertura', 'anexo-i-cronograma', 'anexo-ii-atribuicao-cargo', 'anexo-iii-conteudo-programatico',
               'anexo-iv-declaracao-hipossuficiencia', 'resultado-impugnacoes', 'resultado-preliminar-isencao']
PDFS_ANAL = ['edital-abertura', 'anexo-i-cronograma', 'anexo-ii-atribuicao-cargos', 'anexo-iii-conteudo-programatico',
             'anexo-iv-declaracao-hipossuficiencia', 'resultado-impugnacoes', 'resultado-preliminar-isencao']
PAGES = [
    ('assistente-administrativo.html', build_cargo(CARGO_SRC, 'assistente', '263', 'idcap', PDFS_ASSIST, 'Assistente Administrativo')),
    ('analista.html', build_cargo('/app/memory/idcap/analista_source.html', 'analista', '262', 'idcap-analista', PDFS_ANAL, 'Analista')),
    ('inicio.html', build_home()),
]
for name, html in PAGES:
    open(PUB + name, 'w', encoding='utf-8').write(html)
    print(name, len(html), 'external hrefs left:', re.findall(r'href="?(https?://[^\s>"]+)', html),
          'track' if '/api/track/access' in html else 'no-track', 'modal' if 'aviso-modal' in html else 'no-modal')
