from pathlib import Path
import re
import json
import html
from collections import Counter

from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table,
    TableStyle, PageBreak, KeepInFrame, Flowable,
)
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/pdf/Pipewright_Business_Requirements_Document.pdf'
SOURCE = ROOT / 'docs/business-requirements.md'
INV = json.loads((ROOT / 'tmp/pdfs/inventory.json').read_text())
W, H = A4
M = 44
CW = W - 2*M
TOP = H - 59
BOTTOM = 49
CH = TOP - BOTTOM
INK = colors.HexColor('#203A3C')
TEAL = colors.HexColor('#156B68')
MUTED = colors.HexColor('#576B6D')
PALE = colors.HexColor('#EFF5F3')
LINE = colors.HexColor('#D7E1DF')
COPPER = colors.HexColor('#B76C44')

fontdir = Path('/System/Library/Fonts/Supplemental')
for name, filename in [('Body','Arial.ttf'),('Body-Bold','Arial Bold.ttf'),('Body-Italic','Arial Italic.ttf'),('Editorial','Georgia.ttf')]:
    pdfmetrics.registerFont(TTFont(name,str(fontdir / filename)))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='Body-Bold',italic='Body-Italic',boldItalic='Body-Bold')

ST = {
 'p': ParagraphStyle('p',fontName='Body',fontSize=9.8,leading=13.6,textColor=INK,spaceAfter=8),
 'h1': ParagraphStyle('h1',fontName='Body-Bold',fontSize=25,leading=29,textColor=INK,spaceAfter=15),
 'h2': ParagraphStyle('h2',fontName='Body-Bold',fontSize=12.1,leading=15.5,textColor=TEAL,spaceBefore=8,spaceAfter=7,keepWithNext=True),
 'h3': ParagraphStyle('h3',fontName='Body-Bold',fontSize=10.6,leading=14,textColor=TEAL,spaceBefore=7,spaceAfter=5,keepWithNext=True),
 'bullet': ParagraphStyle('bullet',fontName='Body',fontSize=9.8,leading=13.6,textColor=INK,leftIndent=10,firstLineIndent=-9,spaceAfter=7),
 'cell': ParagraphStyle('cell',fontName='Body',fontSize=8.65,leading=11.65,textColor=INK,spaceAfter=0,splitLongWords=True),
 'th': ParagraphStyle('th',fontName='Body-Bold',fontSize=8.6,leading=11,textColor=colors.white,spaceAfter=0),
 'tool': ParagraphStyle('tool',fontName='Body',fontSize=8.5,leading=11,textColor=INK,spaceAfter=0),
 'toolhead': ParagraphStyle('toolhead',fontName='Body-Bold',fontSize=11.5,leading=14,textColor=TEAL,spaceBefore=5,spaceAfter=5),
 'small': ParagraphStyle('small',fontName='Body',fontSize=8.3,leading=11.4,textColor=MUTED,spaceAfter=6),
 'kicker': ParagraphStyle('kicker',fontName='Body-Bold',fontSize=8,leading=10,textColor=COPPER,spaceAfter=8),
}

def norm(s):
    return s.replace('\u2013','-').replace('\u2014','-').replace('\u2011','-').replace('\u00a0',' ')

def rich(s):
    s = html.escape(norm(s))
    s = re.sub(r'`([^`]+)`',r'<font name="Body" size="8.3">\1</font>',s)
    s = re.sub(r'\*\*([^*]+)\*\*',r'<b>\1</b>',s)
    return s

def para(s,style='p'):
    return Paragraph(rich(s),ST[style])

def table(rows,widths=None):
    n=len(rows[0])
    if widths is None:
        if n==2:
            widths=[CW*0.285,CW*0.715]
        elif n==3:
            first=rows[0][0].strip().lower()
            widths=[CW*x for x in ((.11,.43,.46) if first in ('id','uat') else (.24,.34,.42))]
        else:
            widths=[CW/n]*n
    cells=[[para(x,'th' if i==0 else 'cell') for x in row] for i,row in enumerate(rows)]
    t=Table(cells,colWidths=widths,hAlign='LEFT',repeatRows=1)
    t.setStyle(TableStyle([
       ('BACKGROUND',(0,0),(-1,0),TEAL),
       ('VALIGN',(0,0),(-1,-1),'TOP'),
       ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
       ('TOPPADDING',(0,0),(-1,0),8),('BOTTOMPADDING',(0,0),(-1,0),8),
       ('TOPPADDING',(0,1),(-1,-1),7),('BOTTOMPADDING',(0,1),(-1,-1),7),
       ('ROWBACKGROUNDS',(0,1),(-1,-1),[PALE,colors.white]),
       ('LINEBELOW',(0,1),(-1,-1),0.35,LINE),
    ]))
    if rows[0][0] == 'Ref':
        t.setStyle(TableStyle([('TOPPADDING',(0,1),(-1,-1),5),('BOTTOMPADDING',(0,1),(-1,-1),5)]))
    t.spaceAfter=10
    return t

class Process(Flowable):
    def __init__(self):
        super().__init__();self.width=CW;self.height=59
    def draw(self):
        c=self.canv; labels=[('01','ADD DATA'),('02','PREPARE'),('03','VALIDATE'),('04','REVIEW'),('05','DELIVER'),('06','OPERATE')]
        gap=9; bw=(CW-gap*5)/6
        for i,(num,label) in enumerate(labels):
            x=i*(bw+gap)
            c.setFillColor(PALE);c.roundRect(x,10,bw,44,5,fill=1,stroke=0)
            c.setFillColor(COPPER);c.setFont('Body-Bold',8);c.drawString(x+8,40,num)
            c.setFillColor(TEAL);c.setFont('Body-Bold',7.6);c.drawString(x+8,22,label)
            if i<5:
                c.setStrokeColor(TEAL);c.setLineWidth(.7)
                c.line(x+bw+1,31,x+bw+gap-1,31)
                c.line(x+bw+gap-3,33,x+bw+gap-1,31);c.line(x+bw+gap-3,29,x+bw+gap-1,31)

def tools_block(categories):
    out=[]
    for category in categories:
        tools=sorted([t for t in INV['tools'] if t['category']==category],key=lambda t:t['title'])
        out.append(para(f'{category} / {len(tools)} tools','toolhead'))
        rows=[]
        for i in range(0,len(tools),2):
            cells=[]
            for t in tools[i:i+2]:
                cells.append(Paragraph('<b>'+html.escape(t['title'])+'</b><br/><font size="7.5" color="#576B6D">'+html.escape(t['name'])+'</font>',ST['tool']))
            if len(cells)==1: cells.append('')
            rows.append(cells)
        t=Table(rows,colWidths=[CW/2,CW/2],hAlign='LEFT')
        t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),1),('BOTTOMPADDING',(0,0),(-1,-1),1),('LINEBELOW',(0,0),(-1,-1),.3,LINE)]))
        out.append(t);out.append(Spacer(1,4))
    return out

TOOL_GROUPS={
 'TOOLS_A':['Text'],
 'TOOLS_B':['Date & time','Nested data'],
 'TOOLS_C':['Numeric','Type & conversion','Missing data','Columns'],
 'TOOLS_D':['Cleansing','Encoding & privacy','Validation','Rows'],
}

SECTIONS = [s.strip() for s in SOURCE.read_text().split('<!-- PAGE -->')]
TITLES=[re.search(r'^# (.+)',s,re.M).group(1) for s in SECTIONS]

def connector_block():
    cats={
       'saas':'Business SaaS','database':'Relational databases','nosql':'NoSQL / search / graph',
       'storage':'Object storage / transfer','warehouse':'Warehouses','timeseries':'Time series',
       'lakehouse':'Lakehouse / catalogues','api':'API protocols','file':'Local files',
    }
    rows=[['Registry category','Entries','Available','Tier 2','Tier 4']]
    for cat,label in cats.items():
        cs=[s for s in INV['connectors'] if s['category']==cat]
        rows.append([label,str(len(cs)),str(sum(s['available'] for s in cs)),str(sum(s['tier']==2 for s in cs)),str(sum(s['tier']==4 for s in cs))])
    rows.append(['Total','211','155','50','161'])
    return table(rows,[CW*.43,CW*.135,CW*.165,CW*.135,CW*.135])

def contents():
    rows=[['Reading path','Pages']]
    starts=[(3,9,'Business purpose, objectives, users and use cases'),(10,17,'Current functional requirements'),(18,20,'Data, non-functional requirements and readiness'),(21,31,'Roadmap and remaining feature backlog'),(32,35,'Acceptance, rollout, reconciliation and evidence'),(36,40,'Current tool inventory and connector readiness')]
    for a,b,title in starts: rows.append([title,f'{a}-{b}'])
    return table(rows,[CW*.83,CW*.17])

def parse_section(text):
    lines=text.splitlines();out=[];i=0
    while i<len(lines):
        line=lines[i].strip()
        if not line: i+=1;continue
        if line.startswith('{{'):
            token=line.strip('{}')
            if token in TOOL_GROUPS: out.extend(tools_block(TOOL_GROUPS[token]))
            elif token=='WORKFLOW':out.append(Process())
            elif token=='CONNECTORS':out.append(connector_block())
            elif token=='CONTENTS':out.append(para('Page reference','h2'));out.append(contents())
            i+=1;continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                cells=[s.strip() for s in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',c) for c in cells):rows.append(cells)
                i+=1
            out.append(table(rows));continue
        if line.startswith('# '):out.append(para(line[2:],'h1'))
        elif line.startswith('## '):out.append(para(line[3:],'h2'))
        elif line.startswith('### '):out.append(para(line[4:],'h3'))
        elif line.startswith('- '):out.append(para('• '+line[2:],'bullet'))
        elif re.match(r'^\d+\. ',line):out.append(para(line,'bullet'))
        else:
            combined=[line]
            while i+1<len(lines) and lines[i+1].strip() and not lines[i+1].startswith(('#','|','- ','{{')):
                i+=1;combined.append(lines[i].strip())
            out.append(para(' '.join(combined)))
        i+=1
    return out

def band(page):
    if page<=9:return 'BUSINESS CONTEXT'
    if page<=17:return 'CURRENT CAPABILITIES'
    if page<=20:return 'OPERATING REQUIREMENTS'
    if page<=31:return 'PLANNED AND DEFERRED SCOPE'
    if page<=35:return 'ACCEPTANCE AND EVIDENCE'
    return 'CAPABILITY INVENTORY'

def draw_cover(c):
    c.setFillColor(PALE);c.rect(0,0,W,H,fill=1,stroke=0)
    c.setFillColor(TEAL);c.rect(0,H-12,W,12,fill=1,stroke=0)
    c.setFillColor(INK);c.setFont('Body-Bold',12);c.drawString(M,H-74,'PIPEWRIGHT')
    c.setFillColor(COPPER);c.setFont('Body-Bold',8.5);c.drawString(M,H-109,'PRODUCT SCOPE  /  BUSINESS REQUIREMENTS')
    c.setFillColor(INK);c.setFont('Editorial',38)
    for i,s in enumerate(['Business','Requirements','Document']):c.drawString(M,H-184-i*47,s)
    c.setStrokeColor(TEAL);c.setLineWidth(2);c.line(M,H-320,M+78,H-320)
    p=Paragraph('From recurring data preparation to governed, repeatable workflows.',ParagraphStyle('cover',fontName='Body',fontSize=17,leading=23,textColor=TEAL))
    p.wrap(CW-55,100);p.drawOn(c,M,H-402)
    p=para('Purpose, target users, current capabilities, business acceptance and the full documented roadmap.','p')
    _,ph=p.wrap(CW-75,100);p.drawOn(c,M,H-459-ph)
    # A quiet process motif, made of editable vector shapes.
    y=212;labels=['CONNECT','PREPARE','TRUST','DELIVER']
    for i,label in enumerate(labels):
        x=M+i*126;c.setFillColor(colors.white);c.roundRect(x,y,112,49,5,fill=1,stroke=0)
        c.setFillColor(COPPER);c.setFont('Body-Bold',8);c.drawString(x+10,y+31,f'0{i+1}')
        c.setFillColor(TEAL);c.setFont('Body-Bold',8);c.drawString(x+10,y+13,label)
    c.setFillColor(INK);c.setFont('Body-Bold',10);c.drawString(M,148,'Version 1.0  |  23 September 2026')
    c.setFillColor(MUTED);c.setFont('Body',9);c.drawString(M,129,'Business review draft  /  Repository baseline 79eb302')
    p=para('For product sponsors, business users, data teams, governance reviewers and platform operators. Status is explicitly separated into available, partial, conditional, planned and candidate capabilities.','small')
    _,ph=p.wrap(CW,55);p.drawOn(c,M,80-ph)

def onpage(c,doc):
    page=doc.page
    c.saveState()
    title=TITLES[page-1]
    c.bookmarkPage(f'page-{page}')
    c.addOutlineEntry(title,f'page-{page}',level=0,closed=False)
    if page==1:draw_cover(c)
    else:
        c.setFillColor(TEAL);c.rect(M,H-36,23,3,fill=1,stroke=0)
        c.setFont('Body-Bold',7.3);c.drawString(M+31,H-36,'PIPEWRIGHT  /  BUSINESS REQUIREMENTS')
        c.setFillColor(MUTED);c.setFont('Body',7);c.drawRightString(W-M,H-36,band(page))
        c.setStrokeColor(LINE);c.setLineWidth(.5);c.line(M,38,W-M,38)
        c.setFillColor(MUTED);c.setFont('Body',7.3);c.drawString(M,25,'23 SEP 2026  •  V1.0  •  BUSINESS REVIEW DRAFT')
        c.drawRightString(W-M,25,f'{page:02d} / {len(SECTIONS):02d}')
    c.restoreState()

class Doc(BaseDocTemplate):
    def __init__(self,path):
        super().__init__(str(path),pagesize=A4,leftMargin=M,rightMargin=M,topMargin=H-TOP,bottomMargin=BOTTOM,title='Pipewright - Business Requirements Document',author='Pipewright',subject='Business requirements, users, current features and planned roadmap',creator='Pipewright document workflow')
        self.addPageTemplates(PageTemplate(id='normal',frames=[Frame(M,BOTTOM,CW,CH,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],onPage=onpage))

story=[Spacer(1,1),PageBreak()];fitted=[]
for i,section in enumerate(SECTIONS[1:],start=2):
    flows=parse_section(section)
    block=KeepInFrame(CW,CH-1,flows,mode='shrink',hAlign='LEFT',vAlign='TOP')
    fitted.append((i,block));story.append(block)
    if i<len(SECTIONS):story.append(PageBreak())
Doc(OUT).build(story)
scales=[{'page':p,'title':TITLES[p-1],'scale':round(getattr(b,'_scale',1),3)} for p,b in fitted]
(ROOT/'tmp/pdfs/layout.json').write_text(json.dumps(scales,indent=2))
print(json.dumps({'output':str(OUT),'pages':len(SECTIONS),'compressed_pages':[s for s in scales if s['scale']>1.01]},indent=2))
