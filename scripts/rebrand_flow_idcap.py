import re

PUB = '/app/frontend/public/'
PAGES = ['inscricao.html', 'dados-inscricao.html', 'confirmacao.html', 'inscricao-realizada.html',
         'pagamento-pix.html', 'minhas-inscricoes.html', 'seduc/finalizar.js']

R = [
    ('Concurso Público SEFAZ/AL 2026 - Secretaria de Estado da Fazenda de Alagoas | Cebraspe',
     'Concurso Público SEAD/AP 001/2026 - Secretaria de Estado da Administração do Amapá | IDCAP'),
    ('SEFAZ/AL, concurso público, Auditor Fiscal, Cebraspe, 2026',
     'SEAD/AP, concurso público, Assistente Administrativo, IDCAP, 2026'),
    (' - SEFAZ/AL 2026 | Cebraspe', ' - SEAD/AP 2026 | IDCAP'),
    ('SEFAZ/AL 2026 - Edital nº 1', 'SEAD/AP 2026 - Edital nº 001/2026'),
    ('Secretaria de Estado da Fazenda de Alagoas - Edital nº 1',
     'Secretaria de Estado da Administração do Amapá - Edital nº 001/2026'),
    ('Edital nº 1 – SEFAZ/AL', 'Edital nº 001/2026 – SEAD/AP'),
    ('Secretaria de Estado da Fazenda de Alagoas', 'Secretaria de Estado da Administração do Amapá'),
    ('Cebraspe — Centro Brasileiro de Pesquisa em Avaliação e Seleção e de Promoção de Eventos',
     'IDCAP — Instituto de Desenvolvimento e Capacitação'),
    ('© CEBRASPE — SEFAZ/AL 2026', '© IDCAP — SEAD/AP 2026'),
    ('SEFAZ/AL 2026 - Cebraspe', 'SEAD/AP 2026 - IDCAP'),
    ('SEFAZ_AL_26', 'SEAD_AP_26'),
    ('SEFAZ/AL 2026', 'SEAD/AP 2026'),
    ('SEFAZ/AL', 'SEAD/AP'),
    ('Auditor Fiscal da Administração Tributária Estadual (AFTE)', 'Assistente Administrativo'),
    ('O Cebraspe atende', 'O IDCAP atende'),
    ('Sites Cebraspe', 'Sites IDCAP'),
    ('<span>CEBRASPE</span>', '<span>IDCAP</span>'),
    ('alt="Cebraspe"', 'alt="IDCAP"'),
    ('content="Cebraspe"', 'content="IDCAP"'),
    ('sac@cebraspe.org.br', 'atendimento@idcap.org.br'),
    ('17/09/2026', '08/10/2026'),
    ('21/10/2026', '30/10/2026'),
    ('data-price="300.00"', 'data-price="90.00"'),
    ('var __v = 300;', 'var __v = 90;'),
    ('storedValor = 300;', 'storedValor = 90;'),
    ('valor: d.__valor || 300', 'valor: d.__valor || 90'),
    ('<input type="hidden" id="UF_PROVA" name="UF_PROVA" value="AL">',
     '<input type="hidden" id="UF_PROVA" name="UF_PROVA" value="AP">'),
    ('<option value="MACEIO/AL" data-uf="AL" selected="">MACEIÓ/AL</option>',
     '<option value="" selected="">Selecione</option>\n<option value="MACAPA/AP" data-uf="AP">MACAPÁ/AP</option>\n<option value="SANTANA/AP" data-uf="AP">SANTANA/AP</option>'),
    ("function syncUf(){ if(mp) mp.value = 'MACEIO/AL'; if(uf) uf.value = 'AL'; }",
     "function syncUf(){ if(uf) uf.value = 'AP'; }"),
    ("{'MACEIO/AL':'MACEIÓ/AL'}", "{'MACAPA/AP':'MACAPÁ/AP','SANTANA/AP':'SANTANA/AP'}"),
    ("{'AL':'Alagoas',", "{'AP':'Amapá',"),
    ("  mark('c-negros', !!d.cotas_negros);\n", ''),
]

NEGRAS_FS = re.compile(r'<fieldset>\s*<label style="text-align:left">\s*<strong>É optante pela reserva de vagas prevista no Edital[^<]*pessoas negras:</strong>.*?</fieldset>\s*', re.S)
NEGRAS_P = re.compile(r'<p style="margin:22px 0 6px 0;">É optante pela reserva de vagas prevista no Edital[^<]*pessoas negras\? <span data-testid="c-negros" id="c-negros" style="float:right;">—</span></p>\s*')

for p in PAGES:
    path = PUB + p
    s = open(path, encoding='utf-8').read()
    o = s
    s = NEGRAS_FS.sub('', s)
    s, n = NEGRAS_P.subn('', s)
    if n:
        s = s.replace('<p style="margin:6px 0;">É optante pela reserva de vagas prevista no Edital nº 1',
                      '<p style="margin:22px 0 6px 0;">É optante pela reserva de vagas prevista no Edital nº 1', 1)
    for a, b in R:
        s = s.replace(a, b)
    if s != o:
        open(path, 'w', encoding='utf-8').write(s)
    left = re.findall(r'SEFAZ|Cebraspe|CEBRASPE|Alagoas|MACEI|Auditor', re.sub(r'data:[^"\')\s]{60,}', '', s))
    print(p, 'changed' if s != o else 'same', 'left:', len(left), sorted(set(left)))
