from pathlib import Path
import csv, json, re, hashlib
from decimal import Decimal as D, ROUND_HALF_UP
from html import escape
p=Path(__file__).parent
h=p/'ARK-X_成績表.html'
s=h.read_text()
original=s
source=(p/'source.csv').read_text().strip()+'\n'
rows=list(csv.DictReader(source.splitlines()))
daily={r['code'][:4]:r for r in csv.DictReader((p/'daily247.csv').open())}
assert len(rows)==10 and len({r['コード'] for r in rows})==10
assert sum(r['区分']=='買' for r in rows)==5
records=[]
for r in rows:
    code=r['コード']
    for a,b in [('10/8始値','open'),('高値','high'),('安値','low'),('終値','close')]:
        assert D(r[a])==D(daily[code][b]),(code,a)
    e=D(r['10/7終値(実測建値)'])
    buy=r['区分']=='買'
    stopped=D(r['採点%'])==D('-2.5')
    x=e*(D('.975') if buy else D('1.025')) if stopped else D(r['終値'])
    ret=(x-e)/e*(1 if buy else -1)
    records.append(dict(who='CEO-FAL',entryDate='2026-10-07',exitDate='2026-10-08',code=code,name=r['銘柄'],side='BUY' if buy else 'SELL',entry=str(e),exit=str(x),close=r['終値'],stopped=stopped,pnlPct=str(ret*100),pnlYen=str(ret*1000000),roundedScorePct=r['採点%'],costYen=None,netPnlYen=None,costStatus='費用未取得・未控除',status='参考損切り判定／正式照合待ち' if code=='6976' else 'FAL採点・日足照合済み',exitBasis='2.5%損切り理論値' if stopped else '終値',note='公開1分足09:00〜09:04欠落' if code=='6976' else r['判定メモ']))
sums={side:sum(D(r['pnlYen']) for r in records if r['side']==side) for side in ['BUY','SELL']}
total=sum(sums.values())
rounded=sum(D(r['roundedScorePct']) for r in records)*10000
assert rounded==27000
def yen(v):
    v=D(v).quantize(D(1),rounding=ROUND_HALF_UP)
    return ('+' if v>0 else '−' if v<0 else '')+f'{abs(v):,}円'
def price(v):
    return f'{D(v):,f}'.rstrip('0').rstrip('.') if '.' in f'{D(v):,f}' else f'{D(v):,f}'
def pc(v):return f'{D(v):+.4f}%'
def cls(v):return 'up' if D(v)>0 else 'down' if D(v)<0 else ''
key='CEO-FAL-20261007-20261008'
sha=hashlib.sha256(source.encode()).hexdigest()
if f'id="{key}" data-input-sha="{sha}"' in s:
    print(json.dumps({'status':'ALREADY_APPLIED','added_rows':0,'sourceTextSha256':sha}));raise SystemExit(0)
data=dict(key=key,sourceId='submitted-input',sourceTextSha256=sha,basePerRow=1000000,totalBase=10000000,rows=records,totals={k:str(v) for k,v in sums.items()},totalPnlYen=str(total),portfolioPct=str(total/100000),roundedScoreSumPoints='2.70',roundedScoreYen='27000',costStatus='unknown',originalEmbeddedRows=130)
block=f'''<!-- BEGIN {key} -->
<section class="card ceofal" id="{key}" data-input-sha="{sha}">
<h2>10/7建て → 10/8評価｜CEO参考・FAL採点</h2>
<p class="note">各100万円 × 買い5本・売り5本＝合計1000万円。費用前の紙上換算。</p>
<table class="simple cf-summary"><thead><tr><th>買い5本</th><th>売り5本</th><th>10本合計</th></tr></thead><tbody><tr>
<td class="num down"><b>{yen(sums['BUY'])}</b></td><td class="num up"><b>{yen(sums['SELL'])}</b></td><td class="num up"><b>{yen(total)}</b></td></tr></tbody></table>
<p><b>総資金1000万円比 {pc(total/100000)}</b> ｜ 太陽誘電の参考損切り −25,000円を含みます。</p>
<p class="note">9本の小計 {yen(total+25000)}。太陽誘電のみ正式照合待ち。費用控除後の損益は未確定です。</p>
<div class="scroll"><table class="simple cf-detail"><thead><tr><th>売買・銘柄</th><th>建値 → 適用決済値</th><th>100万円換算損益</th><th>判定・費用</th></tr></thead><tbody>'''
for side,label in [('BUY','買い'),('SELL','売り')]:
    for r in records:
        if r['side']!=side:continue
        block+=f'''<tr data-code="{r['code']}" class="cf-tr {'cf-buy' if side=='BUY' else 'cf-sell'}"><td class="l"><b>{label} {escape(r['name'])}</b><br>{r['code']}<br><span class="note">10/7 → 10/8</span></td><td class="num">{price(r['entry'])}円 → {price(r['exit'])}円<br><span class="note">{r['exitBasis']}</span></td><td class="num {cls(r['pnlYen'])}"><b>{yen(r['pnlYen'])}</b><br>{pc(r['pnlPct'])}</td><td class="l cf-status">{r['status']}<br><span class="note">{r['costStatus']}</span></td></tr>'''
block+='''</tbody></table></div>
<p class="note">損切り3本は採点ルールから算出した理論決済値で、実約定ではありません。手数料・金利・貸株料・逆日歩・滑りは未取得。単元株数へ丸めず100万円で換算しています。</p>
<details><summary>計算・出典・未確認事項</summary><p>買い＝(決済値−建値)÷建値×100万円。売り＝(建値−決済値)÷建値×100万円。内部では丸めず集計し、円表示で四捨五入。</p>
<p>丸め済み採点の合算は+2.70ポイント＝約+27,000円／総資金比+0.27%。建値・適用決済値からの再計算は+27,040.319899円／+0.270403198992%。両者は丸め方が異なります。</p>
<p>6976：09:00〜09:04の公開1分足が欠落。参考損切り判定を維持し、正式照合待ち。その他9本の採点は表示済み。CEO参考のためARK-V0・正式A〜Jの成績には合算しません。</p>
<p><a href="#">FAL元CSV</a> ／ <a href="#">10/8日足247銘柄</a> ／ <a href="#">6976参考分足の証拠</a></p>
</details></section>
'''
block+='<script type="application/json" id="ceofal-results-data">'+json.dumps(data,ensure_ascii=False)+'</script>\n<!-- END '+key+' -->'
style='''<style id="ceofal-style">
.ceofal{border:2px solid var(--accent);padding:14px;border-radius:10px;background:var(--panel);min-width:0}
.ceofal p{margin:0}.cf-summary{width:100%;table-layout:fixed}.cf-summary td,.cf-summary th{text-align:center!important;padding:9px 3px;white-space:normal}.cf-summary b{font-size:1.05rem}.cf-detail{width:100%}.cf-detail .cf-status{white-space:normal;min-width:170px}.cf-buy{background:var(--upbg)}.cf-sell{background:var(--downbg)}
@media(max-width:600px){.wrap{padding-inline:10px}.ceofal{padding:10px}.cf-summary b{font-size:.87rem}.cf-detail thead{display:none}.cf-detail,.cf-detail tbody{display:block}.cf-detail .cf-tr{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);border-top:2px solid var(--line)}.cf-detail td{display:block;border:none;text-align:left!important;white-space:normal;padding:8px;font-size:12px;overflow-wrap:anywhere}.cf-detail .cf-status{min-width:0}.cf-detail td:nth-child(2){text-align:right!important}.cf-detail td:nth-child(3){font-size:15px}.ceofal .scroll{overflow:visible}}
</style>'''
s=re.sub(r'<style id="ceofal-style">.*?</style>','',s,flags=re.S)
s=s.replace('</header>','</header>\n'+style,1)
pattern=r'<!-- BEGIN '+key+r' -->.*?<!-- END '+key+r' -->'
if re.search(pattern,s,flags=re.S):s=re.sub(pattern,lambda m:block,s,flags=re.S)
else:s=s.replace('<section class="card" id="visible-results">',block+'\n<section class="card" id="visible-results">',1)
assert re.search(r'const EMBEDDED=(.*);',s).group(1)==re.search(r'const EMBEDDED=(.*);',original).group(1)
assert s.count('data-code=')==10
h.write_text(s)
(p/'calculation.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
print(json.dumps({'rows':10,'total':str(total),'buy':str(sums['BUY']),'sell':str(sums['SELL']),'sourceTextSha256':sha,'historyPreserved':True},ensure_ascii=False))

