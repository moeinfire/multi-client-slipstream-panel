#!/usr/bin/env python3
import os,re,sqlite3,subprocess,secrets,hmac,time,threading,shlex,pwd,socket,select,socketserver,ipaddress,shutil,concurrent.futures,ssl
from functools import wraps
from flask import Flask,request,redirect,session,render_template_string,flash,abort,jsonify
from markupsafe import escape

APP='/opt/slipstream-panel'; DB=APP+'/tunnels.db'
BIN=os.environ.get('SLIPSTREAM_BIN','/usr/local/bin/slipstream-client')
PMIN=int(os.environ.get('PORT_MIN','10800')); PMAX=int(os.environ.get('PORT_MAX','11999'))
PANEL_HOST=os.environ.get('PANEL_HOST','0.0.0.0'); PANEL_PORT=int(os.environ.get('PANEL_PORT','18080'))
PANEL_BASE_PATH=open('/etc/slipstream-panel/base-path').read().strip().rstrip('/') if os.path.exists('/etc/slipstream-panel/base-path') else ''
if PANEL_BASE_PATH and not re.fullmatch(r'/[A-Za-z0-9_-]{4,64}', PANEL_BASE_PATH): raise RuntimeError('Invalid panel base path')
LOCAL_HOST='127.0.0.1'; CHECK=10; COOLDOWN=300; ERROR_GRACE_SECONDS=30
LOGDIR='/var/log/slipstream-panel'
LOG_OFFSETS={}
SUSPECT_SINCE={}
LB_DEFAULT_PORT=20818
LB_QUARANTINE=300
LB_LOCK=threading.RLock()
LB_SERVER=None
LB_SERVER_PORT=None
LB_QUARANTINED={}
LB_RR_INDEX=0
DNS_SCAN_LOCK=threading.RLock()
DNS_SCAN_TEST_HOST='www.google.com'
DNS_SCAN_STATE={"running":False,"cancel":False,"domain":"","phase":"idle","workers":1,"ping_total":0,"ping_done":0,"latency_total":0,"latency_done":0,"ping_results":[],"latency_results":[],"started_at":None}
app=Flask(__name__); app.secret_key=open('/etc/slipstream-panel/secret.key').read().strip()
app.config['SESSION_COOKIE_PATH']=(PANEL_BASE_PATH or '/')

class PanelPathMiddleware:
    def __init__(self, wrapped, prefix): self.wrapped,self.prefix=wrapped,prefix
    def __call__(self, environ, start_response):
        if self.prefix:
            path=environ.get('PATH_INFO','')
            if path == self.prefix or path.startswith(self.prefix + '/'):
                environ['SCRIPT_NAME']=environ.get('SCRIPT_NAME','')+self.prefix
                environ['PATH_INFO']=path[len(self.prefix):] or '/'
            else:
                body=b'Not Found'
                start_response('404 Not Found',[('Content-Type','text/plain; charset=utf-8'),('Content-Length',str(len(body)))])
                return [body]
        return self.wrapped(environ,start_response)
app.wsgi_app=PanelPathMiddleware(app.wsgi_app,PANEL_BASE_PATH)

@app.after_request
def apply_panel_base_path(response):
    if PANEL_BASE_PATH:
        location=response.headers.get('Location')
        if location and location.startswith('/') and not location.startswith(PANEL_BASE_PATH+'/'):
            response.headers['Location']=PANEL_BASE_PATH+location
        if response.mimetype=='text/html':
            body=response.get_data()
            body=body.replace(b'="/', ('="'+PANEL_BASE_PATH+'/').encode())
            body=body.replace(b"('/", ("('"+PANEL_BASE_PATH+'/').encode())
            body=body.replace(b"(\"/", ('(\"'+PANEL_BASE_PATH+'/').encode())
            response.set_data(body)
    return response
PASSWORD=open('/etc/slipstream-panel/admin.password').read().strip()

HTML=r'''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Slipstream Manager</title><style>
:root{color-scheme:dark;--bg:#080f1e;--surface:#111d31;--surface2:#0c1729;--line:#263b59;--txt:#edf4ff;--muted:#9aacc7;--blue:#438cff;--cyan:#37d6d0;--green:#25c58b;--red:#ff667c;--amber:#ffc45c;--shadow:0 16px 42px rgba(0,0,0,.24)}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 8% 0%,rgba(48,116,210,.18),transparent 34%),radial-gradient(ellipse at 95% 8%,rgba(35,194,185,.10),transparent 30%),linear-gradient(145deg,#080f1e 0%,#0b1527 55%,#101b30 100%);color:var(--txt);font:15px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1380px;margin:0 auto;padding:30px 22px 54px}
.top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin:4px 0 22px}
.brand{font-size:26px;font-weight:850;letter-spacing:-.5px;display:flex;align-items:center;gap:11px}
.brand:before{content:"S";display:inline-grid;place-items:center;width:42px;height:42px;border-radius:13px;background:linear-gradient(140deg,#438cff,#27c8c5);box-shadow:0 8px 24px rgba(55,143,255,.3);color:#fff;font-size:23px}
.sub,.muted{color:var(--muted);font-size:13px}
.card{background:linear-gradient(145deg,rgba(19,32,53,.96),rgba(14,25,43,.96));border:1px solid rgba(105,142,190,.18);border-radius:18px;padding:22px;margin:16px 0;box-shadow:var(--shadow)}
.card h3{font-size:17px;margin:0 0 17px;display:flex;align-items:center;gap:9px}
.card h3:before{content:"";width:4px;height:19px;border-radius:4px;background:linear-gradient(var(--cyan),var(--blue))}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:20px 0}
.stat{position:relative;overflow:hidden;background:linear-gradient(145deg,#142640,#101c30);border:1px solid rgba(105,142,190,.2);padding:17px 19px;border-radius:16px;color:var(--muted);font-size:13px}
.stat:after{content:"";position:absolute;width:100px;height:100px;border-radius:50%;left:-34px;bottom:-55px;background:rgba(67,140,255,.08)}
.num{font-size:30px;font-weight:850;color:var(--txt);line-height:1.4;margin-top:5px;font-variant-numeric:tabular-nums}
.formgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
label{display:block;color:#b4c4da;font-size:13px;margin-bottom:7px;font-weight:650}
input,textarea{width:100%;background:#091426;color:var(--txt);border:1px solid #2b4263;border-radius:11px;padding:12px 13px;font:inherit;outline:none;transition:border .18s,box-shadow .18s}
input:focus,textarea:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(67,140,255,.14)}
textarea{min-height:78px;resize:vertical;direction:ltr;text-align:left;font-family:ui-monospace,Consolas,monospace}
button,.btn{border:1px solid transparent;border-radius:10px;padding:10px 15px;background:linear-gradient(135deg,#438cff,#3475dc);color:white;font-weight:750;cursor:pointer;text-decoration:none;font-size:13px;display:inline-flex;align-items:center;justify-content:center;gap:6px;transition:transform .16s,filter .16s,box-shadow .16s;box-shadow:0 5px 14px rgba(39,111,220,.16)}
button:hover,.btn:hover{filter:brightness(1.12);transform:translateY(-1px);box-shadow:0 8px 18px rgba(39,111,220,.24)}
button.gray{background:#263b58;border-color:#3a5274;box-shadow:none}
button.green{background:linear-gradient(135deg,#1b9c72,#147d62);box-shadow:0 5px 14px rgba(20,125,98,.16)}
button.danger{background:#592b3a;border-color:#804052;box-shadow:none}
.actions{display:flex;gap:7px;flex-wrap:wrap;align-items:center}
table{width:100%;border-collapse:separate;border-spacing:0;min-width:1050px}
th,td{text-align:right;padding:14px 12px;border-bottom:1px solid rgba(105,142,190,.14);font-size:13px;vertical-align:middle}
th{color:#9fb3cf;font-size:12px;font-weight:750;background:#0c192b;position:sticky;top:0}
th:first-child{border-radius:0 10px 0 0}th:last-child{border-radius:10px 0 0 0}
tbody tr{background:rgba(10,21,37,.35);transition:background .15s}
tbody tr:hover{background:rgba(47,91,145,.14)}
tbody tr:last-child td{border-bottom:0}
.tablewrap{overflow:auto;border:1px solid rgba(105,142,190,.16);border-radius:13px}
.flash{padding:12px 15px;background:rgba(45,105,170,.2);border:1px solid rgba(83,151,220,.28);border-radius:11px;margin:8px 0 14px;color:#dcecff}
.login{max-width:430px;margin:12vh auto}
.pill{display:inline-flex;align-items:center;gap:6px;padding:6px 11px;border-radius:30px;font-size:12px;font-weight:800;white-space:nowrap;border:1px solid transparent}
.up{color:#70e5b5;background:rgba(20,135,95,.17);border-color:rgba(37,197,139,.22)}
.down{color:#ff9cab;background:rgba(186,51,75,.17);border-color:rgba(255,102,124,.2)}
.wait{color:#ffd889;background:rgba(172,121,27,.18);border-color:rgba(255,196,92,.2)}
.hint{color:var(--muted);font-size:13px;line-height:1.9;background:rgba(6,16,30,.38);padding:12px 14px;border-radius:10px;border-right:3px solid #3c8de8}
.dnsform{min-width:210px;max-width:280px}
.dnsform textarea{min-height:65px}
.healthdetail{display:block;color:var(--muted);font-size:11px;margin-top:5px;max-width:210px;line-height:1.6}\n.traffic{font-variant-numeric:tabular-nums;white-space:nowrap;line-height:1.8}.traffic strong{color:#eaf3ff}.traffic .speed{color:#7ddbd2;font-size:11px}.trafficform{margin-top:5px}.trafficform button{padding:5px 8px;font-size:11px}
.timer{display:block;color:#ff9cab;font-size:19px;font-weight:850;direction:ltr;font-variant-numeric:tabular-nums;margin-top:4px}
.domain{font-weight:800;color:#eaf3ff;direction:ltr;display:inline-block}
.small{font-size:11px;color:var(--muted)}
code{color:#8dd8ff;background:rgba(40,112,170,.12);padding:2px 5px;border-radius:5px}
a.btn{background:#263b58;border-color:#3a5274;box-shadow:none}
@media(max-width:800px){.wrap{padding:18px 12px 36px}.grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.card{padding:16px;margin:12px 0}.brand{font-size:22px}.num{font-size:25px}}
@media(max-width:460px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.stat{padding:13px}.top .actions{width:100%;justify-content:flex-start}}
</style></head><body><div class="wrap">{% with ms=get_flashed_messages() %}{% for m in ms %}<div class="flash">{{m}}</div>{% endfor %}{% endwith %}{% if not logged %}<div class="card login"><div class="brand">Slipstream Manager</div><p class="muted">ورود به پنل مدیریت</p><form method="post" action="/login"><input type="hidden" name="csrf" value="{{csrf}}"><label>رمز عبور</label><input type="password" name="password" required autofocus><p><button style="width:100%">ورود</button></p></form></div>{% else %}
<div class="top"><div><div class="brand">Slipstream Manager</div><div class="sub">مدیریت دامنه‌ها، DNS چندگانه و پایش اتصال Slipstream از روی لاگ</div></div><div class="actions"><span class="pill">Ubuntu · systemd</span><a class="btn" href="/dns-scan">🔎 اسکن DNS</a><a class="btn" href="/logout">خروج</a></div></div>
<div class="grid"><div class="stat">کل تونل‌ها<div class="num">{{tunnels|length}}</div></div><div class="stat">متصل<div class="num" id="healthy">{{healthy}}</div></div><div class="stat">در انتظار اتصال مجدد<div class="num" id="cooling">{{cooling}}</div></div><div class="stat">محدوده پورت<div class="num">{{pmin}}–{{pmax}}</div></div></div>
<div class="card"><h3>🌐 مدیریت DNS کلی</h3><form method="post" action="/dns/global"><input type="hidden" name="csrf" value="{{csrf}}"><label>DNS Resolverهای عمومی (هر خط یک مورد، فرمت IP:PORT)</label><textarea name="resolvers" required>{{global_resolvers}}</textarea><div class="actions" style="margin-top:12px"><button class="gray" name="mode" value="save">ذخیره به‌عنوان DNS پیش‌فرض</button><button class="green" name="mode" value="apply" onclick="return confirm('DNSهای واردشده روی تمام تونل‌ها اعمال و تونل‌های فعال به‌ترتیب ری‌استارت می‌شوند. ادامه می‌دهید؟')">اعمال روی همه تونل‌ها</button></div></form><div class="hint" style="margin-top:12px">ذخیره پیش‌فرض فقط روی دامنه‌هایی که از این به بعد اضافه می‌کنی اثر دارد. «اعمال روی همه» DNS تمام تونل‌های فعلی را جایگزین می‌کند و تونل‌های فعال را یکی‌یکی ری‌استارت می‌کند. برای تنظیم متفاوت هر تونل، از بخش ویرایش DNS همان ردیف استفاده کن.</div></div>
<div class="card"><h3>＋ افزودن دامنه</h3><form method="post" action="/add"><input type="hidden" name="csrf" value="{{csrf}}"><div class="formgrid"><div><label>دامنه</label><input name="domain" placeholder="t.example.com" required></div><div><label>DNS Resolverها (هر خط یک مورد)</label><textarea name="resolvers" required>{{global_resolvers}}</textarea></div><div><label>پورت محلی (اختیاری)</label><input name="port" type="number" min="{{pmin}}" max="{{pmax}}" placeholder="خودکار"></div><div><label>گواهی PEM (اختیاری)</label><input name="cert" placeholder="/etc/slipstream/cert.pem"></div></div><p><button>افزودن و اجرای تونل</button></p></form><div class="hint">DNSها به شکل گزینه‌های تکرارشونده <code>--resolver</code> اجرا می‌شوند. وضعیت اتصال بر اساس پیام‌های خود Slipstream بررسی می‌شود: «connection ready»، «connection closed» و «client error».</div></div>
<div class="card"><h3>⚖ لودبالانسر SOCKS5</h3><form method="post" action="/lb/settings"><input type="hidden" name="csrf" value="{{csrf}}"><div class="formgrid"><div><label>پورت خروجی لودبالانسر</label><input name="lb_port" type="number" min="1" max="65535" value="{{lb_port}}" required></div><div><label>وضعیت</label><div class="hint">{% if lb_enabled %}فعال — پورت خروجی در حال سرویس‌دهی است{% else %}غیرفعال{% endif %}</div><label style="margin-top:10px"><input style="width:auto" type="checkbox" name="lb_enabled" value="1" {% if lb_enabled %}checked{% endif %}> فعال‌سازی لودبالانسر</label></div></div><p><button class="green">ذخیره تنظیمات</button></p></form><div class="hint">آدرس ورودی: <code>SERVER_IP:{{lb_port}}</code> — هر اتصال جدید به روش Round Robin به یکی از تونل‌های سالم و فعال متصل می‌شود. تونل‌های ناسالم یا غیرقابل‌دسترسی از چرخه خارج می‌شوند و پس از ۵ دقیقه، در صورت سالم‌بودن، دوباره قابل انتخاب خواهند بود. احراز هویت SOCKS همانند تونل مقصد عبور داده می‌شود؛ این بخش دست‌دهی SOCKS5 را تغییر نمی‌دهد.</div><div class="small">تونل‌های حاضر در چرخه: {{lb_backends|join(', ') if lb_backends else 'هیچ تونل سالمی موجود نیست'}}</div></div>
<div class="card"><h3>تونل‌ها</h3><div class="hint">حجم و سرعت بر اساس حسابداری IP اختصاصی systemd برای هر سرویس است. برای تونل‌های فعلی، شمارش پس از راه‌اندازی مجدد همان سرویس آغاز می‌شود؛ این به‌روزرسانی به‌تنهایی تونل‌ها را قطع نمی‌کند. سرعت با نمونه‌گیری هر ۱۰ ثانیه محاسبه می‌شود.</div>{% if tunnels %}<div class="actions" style="justify-content:flex-start;margin:14px 0"><form method="post" action="/action/all/start" onsubmit="return confirm('تمام تونل‌های ثبت‌شده، حتی موارد متوقف‌شده، اجرا شوند؟')"><input type="hidden" name="csrf" value="{{csrf}}"><button class="green">▶ اجرای همه</button></form><form method="post" action="/action/all/stop" onsubmit="return confirm('تمام تونل‌ها متوقف شوند؟ اتصال کاربران همه تونل‌ها قطع خواهد شد.')"><input type="hidden" name="csrf" value="{{csrf}}"><button class="danger">■ توقف همه</button></form><form method="post" action="/action/all/restart" onsubmit="return confirm('تمام تونل‌های فعال ری‌استارت شوند؟ اتصال کاربران این تونل‌ها موقتاً قطع می‌شود.')"><input type="hidden" name="csrf" value="{{csrf}}"><button class="gray">↻ ری‌استارت همه فعال‌ها</button></form></div>{% endif %}{% if tunnels %}<div class="tablewrap"><table><thead><tr><th>دامنه</th><th>DNSها</th><th>پورت محلی</th><th>سلامت</th><th>حجم ترافیک</th><th>ویرایش DNS</th><th>عملیات</th></tr></thead><tbody>{% for t in tunnels %}<tr><td><b class="domain">{{t.domain}}</b><div class="small">{{t.service}}</div><div class="small">تعداد خطا: <span id="fails-{{t.id}}">{{t.failure_count or 0}}</span></div></td><td style="white-space:pre-line;direction:ltr;text-align:left">{{t.resolver}}</td><td style="direction:ltr">127.0.0.1:{{t.port}}</td><td><span id="health-{{t.id}}" class="pill {{'up' if t.health_state=='connected' else ('wait' if t.health_state=='recovering' else 'down')}}">{{'● متصل' if t.health_state=='connected' else ('● در انتظار' if t.health_state in ['cooldown','recovering'] else ('● توقف دستی' if t.health_state=='manual' else '● قطع شده'))}}</span><span class="healthdetail" id="detail-{{t.id}}">{{t.health_text}}</span><span class="timer" id="timer-{{t.id}}"></span><span class="healthdetail" id="error-{{t.id}}">{{t.last_error or ''}}</span></td><td class="traffic"><div>دریافتی: <strong id="rx-{{t.id}}">—</strong></div><div>ارسالی: <strong id="tx-{{t.id}}">—</strong></div><div>مجموع: <strong id="total-{{t.id}}">—</strong></div><div class="speed" id="speed-{{t.id}}">سرعت: —</div><form class="trafficform" method="post" action="/traffic/reset/{{t.id}}" onsubmit="return confirm('آمار حجم این تونل صفر شود؟')"><input type="hidden" name="csrf" value="{{csrf}}"><button class="gray" type="submit">ریست حجم</button></form></td><td><form class="dnsform" method="post" action="/dns/{{t.id}}"><input type="hidden" name="csrf" value="{{csrf}}"><textarea name="resolvers" required>{{t.resolver}}</textarea><button class="gray">ذخیره DNSها</button></form></td><td><div class="actions">{% if t.enabled %}<form method="post" action="/action/{{t.id}}/stop"><input type="hidden" name="csrf" value="{{csrf}}"><button class="gray">توقف دستی</button></form>{% else %}<form method="post" action="/action/{{t.id}}/start"><input type="hidden" name="csrf" value="{{csrf}}"><button class="green">شروع</button></form>{% endif %}<form method="post" action="/action/{{t.id}}/restart"><input type="hidden" name="csrf" value="{{csrf}}"><button class="gray">ری‌استارت</button></form><a class="btn" href="/logs/{{t.id}}">لاگ</a><form method="post" action="/action/{{t.id}}/delete" onsubmit="return confirm('حذف شود؟')"><input type="hidden" name="csrf" value="{{csrf}}"><button class="danger">حذف</button></form></div></td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="muted">هنوز دامنه‌ای ثبت نشده است.</p>{% endif %}</div>
<div class="card"><h3>منطق پایش سلامت</h3><div class="hint">هر ۱۰ ثانیه لاگ اختصاصی هر سرویس بررسی می‌شود. پیام «connection closed» یا «client error» یک مهلت بازیابی ۳۰ ثانیه‌ای ایجاد می‌کند؛ اگر در این مدت «connection ready» دیده شود، خطا رفع‌شده تلقی می‌شود. در غیر این صورت، یا در صورت خروج پردازش/خطای «address already in use»، همان تونل متوقف و پس از ۵ دقیقه دوباره اجرا می‌شود. این منطق مطابق اسکریپت مدیریت ارسالی شماست و به پاسخ SOCKS5 وابسته نیست.</div></div>
<script>
function clock(s){s=Math.max(0,Math.floor(s));return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')}
function bytes(v){if(v===null||v===undefined)return 'غیرفعال';let n=Math.max(0,Number(v));if(n<1024)return n.toFixed(0)+' B';let u=['KB','MB','GB','TB'];n/=1024;let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++}return n.toFixed(2)+' '+u[i]}
function rate(v){return bytes(v)+'/s'}
async function refresh(){try{let r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)return;let d=await r.json(),h=0,c=0;for(let t of d.tunnels){let e=document.getElementById('health-'+t.id);if(!e)continue;let rx=document.getElementById('rx-'+t.id),tx=document.getElementById('tx-'+t.id),tot=document.getElementById('total-'+t.id),sp=document.getElementById('speed-'+t.id);if(rx){rx.textContent=t.traffic_ready?bytes(t.rx):'نیازمند فعال‌سازی';tx.textContent=t.traffic_ready?bytes(t.tx):'نیازمند فعال‌سازی';tot.textContent=t.traffic_ready?bytes(t.rx+t.tx):'—';sp.textContent=t.traffic_ready?'سرعت دریافتی '+rate(t.rx_rate)+' · ارسالی '+rate(t.tx_rate):'حسابداری ترافیک هنوز فعال نشده'}let tm=document.getElementById('timer-'+t.id),de=document.getElementById('detail-'+t.id);e.className='pill '+(t.state==='connected'?'up':(t.state==='recovering'?'wait':'down'));e.textContent=t.state==='connected'?'● متصل':t.state==='cooldown'?'● قطع موقت':t.state==='recovering'?'● در حال اتصال':t.state==='manual'?'● توقف دستی':'● قطع شده';if(t.state==='connected')h++;if(t.state==='cooldown')c++;de.textContent=t.state==='cooldown'?'اتصال مجدد خودکار':t.state==='recovering'?'در حال بررسی اتصال':t.state==='connected'?'پیام connection ready دریافت شده':t.state==='manual'?'توقف توسط مدیر':'سرویس قطع است';tm.textContent=t.state==='cooldown'&&t.retry_at?'بازگشت در '+clock(t.retry_at-Date.now()/1000):'';document.getElementById('error-'+t.id).textContent=t.last_error||'';document.getElementById('fails-'+t.id).textContent=t.failure_count||0}document.getElementById('healthy').textContent=h;document.getElementById('cooling').textContent=c}catch(e){}}
refresh();setInterval(refresh,5000);
</script>
{% endif %}</div></body></html>'''

def db():
    os.makedirs(APP,exist_ok=True); c=sqlite3.connect(DB,timeout=10); c.row_factory=sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS tunnels(id INTEGER PRIMARY KEY,domain TEXT UNIQUE,resolver TEXT,port INTEGER UNIQUE,cert TEXT DEFAULT '',enabled INTEGER NOT NULL DEFAULT 1,health_state TEXT NOT NULL DEFAULT 'recovering',retry_at REAL,last_started REAL,last_check REAL,last_error TEXT DEFAULT '',failure_count INTEGER NOT NULL DEFAULT 0,last_down REAL)")
    cols={r['name'] for r in c.execute('PRAGMA table_info(tunnels)')}
    for n,d in {'enabled':'INTEGER NOT NULL DEFAULT 1','health_state':"TEXT NOT NULL DEFAULT 'recovering'",'retry_at':'REAL','last_started':'REAL','last_check':'REAL','last_error':"TEXT DEFAULT ''",'failure_count':'INTEGER NOT NULL DEFAULT 0','last_down':'REAL'}.items():
        if n not in cols:c.execute(f'ALTER TABLE tunnels ADD COLUMN {n} {d}')
    c.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('lb_port',?)",(str(LB_DEFAULT_PORT),))
    c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('lb_enabled','1')")
    c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('global_resolvers','1.1.1.1:53')")
    c.execute('CREATE TABLE IF NOT EXISTS traffic_stats(tunnel_id INTEGER PRIMARY KEY, rx_total INTEGER NOT NULL DEFAULT 0, tx_total INTEGER NOT NULL DEFAULT 0, last_rx INTEGER NOT NULL DEFAULT 0, last_tx INTEGER NOT NULL DEFAULT 0, last_sample REAL, rx_rate REAL NOT NULL DEFAULT 0, tx_rate REAL NOT NULL DEFAULT 0)')
    c.commit();return c

def get_setting(key, default=None):
    c=db(); row=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone(); c.close()
    return row['value'] if row else default

def set_settings(**values):
    c=db()
    for k,v in values.items(): c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,str(v)))
    c.commit(); c.close()

def lb_backends():
    c=db(); rows=c.execute("SELECT id,port FROM tunnels WHERE enabled=1 AND health_state='connected' ORDER BY port").fetchall(); c.close()
    now=time.time(); good=[]
    for row in rows:
        port=int(row['port']); until=LB_QUARANTINED.get(port,0)
        if until>now: continue
        if until: LB_QUARANTINED.pop(port,None)
        good.append(port)
    return good

def choose_backend():
    global LB_RR_INDEX
    candidates=lb_backends()
    if not candidates: return None
    with LB_LOCK:
        # Round Robin over healthy candidates; failed TCP connects are quarantined for 5 minutes.
        start=LB_RR_INDEX % len(candidates)
        ordered=candidates[start:]+candidates[:start]
        LB_RR_INDEX=(LB_RR_INDEX+1) % max(1,len(candidates))
    for port in ordered:
        try:
            upstream=socket.create_connection(('127.0.0.1',port),timeout=1.5)
            upstream.settimeout(None)
            return port,upstream
        except OSError:
            LB_QUARANTINED[port]=time.time()+LB_QUARANTINE
    return None

class LBHandler(socketserver.BaseRequestHandler):
    def handle(self):
        picked=choose_backend()
        if not picked: return
        _port, upstream=picked
        client=self.request
        try:
            client.settimeout(120); upstream.settimeout(120)
            peers=[client,upstream]
            while True:
                readable,_,_ = select.select(peers,[],[],None)
                if not readable: break
                for src in readable:
                    dst=upstream if src is client else client
                    try: data=src.recv(65536)
                    except (BlockingIOError, OSError): return
                    if not data: return
                    dst.sendall(data)
        except (OSError, ValueError):
            pass
        finally:
            try: upstream.close()
            except Exception: pass

class LBThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True
    block_on_close=False

def lb_supervisor():
    global LB_SERVER,LB_SERVER_PORT
    while True:
        try:
            enabled=get_setting('lb_enabled','1')=='1'
            try: desired=int(get_setting('lb_port',str(LB_DEFAULT_PORT)))
            except (TypeError,ValueError): desired=LB_DEFAULT_PORT
            with LB_LOCK:
                current=LB_SERVER; current_port=LB_SERVER_PORT
            if current and (not enabled or desired!=current_port):
                try: current.shutdown(); current.server_close()
                except Exception: pass
                with LB_LOCK: LB_SERVER=None; LB_SERVER_PORT=None
                current=None
            if enabled and current is None and 1<=desired<=65535:
                try:
                    server=LBThreadingServer(('0.0.0.0',desired),LBHandler)
                    thread=threading.Thread(target=server.serve_forever,daemon=True,name='slipstream-lb-server')
                    thread.start()
                    with LB_LOCK: LB_SERVER=server; LB_SERVER_PORT=desired
                    print(f'[load-balancer] listening on 0.0.0.0:{desired}',flush=True)
                except OSError as e:
                    print(f'[load-balancer] cannot listen on {desired}: {e}',flush=True)
        except Exception as e:
            print(f'[load-balancer-supervisor] {type(e).__name__}: {e}',flush=True)
        time.sleep(2)

def csrf_token():
    if 'csrf' not in session:session['csrf']=secrets.token_urlsafe(24)
    return session['csrf']
def check_csrf():
    if not hmac.compare_digest(str(request.form.get('csrf','')),str(session.get('csrf',''))):abort(400)
def require_login(fn):
    @wraps(fn)
    def w(*a,**k):
        if session.get('logged') is not True:return redirect('/login')
        return fn(*a,**k)
    return w
def valid_domain(s):
    return len(s)<=253 and re.fullmatch(r'(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}',s or '') is not None
def valid_resolver(s):
    try:
        host,port=s.rsplit(':',1)
        if host.startswith('[') and host.endswith(']'):host=host[1:-1]
        ipaddress.ip_address(host)
        return port.isdigit() and 1<=int(port)<=65535
    except Exception:return False
def parse_resolvers(raw):
    a=[]
    for x in (raw or '').replace(',','\n').splitlines():
        x=x.strip()
        if x and x not in a:a.append(x)
    if not a or any(not valid_resolver(x) for x in a):raise ValueError('DNS نامعتبر است؛ هر خط باید IP:PORT معتبر باشد.')
    return a

def parse_scan_resolvers(raw,port):
    if not 1<=port<=65535:raise ValueError('پورت DNS باید بین ۱ تا ۶۵۵۳۵ باشد.')
    items=[]
    for raw_line in (raw or '').replace(',','\n').splitlines():
        line=raw_line.strip()
        if not line:continue
        try:ip=ipaddress.ip_address(line)
        except ValueError:raise ValueError(f'IP نامعتبر است: {line} (فقط IP وارد کن؛ پورت جداگانه تعیین می‌شود)')
        value=f'[{ip.compressed}]:{port}' if ip.version==6 else f'{ip.compressed}:{port}'
        if value not in items:items.append(value)
    if not items:raise ValueError('حداقل یک IP برای اسکن وارد کن.')
    if len(items)>10000:raise ValueError('در هر اسکن حداکثر ۱۰٬۰۰۰ IP مجاز است تا حافظه پنل بیش از حد مصرف نشود.')
    return items
def unit(i):return f'slipstream-client-{i}'
def ctl(*a):return subprocess.run(['/usr/bin/systemctl',*a],capture_output=True,text=True,timeout=15)
def active(i):return ctl('is-active','--quiet',unit(i)).returncode==0
def update(i,**f):
    allowed={'enabled','health_state','retry_at','last_started','last_check','last_error','failure_count','last_down','resolver'}
    if not set(f)<=allowed:raise ValueError('bad update')
    c=db();c.execute('UPDATE tunnels SET '+','.join(k+'=?' for k in f)+' WHERE id=?',(*f.values(),i));c.commit();c.close()
def log_path(r):
    return os.path.join(LOGDIR, f"{r['port']}.log")

def reset_log_cursor(r):
    path=log_path(r)
    try:
        LOG_OFFSETS[r['id']]=os.path.getsize(path)
    except OSError:
        LOG_OFFSETS[r['id']]=0
    SUSPECT_SINCE.pop(r['id'],None)

def read_new_log_lines(r):
    path=log_path(r); i=r['id']
    try:
        size=os.path.getsize(path)
        offset=LOG_OFFSETS.get(i,0)
        if size<offset:offset=0
        with open(path,'r',encoding='utf-8',errors='replace') as f:
            f.seek(offset); data=f.read(); LOG_OFFSETS[i]=f.tell()
        return data.splitlines()
    except FileNotFoundError:
        return []

def make_unit(r, reload_systemd=True):
    args=[BIN,'--domain',r['domain']]
    for dns in parse_resolvers(r['resolver']):args += ['--resolver',dns]
    args += ['--tcp-listen-host',LOCAL_HOST,'--tcp-listen-port',str(r['port'])]
    if r['cert']:args += ['--cert',r['cert']]
    os.makedirs(LOGDIR,exist_ok=True)
    try:
        u=pwd.getpwnam('slipstream'); os.chown(LOGDIR,u.pw_uid,u.pw_gid)
    except KeyError:
        raise RuntimeError('کاربر سیستم slipstream وجود ندارد؛ نصب پنل را بررسی کنید.')
    os.chmod(LOGDIR,0o750)
    lp=log_path(r)
    with open(lp,'a',encoding='utf-8'):pass
    os.chown(lp,u.pw_uid,u.pw_gid);os.chmod(lp,0o640)
    lines=['[Unit]',f'Description=Slipstream client {r["domain"]}','After=network-online.target','Wants=network-online.target','','[Service]','Type=simple','User=slipstream','Group=slipstream','ExecStart='+' '.join(shlex.quote(x) for x in args),'Restart=no','IPAccounting=yes',f'StandardOutput=append:{lp}','StandardError=inherit','NoNewPrivileges=true','PrivateTmp=true','ProtectSystem=strict','ProtectHome=true',f'ReadWritePaths={LOGDIR}','','[Install]','WantedBy=multi-user.target','']
    with open(f'/etc/systemd/system/{unit(r["id"])}.service','w') as f:f.write('\n'.join(lines))
    os.chmod(f'/etc/systemd/system/{unit(r["id"])}.service',0o644)
    if reload_systemd:ctl('daemon-reload')

def start(r):
    make_unit(r);reset_log_cursor(r);ctl('enable',unit(r['id']));z=ctl('start',unit(r['id']))
    if z.returncode==0:
        update(r['id'],enabled=1,health_state='recovering',retry_at=None,last_started=time.time(),last_error='')
    else:
        now=time.time();update(r['id'],enabled=1,health_state='cooldown',retry_at=now+COOLDOWN,last_started=now,last_down=now,last_error=(z.stderr or z.stdout).strip() or 'systemd نتوانست تونل را اجرا کند.',failure_count=(r['failure_count'] or 0)+1)

def fail_tunnel(r,reason,now):
    i=r['id']
    ctl('stop',unit(i))
    SUSPECT_SINCE.pop(i,None)
    update(i,health_state='cooldown',retry_at=now+COOLDOWN,last_error=reason,last_down=now,last_check=now,failure_count=(r['failure_count'] or 0)+1)

def refresh_existing_units():
    """Rewrite existing units to capture stdout/stderr in per-tunnel logs, then restart enabled ones."""
    c=db(); rows=c.execute('SELECT * FROM tunnels ORDER BY id').fetchall(); c.close()
    for r in rows:
        make_unit(r)
    for r in rows:
        if r['enabled']:
            reset_log_cursor(r)
            z=ctl('restart',unit(r['id']))
            now=time.time()
            if z.returncode==0:
                update(r['id'],health_state='recovering',retry_at=None,last_started=now,last_error='')
            else:
                update(r['id'],health_state='cooldown',retry_at=now+COOLDOWN,last_started=now,last_down=now,last_error=(z.stderr or z.stdout).strip(),failure_count=(r['failure_count'] or 0)+1)


TRAFFIC_CACHE = {}
TRAFFIC_LOCK = threading.RLock()
TRAFFIC_SAMPLE_SECONDS = 10

def read_systemd_traffic(rows):
    """Read all per-unit cgroup IP counters in one systemctl invocation."""
    if not rows:
        return {}
    names=[unit(r['id'])+'.service' for r in rows]
    cmd=['/usr/bin/systemctl','show','--no-pager',
         '--property=Id','--property=IPAccounting',
         '--property=IPIngressBytes','--property=IPEgressBytes','--',*names]
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=12)
        if p.returncode != 0:
            return {}
        result={}; current={}
        for line in p.stdout.splitlines()+['']:
            if not line.strip():
                if current.get('Id'):
                    try:
                        result[current['Id'].removesuffix('.service')]=(
                            int(current.get('IPIngressBytes','0')),
                            int(current.get('IPEgressBytes','0')),
                            current.get('IPAccounting','no').lower() in ('yes','true','1'))
                    except (ValueError,TypeError):
                        pass
                current={}
                continue
            if '=' in line:
                k,v=line.split('=',1);current[k]=v
        return result
    except (OSError,subprocess.TimeoutExpired):
        return {}

def sample_traffic(force=False):
    """Persist cumulative bytes and derive rates with a single low-frequency poll."""
    now=time.time()
    with TRAFFIC_LOCK:
        if not force and now-TRAFFIC_CACHE.get('_sampled_at',0)<TRAFFIC_SAMPLE_SECONDS:
            return
        c=db()
        rows=c.execute('SELECT id FROM tunnels').fetchall()
        counters=read_systemd_traffic(rows)
        for row in rows:
            i=int(row['id']); name=unit(i)
            if name not in counters:
                TRAFFIC_CACHE[i]={'ready':False,'rx':0,'tx':0,'rx_rate':0,'tx_rate':0}
                continue
            rx,tx,enabled=counters[name]
            if not enabled:
                TRAFFIC_CACHE[i]={'ready':False,'rx':0,'tx':0,'rx_rate':0,'tx_rate':0}
                continue
            st=c.execute('SELECT * FROM traffic_stats WHERE tunnel_id=?',(i,)).fetchone()
            if st is None:
                c.execute('INSERT INTO traffic_stats(tunnel_id,last_rx,last_tx,last_sample) VALUES(?,?,?,?)',(i,rx,tx,now))
                rx_total=tx_total=0;rx_rate=tx_rate=0
            else:
                elapsed=max(0.001,now-(st['last_sample'] or now))
                drx=(rx-st['last_rx']) if rx>=st['last_rx'] else rx
                dtx=(tx-st['last_tx']) if tx>=st['last_tx'] else tx
                rx_total=st['rx_total']+max(0,drx)
                tx_total=st['tx_total']+max(0,dtx)
                rx_rate=max(0,drx)/elapsed
                tx_rate=max(0,dtx)/elapsed
                c.execute('UPDATE traffic_stats SET rx_total=?,tx_total=?,last_rx=?,last_tx=?,last_sample=?,rx_rate=?,tx_rate=? WHERE tunnel_id=?',
                          (rx_total,tx_total,rx,tx,now,rx_rate,tx_rate,i))
            TRAFFIC_CACHE[i]={'ready':True,'rx':int(rx_total),'tx':int(tx_total),
                              'rx_rate':float(rx_rate),'tx_rate':float(tx_rate)}
        c.commit();c.close()
        TRAFFIC_CACHE['_sampled_at']=now

def traffic_snapshot(i):
    sample_traffic()
    with TRAFFIC_LOCK:
        return dict(TRAFFIC_CACHE.get(i,{'ready':False,'rx':0,'tx':0,'rx_rate':0,'tx_rate':0}))

def monitor():
    while True:
        try:
            c=db();rows=c.execute('SELECT * FROM tunnels WHERE enabled=1').fetchall();c.close();now=time.time()
            sample_traffic()
            for r in rows:
                i=r['id'];retry=r['retry_at']
                if retry:
                    if now<retry:
                        if active(i):ctl('stop',unit(i))
                        continue
                    try:start(r)
                    except Exception as e:
                        update(i,health_state='cooldown',retry_at=time.time()+COOLDOWN,last_error=str(e),last_down=time.time(),failure_count=(r['failure_count'] or 0)+1)
                    continue

                # Match the supplied supervisor script: inspect Slipstream output itself.
                immediate_error=None
                for line in read_new_log_lines(r):
                    lower=line.lower()
                    if 'connection ready' in lower:
                        SUSPECT_SINCE.pop(i,None)
                        update(i,health_state='connected',last_check=now,last_error='')
                    elif 'address already in use' in lower:
                        immediate_error='پورت محلی قبلاً توسط برنامه دیگری اشغال شده است.'
                        break
                    elif 'connection closed' in lower or 'client error' in lower:
                        if i not in SUSPECT_SINCE:
                            SUSPECT_SINCE[i]=time.monotonic()
                            update(i,health_state='recovering',last_check=now,last_error=line[:1000])

                if immediate_error:
                    fail_tunnel(r,immediate_error,now);continue
                if not active(i):
                    fail_tunnel(r,'پردازش Slipstream خارج شد یا متوقف شد.',now);continue
                suspect=SUSPECT_SINCE.get(i)
                if suspect is not None and time.monotonic()-suspect>=ERROR_GRACE_SECONDS:
                    fail_tunnel(r,'پس از خطای connection، طی ۳۰ ثانیه پیام connection ready دریافت نشد.',now);continue
                # A running process with no error/readiness line remains in the starting state.
                c=db();state=c.execute('SELECT health_state FROM tunnels WHERE id=?',(i,)).fetchone();c.close()
                if state and state['health_state'] not in ('connected','recovering'):
                    update(i,health_state='recovering',last_check=now)
        except Exception as e:
            # Keep the monitor alive; the panel service journal will show unexpected monitor errors.
            print(f'[health-monitor] {type(e).__name__}: {e}',flush=True)
        time.sleep(CHECK)
def tunnels():
    c=db();rows=c.execute('SELECT * FROM tunnels ORDER BY port').fetchall();out=[]
    for x in rows:
        d=dict(x);d['service']=unit(d['id']);d['health_text']='در انتظار اتصال مجدد' if d['health_state']=='cooldown' else ('در حال بررسی اتصال' if d['health_state']=='recovering' else ('پیام connection ready دریافت شده' if d['health_state']=='connected' else 'توسط مدیر متوقف شده'))
        out.append(d)
    c.close();return out

DNS_SCAN_HTML=r'''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>اسکن DNS · Slipstream</title><style>
:root{color-scheme:dark;--txt:#edf4ff;--muted:#9aacc7;--green:#25c58b;--red:#ff667c;--blue:#438cff}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:linear-gradient(145deg,#080f1e,#101b30);color:var(--txt);font:15px/1.7 system-ui,-apple-system,"Segoe UI",sans-serif}.wrap{max-width:1200px;margin:0 auto;padding:28px 18px}.top,.actions{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.brand{font-size:25px;font-weight:850}.muted,.hint{color:var(--muted);font-size:13px}.card{background:#111d31;border:1px solid #263b59;border-radius:16px;padding:22px;margin:18px 0}h3{margin:0 0 15px}label{display:block;color:#b4c4da;font-size:13px;margin:10px 0 6px}textarea,input{width:100%;background:#091426;color:var(--txt);border:1px solid #2b4263;border-radius:10px;padding:12px;font:inherit}textarea{min-height:180px;direction:ltr;text-align:left;font-family:ui-monospace,Consolas,monospace}input{min-height:44px}button,.btn{border:0;border-radius:10px;padding:10px 15px;background:#3475dc;color:#fff;font-weight:750;cursor:pointer;text-decoration:none;display:inline-block}button.gray,.btn.gray{background:#263b58}button.danger{background:#713447}button:disabled{opacity:.5;cursor:not-allowed}.hint{background:#091426;padding:12px;border-radius:10px;margin-top:12px;line-height:1.9}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.stat{background:#0c1729;padding:14px;border-radius:12px;color:var(--muted)}.num{display:block;color:#fff;font-size:25px;font-weight:850}.formgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.tablewrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:650px}td,th{text-align:right;padding:11px;border-bottom:1px solid #263b59;font-size:13px}th{color:#9fb3cf}.ok{color:#70e5b5}.bad{color:#ff9cab}.dns{direction:ltr;text-align:left;font-family:monospace}.progress{height:9px;background:#091426;border-radius:20px;overflow:hidden;margin:12px 0}.bar{height:100%;width:0;background:linear-gradient(90deg,#438cff,#25c58b);transition:width .2s}.hidden{display:none}.section-title{display:flex;align-items:center;gap:8px;margin:20px 0 8px}.tag{font-size:11px;border:1px solid #2b4263;border-radius:20px;padding:2px 8px;color:#b4c4da}.small{font-size:12px;color:var(--muted)}.pick{width:18px;height:18px;min-height:0;accent-color:#438cff;cursor:pointer}.lat-tools{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:12px 0}@media(max-width:900px){.stats{grid-template-columns:repeat(3,1fr)}}@media(max-width:650px){.wrap{padding:16px 10px}.card{padding:15px}.stats{grid-template-columns:repeat(2,1fr)}.num{font-size:20px}}
</style></head><body><div class="wrap"><div class="top"><div><div class="brand">🔎 اسکن DNS برای Slipstream</div><div class="muted">دو مرحله: Ping اطلاع‌رسانی DNSها و تست کامل SOCKS5 احراز هویت‌شده از طریق Slipstream تا Google</div></div><a class="btn gray" href="/">بازگشت به پنل</a></div>
<div class="card"><h3>تنظیم اسکن</h3><form id="scanForm"><input type="hidden" id="csrf" value="{{csrf}}"><div class="formgrid"><div><label>دامنه Slipstream</label><input id="domain" placeholder="t.example.com" required></div><div><label>پورت DNS (برای همه IPها)</label><input id="dnsPort" type="number" min="1" max="65535" value="53" required></div><div><label>تعداد اسکن هم‌زمان (Worker)</label><input id="workers" type="number" min="1" max="32" value="{{default_workers}}" required><div class="small">هسته‌های CPU سرور: {{cpu_count}} · مقدار پیشنهادی اولیه بر اساس CPU</div></div><div><label>مهلت تست هر DNS (ثانیه)</label><input id="timeout" type="number" min="5" max="60" value="12"></div></div>
<label>فهرست IPهای DNS (هر خط فقط یک IP؛ محدودیت قبلی ۳۲ مورد حذف شده)</label><textarea id="resolvers" placeholder="1.1.1.1&#10;8.8.8.8&#10;9.9.9.9" required>{{global_resolvers}}</textarea><div class="formgrid"><div><label>نام کاربری SOCKS5 (برای اتصال اصلی)</label><input id="socksUser" autocomplete="off" placeholder="نام کاربری" required></div><div><label>رمز عبور SOCKS5 (برای اتصال اصلی)</label><input id="socksPass" type="password" autocomplete="new-password" placeholder="رمز عبور" required></div><div><label>مسیر گواهی PEM (اختیاری)</label><input id="cert" placeholder="/etc/slipstream/cert.pem"></div><div><label>دامنه مقصد تست</label><input value="www.google.com:443 / HTTPS generate_204" readonly></div></div><div class="actions" style="justify-content:flex-start;margin-top:14px"><button type="submit" id="startBtn">شروع اسکن دومرحله‌ای</button><button type="button" class="danger hidden" id="stopBtn">توقف اسکن</button></div></form><div class="hint"><b>مرحله ۱:</b> یک‌بار Ping از تمام IPهای DNS گرفته می‌شود. <b>مرحله ۲:</b> تمام DNSهای واردشده، مستقل از نتیجه Ping، وارد تست کامل می‌شوند؛ برای هرکدام یک Slipstream موقت اجرا می‌شود و پس از آماده‌شدن تونل، اسکنر مستقیماً به Listener محلی وصل می‌شود، روش Username/Password را در دست‌دهی SOCKS5 مذاکره می‌کند و همان نام کاربری و رمز را از داخل تونل برای SOCKS5 سمت سرور می‌فرستد؛ سپس درخواست HTTPS به <b>www.google.com:443</b> را عبور می‌دهد. پاسخ TLS معتبر و HTTP 204 از <b>/generate_204</b> لازم است تا DNS سالم اعلام شود. نتیجه Ping فقط اطلاعاتی است و در انتخاب DNSها برای مرحله دوم نقشی ندارد؛ حتی DNSهایی که ICMP را مسدود کرده‌اند نیز تست کامل می‌شوند. اعتبارنامه‌ها ذخیره نمی‌شوند و فقط در حافظه همان اسکن استفاده می‌شوند. Latency زمان کامل تا پاسخ Google است. تعداد Workerها سقف کارهای هم‌زمان هر مرحله است. تونل‌های اصلی ری‌استارت یا تغییر نمی‌کنند.</div></div>
<div class="card"><h3>پیشرفت اسکن</h3><div class="stats"><div class="stat">Ping موفق<span class="num ok" id="pingGood">0</span></div><div class="stat">Ping ناموفق<span class="num bad" id="pingBad">0</span></div><div class="stat">Google HTTPS موفق<span class="num ok" id="latGood">0</span></div><div class="stat">Google HTTPS ناموفق<span class="num bad" id="latBad">0</span></div></div><div class="progress"><div class="bar" id="bar"></div></div><div class="muted" id="state">هنوز اسکن شروع نشده است.</div>
<div class="section-title"><h3>مرحله اول: Ping DNS</h3><span class="tag" id="pingProgress">0 / 0</span></div><div class="tablewrap"><table><thead><tr><th>DNS</th><th>نتیجه</th><th>زمان</th><th>جزئیات</th></tr></thead><tbody id="pingRows"><tr><td colspan="4" class="muted">هنوز بررسی نشده است.</td></tr></tbody></table></div>
<div class="section-title"><h3>مرحله دوم: تست کامل تونل و HTTPS گوگل با احراز هویت SOCKS5</h3><span class="tag" id="latProgress">0 / 0</span></div><div class="lat-tools"><button type="button" class="gray" id="sortLatencyBtn">مرتب‌سازی Latency: کم به زیاد</button><button type="button" class="gray" id="copySelectedBtn">کپی DNSهای انتخاب‌شده (۰)</button><span class="small">نتایج موفق به‌صورت پیش‌فرض بر اساس کمترین Latency نمایش داده می‌شوند؛ برای انتخاب، تیک کنار DNS را بزن.</span></div><div class="tablewrap"><table><thead><tr><th>انتخاب</th><th>DNS</th><th>اتصال HTTPS گوگل</th><th>Latency</th><th>جزئیات</th></tr></thead><tbody id="latRows"><tr><td colspan="5" class="muted">تمام DNSهای واردشده، مستقل از نتیجه Ping، آزمایش می‌شوند.</td></tr></tbody></table></div>
<div class="actions" style="justify-content:flex-start;margin-top:14px"><button type="button" class="gray" id="copyBtn">کپی DNSهای نهایی</button><button type="button" class="gray" id="copyPingBtn">کپی DNSهای Ping موفق</button></div><label>DNSهای نهایی سالم (تست کامل Google موفق)</label><textarea id="healthyList" readonly placeholder="پس از پایان اسکن DNSهای سالم اینجا نمایش داده می‌شوند." style="min-height:100px"></textarea></div></div>
<script>
let timer=null;const $=id=>document.getElementById(id);const selectedResolvers=new Set();let latencyAscending=true;function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function latencyMs(x){const m=String(x.elapsed||'').match(/[0-9.]+/);return m?Number(m[0]):Number.POSITIVE_INFINITY}
function rowsHtml(items,stage){if(!items.length)return `<tr><td colspan="${stage==='latency'?5:4}" class="muted">هنوز نتیجه‌ای وجود ندارد.</td></tr>`;let list=items;if(stage==='latency')list=[...items].sort((a,b)=>latencyAscending?latencyMs(a)-latencyMs(b):latencyMs(b)-latencyMs(a));return list.map(x=>{const pick=stage==='latency'&&x.ok?`<input class="pick resolver-pick" type="checkbox" data-resolver="${esc(x.resolver)}" ${selectedResolvers.has(x.resolver)?'checked':''} aria-label="انتخاب ${esc(x.resolver)}">`:(stage==='latency'?'—':'');return `<tr>${stage==='latency'?`<td>${pick}</td>`:''}<td class="dns">${esc(x.resolver)}</td><td class="${x.ok?'ok':'bad'}">${x.ok?'✓ '+(stage==='ping'?'پاسخ داد':stage==='latency'?'اتصال HTTPS گوگل موفق':'متصل شد'):'✕ ناموفق'}</td><td>${esc(x.elapsed||'—')}</td><td>${esc(x.detail||'')}</td></tr>`}).join('')}
function updateSelectedCount(){$('copySelectedBtn').textContent=`کپی DNSهای انتخاب‌شده (${selectedResolvers.size})`}
function render(d){const p=d.ping_results||[],l=d.latency_results||[];$('pingGood').textContent=p.filter(x=>x.ok).length;$('pingBad').textContent=p.filter(x=>!x.ok).length;$('latGood').textContent=l.filter(x=>x.ok).length;$('latBad').textContent=l.filter(x=>!x.ok).length;$('pingRows').innerHTML=rowsHtml(p,'ping');$('latRows').innerHTML=rowsHtml(l,'latency');updateSelectedCount();$('pingProgress').textContent=(d.ping_done||0)+' / '+(d.ping_total||0);$('latProgress').textContent=(d.latency_done||0)+' / '+(d.latency_total||0);let pct=d.phase==='ping'?((d.ping_total||0)?(d.ping_done||0)/d.ping_total*50:0):d.phase==='latency'?(50+((d.latency_total||0)?(d.latency_done||0)/d.latency_total*50:0)):(d.phase==='done'?100:0);$('bar').style.width=Math.round(pct)+'%';let phase=d.phase==='ping'?'مرحله اول: Ping DNSها':d.phase==='latency'?'مرحله دوم: تست کامل تونل و HTTPS گوگل':d.phase==='done'?(d.cancelled?'اسکن متوقف شد.':'اسکن دومرحله‌ای به پایان رسید.'):'هنوز اسکن شروع نشده است.';$('state').textContent=d.running?`${phase} · دامنه: ${d.domain} · Worker: ${d.workers}`:phase;$('healthyList').value=l.filter(x=>x.ok).map(x=>x.resolver).join('\n');$('startBtn').disabled=!!d.running;$('stopBtn').classList.toggle('hidden',!d.running)}
async function poll(){try{let r=await fetch('/api/dns-scan/status',{cache:'no-store'});if(!r.ok)return;let d=await r.json();render(d);if(!d.running&&timer){clearInterval(timer);timer=null}}catch(e){}}
$('scanForm').addEventListener('submit',async e=>{e.preventDefault();selectedResolvers.clear();updateSelectedCount();let fd=new FormData();for(const [k,id] of Object.entries({csrf:'csrf',domain:'domain',dns_port:'dnsPort',workers:'workers',resolvers:'resolvers',cert:'cert',timeout:'timeout',socks_user:'socksUser',socks_pass:'socksPass'}))fd.append(k,$(id).value);$('startBtn').disabled=true;try{let r=await fetch('/api/dns-scan/start',{method:'POST',body:fd});let d=await r.json();if(!r.ok){alert(d.error||'شروع اسکن ناموفق بود');$('startBtn').disabled=false;return}render(d);if(timer)clearInterval(timer);timer=setInterval(poll,800)}catch(e){alert('خطا در ارتباط با پنل');$('startBtn').disabled=false}});
$('stopBtn').addEventListener('click',async()=>{let fd=new FormData();fd.append('csrf',$('csrf').value);await fetch('/api/dns-scan/stop',{method:'POST',body:fd});poll()});$('latRows').addEventListener('change',e=>{if(!e.target.classList.contains('resolver-pick'))return;const ip=e.target.dataset.resolver;if(e.target.checked)selectedResolvers.add(ip);else selectedResolvers.delete(ip);updateSelectedCount()});$('sortLatencyBtn').addEventListener('click',()=>{latencyAscending=!latencyAscending;$('sortLatencyBtn').textContent=`مرتب‌سازی Latency: ${latencyAscending?'کم به زیاد':'زیاد به کم'}`;if(window.lastScan)render(window.lastScan)});async function copyText(v){try{await navigator.clipboard.writeText(v)}catch(e){let t=document.createElement('textarea');t.value=v;document.body.appendChild(t);t.select();document.execCommand('copy');t.remove()}}$('copyBtn').addEventListener('click',()=>copyText($('healthyList').value));$('copySelectedBtn').addEventListener('click',()=>{const values=[...selectedResolvers];if(!values.length){alert('ابتدا حداقل یک DNS را انتخاب کن.');return}copyText(values.join('\n'))});$('copyPingBtn').addEventListener('click',()=>copyText((window.lastPing||[]).filter(x=>x.ok).map(x=>x.resolver).join('\n')));const oldRender=render;render=function(d){window.lastPing=d.ping_results||[];window.lastScan=d;oldRender(d)};poll();
</script></body></html>''' 

def _dns_scan_snapshot():
    keys=('running','cancel','domain','phase','workers','ping_total','ping_done','latency_total','latency_done','ping_results','latency_results','started_at')
    with DNS_SCAN_LOCK:
        return {k:([dict(x) for x in DNS_SCAN_STATE[k]] if k in ('ping_results','latency_results') else DNS_SCAN_STATE[k]) for k in keys} | {'cancelled':DNS_SCAN_STATE['cancel']}

def _resolver_host(resolver):
    host=resolver.rsplit(':',1)[0]
    if host.startswith('[') and host.endswith(']'):host=host[1:-1]
    return str(ipaddress.ip_address(host))

def _dns_scan_ping(resolver, timeout_sec=2):
    started=time.monotonic()
    try:
        host=_resolver_host(resolver);addr=ipaddress.ip_address(host);ping=shutil.which('ping')
        if not ping:return False,'ابزار ping نصب نیست (بسته iputils-ping)',time.monotonic()-started
        args=[ping,'-n','-c','1','-W',str(timeout_sec)]
        if addr.version==6:args.insert(1,'-6')
        args.append(host);z=subprocess.run(args,capture_output=True,text=True,timeout=timeout_sec+1)
        elapsed=time.monotonic()-started
        if z.returncode==0:return True,'پاسخ ICMP دریافت شد',elapsed
        detail=' '.join((z.stderr or z.stdout or '').strip().split())[-180:] or 'پاسخی دریافت نشد یا ICMP مسدود است'
        return False,detail,elapsed
    except Exception as e:return False,f'{type(e).__name__}: {e}',(time.monotonic()-started)*1000

def _recv_exact(sock,n):
    data=b''
    while len(data)<n:
        chunk=sock.recv(n-len(data))
        if not chunk:raise ConnectionError('ارتباط SOCKS پیش از تکمیل پاسخ بسته شد')
        data+=chunk
    return data

def _socks5_reply(sock):
    head=_recv_exact(sock,4);atyp=head[3]
    if atyp==1:tail=_recv_exact(sock,6)
    elif atyp==4:tail=_recv_exact(sock,18)
    elif atyp==3:tail=_recv_exact(sock,1);tail+=_recv_exact(sock,tail[0]+2)
    else:raise ValueError('نوع آدرس SOCKS نامعتبر است')
    return head+tail

def _dns_scan_latency(target_domain,upstream_port,username,password,timeout_sec):
    """Send a real RFC1929 SOCKS5 handshake through the Slipstream TCP tunnel.

    The username/password are deliberately NOT checked by a local gateway:
    they must reach the SOCKS5 service on the far side of Slipstream.
    """
    started=time.monotonic();raw=None;tls_sock=None
    try:
        raw=socket.create_connection((LOCAL_HOST,upstream_port),timeout=timeout_sec)
        raw.settimeout(timeout_sec)
        # Negotiate username/password directly with the SOCKS5 peer through
        # Slipstream. Do not terminate or strip the authentication locally.
        raw.sendall(b'\x05\x01\x02')
        method=_recv_exact(raw,2)
        if method!=b'\x05\x02':
            if method==b'\x05\xff':
                raise PermissionError('سرور SOCKS5 روش احراز هویت را نپذیرفت')
            if method==b'\x05\x00':
                raise PermissionError('سرور SOCKS5 احراز هویت Username/Password را درخواست نکرد؛ پاسخ no-auth دریافت شد')
            raise ConnectionError(f'پاسخ نامعتبر در مذاکره SOCKS5: {method.hex()}')
        ub=username.encode('utf-8');pb=password.encode('utf-8')
        if not 1<=len(ub)<=255 or not 1<=len(pb)<=255:
            raise ValueError('طول نام کاربری و رمز SOCKS5 باید بین ۱ تا ۲۵۵ بایت باشد')
        raw.sendall(b'\x01'+bytes([len(ub)])+ub+bytes([len(pb)])+pb)
        auth_reply=_recv_exact(raw,2)
        if auth_reply!=b'\x01\x00':
            raise PermissionError('احراز هویت SOCKS5 در سمت سرور ناموفق بود')
        host=target_domain.encode('idna')
        if not 1<=len(host)<=255:raise ValueError('دامنه مقصد معتبر نیست')
        raw.sendall(b'\x05\x01\x00\x03'+bytes([len(host)])+host+(443).to_bytes(2,'big'))
        reply=_socks5_reply(raw)
        if reply[1]!=0:
            codes={1:'خطای عمومی',2:'اتصال غیرمجاز',3:'شبکه در دسترس نیست',4:'میزبان در دسترس نیست',5:'اتصال رد شد',6:'TTL منقضی شد',7:'فرمان پشتیبانی نمی‌شود',8:'نوع آدرس پشتیبانی نمی‌شود'}
            raise ConnectionError('SOCKS CONNECT به Google ناموفق: '+codes.get(reply[1],f'کد {reply[1]}'))
        context=ssl.create_default_context()
        tls_sock=context.wrap_socket(raw,server_hostname=target_domain)
        raw=None
        tls_sock.settimeout(timeout_sec)
        request=(f'GET /generate_204 HTTP/1.1\r\nHost: {target_domain}\r\nUser-Agent: Slipstream-DNS-Scanner/1.0\r\nAccept: */*\r\nConnection: close\r\n\r\n').encode('ascii')
        tls_sock.sendall(request)
        response=b''
        while b'\r\n\r\n' not in response and len(response)<16384:
            chunk=tls_sock.recv(2048)
            if not chunk:break
            response+=chunk
        if b'\r\n\r\n' not in response:raise ConnectionError('پاسخ HTTP گوگل ناقص یا خالی بود')
        status=response.split(b'\r\n',1)[0].decode('ascii','replace')
        elapsed=(time.monotonic()-started)*1000
        if not re.match(r'^HTTP/\d(?:\.\d)? 204(?:\s|$)',status):
            raise ConnectionError(f'پاسخ مورد انتظار Google 204 نبود: {status}')
        return True,'احراز هویت Username/Password در SOCKS5 سمت سرور موفق؛ TLS معتبر و پاسخ HTTP 204 از Google دریافت شد',elapsed
    except Exception as e:
        return False,f'{type(e).__name__}: {e}',(time.monotonic()-started)*1000
    finally:
        if tls_sock:
            try:tls_sock.close()
            except Exception:pass
        if raw:
            try:raw.close()
            except Exception:pass

def _run_parallel(items,workers,fn,append_key,done_key):
    if not items:return
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers,thread_name_prefix='dns-scan') as pool:
        futures={pool.submit(fn,item):item for item in items}
        for future in concurrent.futures.as_completed(futures):
            with DNS_SCAN_LOCK:
                if DNS_SCAN_STATE['cancel']:
                    for f in futures:f.cancel()
                    break
            item=futures[future]
            try:ok,detail,elapsed=future.result()
            except Exception as e:ok,detail,elapsed=False,f'{type(e).__name__}: {e}',0.0
            with DNS_SCAN_LOCK:
                DNS_SCAN_STATE[append_key].append({'resolver':item,'ok':ok,'detail':detail,'elapsed':f'{elapsed:.1f}ms' if append_key=='latency_results' else f'{elapsed:.2f}s'})
                DNS_SCAN_STATE[done_key]+=1

def _dns_scan_worker(domain,resolvers,cert,timeout_sec,workers,username,password):
    try:
        with DNS_SCAN_LOCK:DNS_SCAN_STATE['phase']='ping'
        _run_parallel(resolvers,workers,lambda r:_dns_scan_ping(r,2),'ping_results','ping_done')
        with DNS_SCAN_LOCK:
            # ICMP is informational only. DNS resolvers may block ping while
            # still serving DNS over UDP/TCP, so test every submitted resolver.
            candidates=list(resolvers)
            DNS_SCAN_STATE['latency_total']=len(candidates)
            if not DNS_SCAN_STATE['cancel']:DNS_SCAN_STATE['phase']='latency'
        if not DNS_SCAN_STATE['cancel'] and candidates:
            # Each candidate gets one temporary Slipstream client and one
            # end-to-end authenticated SOCKS5 -> Google HTTPS test.
            def full_latency(resolver):
                return _dns_scan_probe_and_latency(domain,resolver,cert,timeout_sec,username,password)
            _run_parallel(candidates,workers,full_latency,'latency_results','latency_done')
    except Exception as e:
        with DNS_SCAN_LOCK:DNS_SCAN_STATE['latency_results'].append({'resolver':'—','ok':False,'detail':'خطای اسکن: '+str(e),'elapsed':'—'})
    finally:
        with DNS_SCAN_LOCK:DNS_SCAN_STATE['running']=False;DNS_SCAN_STATE['phase']='done'

def _dns_scan_probe_and_latency(domain,resolver,cert,timeout_sec,username,password):
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:sock.bind((LOCAL_HOST,0));local_port=sock.getsockname()[1]
    args=[BIN,'--domain',domain,'--resolver',resolver,'--tcp-listen-host',LOCAL_HOST,'--tcp-listen-port',str(local_port)]
    if cert:args+=['--cert',cert]
    try:u=pwd.getpwnam('slipstream')
    except KeyError:return False,'کاربر سیستم slipstream پیدا نشد',0.0
    def demote():os.initgroups(u.pw_name,u.pw_gid);os.setgid(u.pw_gid);os.setuid(u.pw_uid)
    proc=None;sel=None;started=time.monotonic();output=''
    try:
        proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=0,preexec_fn=demote)
        import selectors
        sel=selectors.DefaultSelector();sel.register(proc.stdout,selectors.EVENT_READ);deadline=started+timeout_sec;ready=False
        while time.monotonic()<deadline:
            with DNS_SCAN_LOCK:
                if DNS_SCAN_STATE['cancel']:return False,'اسکن متوقف شد',(time.monotonic()-started)*1000
            if proc.poll() is not None:break
            for key,_ in sel.select(timeout=.2):
                chunk=os.read(key.fd,4096)
                if chunk:
                    output+=chunk.decode('utf-8','replace')
                    if 'connection ready' in output.lower():ready=True;break
            if ready:break
        if not ready:return False,'Slipstream در مهلت مقرر آماده نشد: '+' '.join(output.split())[-160:],(time.monotonic()-started)*1000
        ok,detail,latency=_dns_scan_latency(DNS_SCAN_TEST_HOST,local_port,username,password,timeout_sec)
        return ok,detail,latency
    except Exception as e:return False,f'{type(e).__name__}: {e}',(time.monotonic()-started)*1000
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=1)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=1)
        if sel:
            try:sel.close()
            except Exception:pass
        if proc and proc.stdout:
            try:proc.stdout.close()
            except Exception:pass

@app.route('/dns-scan')
@require_login
def dns_scan_page():
    cpu=os.cpu_count() or 1
    return render_template_string(DNS_SCAN_HTML,csrf=csrf_token(),global_resolvers='1.1.1.1\n8.8.8.8',cpu_count=cpu,default_workers=min(8,max(1,cpu)))

@app.post('/api/dns-scan/start')
@require_login
def dns_scan_start():
    check_csrf();domain=request.form.get('domain','').strip().lower().rstrip('.');cert=request.form.get('cert','').strip()
    username=request.form.get('socks_user','');password=request.form.get('socks_pass','')
    try:
        dns_port=int(request.form.get('dns_port','53'));resolvers=parse_scan_resolvers(request.form.get('resolvers',''),dns_port)
        timeout_sec=int(request.form.get('timeout','12'));workers=int(request.form.get('workers','1'))
    except (ValueError,TypeError) as e:return jsonify(error=str(e) or 'تنظیمات اسکن نامعتبر است.'),400
    if not username or not password or len(username.encode('utf-8'))>255 or len(password.encode('utf-8'))>255:return jsonify(error='نام کاربری و رمز SOCKS5 الزامی است و هرکدام حداکثر ۲۵۵ بایت باشند.'),400
    if not valid_domain(domain):return jsonify(error='دامنه معتبر نیست.'),400
    if not 5<=timeout_sec<=60:return jsonify(error='مهلت تست باید بین ۵ تا ۶۰ ثانیه باشد.'),400
    if not 1<=workers<=32:return jsonify(error='تعداد Worker باید بین ۱ تا ۳۲ باشد.'),400
    if cert and (not cert.startswith('/') or not os.path.isfile(cert)):return jsonify(error='مسیر گواهی PEM معتبر نیست.'),400
    if not os.path.isfile(BIN) or not os.access(BIN,os.X_OK):return jsonify(error='فایل اجرایی slipstream-client در دسترس نیست.'),500
    with DNS_SCAN_LOCK:
        if DNS_SCAN_STATE['running']:return jsonify(error='یک اسکن دیگر در حال اجراست.'),409
        DNS_SCAN_STATE.update({'running':True,'cancel':False,'domain':domain,'phase':'ping','workers':workers,'ping_total':len(resolvers),'ping_done':0,'latency_total':0,'latency_done':0,'ping_results':[],'latency_results':[],'started_at':time.time()})
    threading.Thread(target=_dns_scan_worker,args=(domain,resolvers,cert,timeout_sec,workers,username,password),daemon=True,name='dns-resolver-scan').start()
    return jsonify(_dns_scan_snapshot())

@app.route('/api/dns-scan/status')
@require_login
def dns_scan_status():return jsonify(_dns_scan_snapshot())

@app.post('/api/dns-scan/stop')
@require_login
def dns_scan_stop():
    check_csrf()
    with DNS_SCAN_LOCK:DNS_SCAN_STATE['cancel']=True
    return jsonify(_dns_scan_snapshot())

@app.route('/')
@require_login
def index():
    ts=tunnels();return render_template_string(HTML,logged=True,tunnels=ts,healthy=sum(x['health_state']=='connected' for x in ts),cooling=sum(x['health_state']=='cooldown' for x in ts),pmin=PMIN,pmax=PMAX,csrf=csrf_token(),lb_port=int(get_setting('lb_port',str(LB_DEFAULT_PORT))),lb_enabled=get_setting('lb_enabled','1')=='1',lb_backends=lb_backends(),global_resolvers=get_setting('global_resolvers','1.1.1.1:53'))
@app.post('/dns/global')
@require_login
def dns_global():
    check_csrf()
    try:
        dns=parse_resolvers(request.form.get('resolvers',''))
    except ValueError as e:
        flash(str(e));return redirect('/')
    value='\n'.join(dns)
    set_settings(global_resolvers=value)
    mode=request.form.get('mode','save')
    if mode!='apply':
        flash('DNS پیش‌فرض ذخیره شد؛ برای دامنه‌های جدید استفاده می‌شود. DNS تونل‌های فعلی تغییر نکرد.')
        return redirect('/')
    c=db();rows=c.execute('SELECT * FROM tunnels ORDER BY port').fetchall();c.close()
    updated=0;restarted=0;failed=[]
    try:
        # Rewrite all unit files first, then persist the new values and reload once.
        for row in rows:
            fresh=dict(row)
            fresh['resolver']=value
            make_unit(fresh,reload_systemd=False)
        for row in rows:
            update(int(row['id']),resolver=value)
            updated+=1
        ctl('daemon-reload')
        # Restart active tunnels one at a time to avoid a simultaneous outage.
        for row in rows:
            i=int(row['id'])
            if not row['enabled']:
                continue
            reset_log_cursor(row)
            z=ctl('restart',unit(i))
            if z.returncode==0:
                update(i,health_state='recovering',retry_at=None,last_started=time.time(),last_error='')
                restarted+=1
            else:
                err=(z.stderr or z.stdout).strip() or 'systemd restart failed'
                update(i,health_state='cooldown',retry_at=time.time()+COOLDOWN,last_error=err,last_down=time.time(),failure_count=(row['failure_count'] or 0)+1)
                failed.append(str(i))
        msg=f'DNS روی {updated} تونل اعمال شد؛ {restarted} تونل فعال به‌ترتیب ری‌استارت شد.'
        if failed:msg+=' ری‌استارت ناموفق برای شناسه: '+', '.join(failed)
        flash(msg)
    except Exception as e:
        flash(f'اعمال DNS کامل نشد: {e}. تنظیمات ذخیره‌شده‌اند؛ وضعیت تونل‌ها را بررسی کن.')
    return redirect('/')
@app.post('/lb/settings')
@require_login
def lb_settings():
    check_csrf()
    try: port=int(request.form.get('lb_port',''))
    except ValueError: flash('پورت لودبالانسر معتبر نیست.'); return redirect('/')
    if not 1<=port<=65535: flash('پورت باید بین 1 تا 65535 باشد.'); return redirect('/')
    # Do not collide with any configured local tunnel port or the panel listener.
    c=db(); used={int(x['port']) for x in c.execute('SELECT port FROM tunnels')}; c.close()
    if port in used or port==PANEL_PORT: flash('این پورت توسط پنل یا یکی از تونل‌ها استفاده می‌شود.'); return redirect('/')
    set_settings(lb_port=port,lb_enabled='1' if request.form.get('lb_enabled')=='1' else '0')
    flash('تنظیمات لودبالانسر ذخیره شد؛ تغییر پورت حداکثر طی چند ثانیه اعمال می‌شود.')
    return redirect('/')

@app.route('/api/status')
@require_login
def api():
    out=[]
    for t in tunnels():
        st=traffic_snapshot(t['id'])
        out.append({'id':t['id'],'state':t['health_state'],'retry_at':t['retry_at'],'last_error':t['last_error'],'failure_count':t['failure_count'],
                    'traffic_ready':st['ready'],'rx':st['rx'],'tx':st['tx'],'rx_rate':st['rx_rate'],'tx_rate':st['tx_rate']})
    return jsonify(tunnels=out)

@app.post('/traffic/reset/<int:i>')
@require_login
def traffic_reset(i):
    check_csrf()
    sample_traffic(force=True)
    c=db()
    exists=c.execute('SELECT 1 FROM tunnels WHERE id=?',(i,)).fetchone()
    if not exists:
        c.close();abort(404)
    c.execute('''INSERT INTO traffic_stats(tunnel_id,rx_total,tx_total,last_rx,last_tx,last_sample,rx_rate,tx_rate)
                 VALUES(?,0,0,0,0,NULL,0,0)
                 ON CONFLICT(tunnel_id) DO UPDATE SET rx_total=0,tx_total=0,rx_rate=0,tx_rate=0''',(i,))
    c.commit();c.close()
    with TRAFFIC_LOCK:
        TRAFFIC_CACHE.pop(i,None)
        TRAFFIC_CACHE.pop('_sampled_at',None)
    flash('آمار حجم نمایشی این تونل صفر شد؛ اتصال و سرویس تغییری نکرد.')
    return redirect('/')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        check_csrf()
        if hmac.compare_digest(request.form.get('password',''),PASSWORD):
            session.clear();session['logged']=True;session['csrf']=secrets.token_urlsafe(24);return redirect('/')
        flash('رمز اشتباه است.')
    return render_template_string(HTML,logged=False,csrf=csrf_token())
@app.route('/logout')
def logout():session.clear();return redirect('/login')

@app.post('/add')
@require_login
def add():
    check_csrf();domain=request.form.get('domain','').strip().lower().rstrip('.');cert=request.form.get('cert','').strip();p=request.form.get('port','').strip()
    try:dns=parse_resolvers(request.form.get('resolvers','') or get_setting('global_resolvers','1.1.1.1:53'))
    except ValueError as e:flash(str(e));return redirect('/')
    if not valid_domain(domain):flash('دامنه معتبر نیست.');return redirect('/')
    if cert and (not cert.startswith('/') or not os.path.isfile(cert)):flash('فایل گواهی معتبر نیست.');return redirect('/')
    c=db()
    if c.execute('SELECT 1 FROM tunnels WHERE domain=?',(domain,)).fetchone():c.close();flash('دامنه تکراری است.');return redirect('/')
    used={x[0] for x in c.execute('SELECT port FROM tunnels')}
    if p:
        try:port=int(p)
        except:port=-1
        if port<PMIN or port>PMAX or port in used:c.close();flash('پورت نامعتبر یا تکراری است.');return redirect('/')
    else:
        port=next((x for x in range(PMIN,PMAX+1) if x not in used),None)
        if port is None:c.close();flash('پورت آزاد موجود نیست.');return redirect('/')
    cur=c.execute('INSERT INTO tunnels(domain,resolver,port,cert,enabled,health_state,last_started) VALUES(?,?,?,?,1,?,?)',(domain,'\n'.join(dns),port,cert,'recovering',time.time()))
    c.commit();i=cur.lastrowid;r=c.execute('SELECT * FROM tunnels WHERE id=?',(i,)).fetchone();c.close()
    try:
        make_unit(r);reset_log_cursor(r);z=ctl('enable','--now',unit(i));flash(f'دامنه ثبت شد؛ پورت {port}' if z.returncode==0 else 'ثبت شد ولی اجرا ناموفق بود: '+(z.stderr or z.stdout).strip())
    except Exception as e:flash('خطا: '+str(e))
    return redirect('/')
@app.post('/dns/<int:i>')
@require_login
def dns_edit(i):
    check_csrf()
    try:dns=parse_resolvers(request.form.get('resolvers',''))
    except ValueError as e:flash(str(e));return redirect('/')
    c=db();r=c.execute('SELECT * FROM tunnels WHERE id=?',(i,)).fetchone();c.close()
    if not r:abort(404)
    update(i,resolver='\n'.join(dns));c=db();r=c.execute('SELECT * FROM tunnels WHERE id=?',(i,)).fetchone();c.close()
    try:
        make_unit(r)
        if r['enabled']:
            reset_log_cursor(r);z=ctl('restart',unit(i));update(i,health_state='recovering',last_started=time.time(),retry_at=None,last_error='')
            flash('DNS ذخیره و تونل ری‌استارت شد.' if z.returncode==0 else 'DNS ذخیره شد اما ری‌استارت ناموفق بود.')
        else:flash('DNS ذخیره شد؛ تونل دستی متوقف است.')
    except Exception as e:flash('خطا در ذخیره DNS: '+str(e))
    return redirect('/')
@app.post('/action/all/<act>')
@require_login
def action_all(act):
    check_csrf()
    if act not in ('start','stop','restart'):
        abort(404)
    c=db(); rows=c.execute('SELECT * FROM tunnels ORDER BY id').fetchall(); c.close()
    if not rows:
        flash('هیچ تونلی برای انجام عملیات وجود ندارد.')
        return redirect('/')

    # Run services sequentially to avoid a sudden CPU/network spike.
    succeeded=0; failed=[]; now=time.time()
    if act=='stop':
        for r in rows:
            i=r['id']; z=ctl('disable','--now',unit(i))
            if z.returncode==0:
                update(i,enabled=0,health_state='manual',retry_at=None,last_error='')
                succeeded+=1
            else:
                failed.append(f"{r['domain']}: {(z.stderr or z.stdout).strip() or 'systemctl error'}")
        label='توقف'
    else:
        targets=[r for r in rows if act=='start' or r['enabled']]
        prepared=[]
        for r in targets:
            try:
                make_unit(r, reload_systemd=False)
                prepared.append(r)
            except Exception as e:
                failed.append(f"{r['domain']}: {e}")
        reload_result=ctl('daemon-reload')
        if reload_result.returncode!=0:
            failed.append('systemd daemon-reload: '+(reload_result.stderr or reload_result.stdout).strip())
        else:
            for r in prepared:
                i=r['id']
                try:
                    reset_log_cursor(r)
                    en=ctl('enable',unit(i))
                    z=ctl('restart' if act=='restart' else 'start',unit(i)) if en.returncode==0 else en
                    if z.returncode==0:
                        update(i,enabled=1,health_state='recovering',retry_at=None,last_started=now,last_error='')
                        succeeded+=1
                    else:
                        err=(z.stderr or z.stdout).strip() or 'systemd نتوانست سرویس را اجرا کند.'
                        update(i,enabled=1,health_state='cooldown',retry_at=now+COOLDOWN,last_started=now,last_down=now,last_error=err,failure_count=(r['failure_count'] or 0)+1)
                        failed.append(f"{r['domain']}: {err}")
                except Exception as e:
                    failed.append(f"{r['domain']}: {e}")
        label='اجرا' if act=='start' else 'ری‌استارت'
        if act=='restart' and not targets:
            flash('هیچ تونل فعالی برای ری‌استارت وجود ندارد؛ تونل‌های متوقف‌شده بدون تغییر باقی ماندند.')
            return redirect('/')

    summary=f"عملیات {label} گروهی: {succeeded} مورد موفق از {len(rows) if act=='stop' else len(targets)} مورد."
    if failed:
        summary += ' خطاها: ' + ' | '.join(failed[:5])
        if len(failed)>5: summary += f" | و {len(failed)-5} خطای دیگر"
    flash(summary)
    return redirect('/')


@app.post('/action/<int:i>/<act>')
@require_login
def action(i,act):
    check_csrf();c=db();r=c.execute('SELECT * FROM tunnels WHERE id=?',(i,)).fetchone();c.close()
    if not r:abort(404)
    if act in ('start','restart'):
        try:
            make_unit(r);reset_log_cursor(r);ctl('enable',unit(i));z=ctl('restart' if act=='restart' else 'start',unit(i));update(i,enabled=1,health_state='recovering',retry_at=None,last_started=time.time(),last_error='')
            flash('تونل راه‌اندازی شد.' if z.returncode==0 else 'خطا در اجرا: '+(z.stderr or z.stdout).strip())
        except Exception as e:flash('خطا: '+str(e))
    elif act=='stop':
        ctl('stop',unit(i));update(i,enabled=0,health_state='manual',retry_at=None,last_error='');flash('توقف دستی انجام شد.')
    elif act=='delete':
        ctl('disable','--now',unit(i))
        try:os.remove(f'/etc/systemd/system/{unit(i)}.service')
        except FileNotFoundError:pass
        ctl('daemon-reload');c=db();c.execute('DELETE FROM tunnels WHERE id=?',(i,));c.commit();c.close();flash('تونل حذف شد.')
    else:abort(404)
    return redirect('/')
@app.route('/logs/<int:i>')
@require_login
def logs(i):
    c=db();r=c.execute('SELECT * FROM tunnels WHERE id=?',(i,)).fetchone();c.close()
    if not r:abort(404)
    z=ctl('status','--no-pager','-n','80',unit(i));out=(z.stdout+'\n'+z.stderr)[-16000:]
    return f'''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><a href="/">بازگشت</a><h3>{escape(r["domain"])}</h3><pre dir="ltr">{escape(out)}</pre></html>'''

if __name__=='__main__':
    db().close()
    threading.Thread(target=monitor,daemon=True,name='slipstream-health-monitor').start()
    threading.Thread(target=lb_supervisor,daemon=True,name='slipstream-lb-supervisor').start()
    app.run(host=PANEL_HOST,port=PANEL_PORT,debug=False,use_reloader=False)
