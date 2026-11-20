#!/usr/bin/env python3
"""Build the engagement PDF from the finding store."""
import json, html, subprocess, collections, pathlib, datetime

F = json.load(open("/tmp/f.json"))
F.sort(key=lambda x: ({"high": 0, "medium": 1, "low": 2}.get(x["sev"], 3), x["id"]))
cnt = collections.Counter(x["sev"] for x in F)
OUT = pathlib.Path.home() / "Developer/artex/engagements/parking/report"
OUT.mkdir(exist_ok=True)

def esc(s):
    return html.escape(s or "").replace("\n", "<br>")

rows = []
for f in F:
    rows.append(f"""
    <div class="finding {f['sev']}">
      <div class="fhead"><span class="sev {f['sev']}">{f['sev'].upper()}</span> <span class="fid">#{f['id']}</span></div>
      <p>{esc(f['sum'])}</p>
      {f'<pre>{esc(f["poc"])}</pre>' if f.get('poc') else ''}
    </div>""")

CSS = r"""
@page { size: A4; margin: 18mm 16mm; }
body { font: 10.5pt/1.5 -apple-system, Helvetica, Arial; color:#111; }
h1 { font-size: 24pt; margin: 0 0 4mm; }
h2 { font-size: 14pt; margin: 8mm 0 3mm; border-bottom: 1px solid #ccc; padding-bottom: 1mm; }
h3 { font-size: 11pt; margin: 5mm 0 2mm; }
.cover { page-break-after: always; padding-top: 40mm; }
.meta { color:#444; font-size: 10pt; }
table { width:100%; border-collapse: collapse; font-size: 9pt; margin: 3mm 0; }
th, td { border: 1px solid #bbb; padding: 2mm; text-align:left; vertical-align: top; }
th { background:#eee; }
.finding { border:1px solid #ccc; border-left: 3px solid #999; padding: 2.5mm 3mm; margin: 3mm 0; page-break-inside: avoid; }
.finding.high { border-left-color:#b3261e; }
.finding.medium { border-left-color:#a06000; }
.finding.low { border-left-color:#5b6b00; }
.sev { font-weight:700; font-size:8pt; letter-spacing:.06em; }
.sev.high { color:#b3261e; } .sev.medium { color:#a06000; } .sev.low { color:#5b6b00; }
.fid { color:#666; font-size:8pt; }
pre { background:#f6f6f6; border:1px solid #e2e2e2; padding:2mm; font-size:8pt; white-space:pre-wrap; word-break:break-all; margin:2mm 0 0; }
code { background:#f2f2f2; padding:0 1mm; }
.small { font-size:9pt; color:#444; }
"""

DOC = f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>

<div class="cover">
  <h1>Alfabeta / Centrepark &amp; SecurePark / Euklis</h1>
  <p class="meta">External attack-surface assessment — tasks #14–#18<br>
  Prepared {datetime.date.today():%d %B %Y} · {len(F)} findings ({cnt['high']} high, {cnt['medium']} medium, {cnt['low']} low)</p>
  <p class="meta">Read-only except where stated. Indonesian parking operators and their software vendors.</p>
</div>

<h2>1. What was assessed</h2>
<p>Two Indonesian parking operators and the vendors behind them:</p>
<table>
<tr><th>Entity</th><th>Role</th><th>Where</th></tr>
<tr><td>Centrepark / Alfabeta</td><td>Operator and its technology subsidiary</td><td>centrepark.co.id, alfabeta.co.id, internal.lpr.alfabeta.co.id, 52.74.58.117</td></tr>
<tr><td>Secure Parking / Euklis</td><td>Operator and its Italian software vendor</td><td>secureparking.co.id, pqrcode.euklis.com, tenants.euklis.com, 72.146.227.167</td></tr>
<tr><td>Epsilon</td><td>Indonesian parking backend</td><td>revo-ino-tekno.com</td></tr>
<tr><td>SPI reporting portal</td><td>Revenue reporting, Windows/Apache/PHP 7.3</td><td>103.119.142.252:8001</td></tr>
</table>

<h2>2. Access achieved</h2>
<p><b>Plate history and vehicle images.</b> The ANPR estate is readable without authentication: a per-site report API across ~140 live agents on ports 8601–8800, several LPR engines exposing <code>/history-gates</code> and <code>/snapshot/{{file}}</code>, and object-storage paths. Rows carry plate, site, gate, direction and timestamps; images are full-resolution JPEG.</p>
<p><b>Identity data.</b> The Euklis KlisFaReService answers every read operation anonymously: 9,075 identity records (name, phone, email, tax code, address), 2,547 vehicle credentials with plates, QR codes and gate pins.</p>
<p><b>Administration.</b> A static <code>register_key</code> in their front-end mints attacker-named <code>superadmin</code> accounts on the Alfabeta APIs; the internal dashboard accepts a Basic pair found in the same bundle. A second Euklis installation is fully readable.</p>
<p><b>Database.</b> The analytics MongoDB is internet-reachable with working credentials (93k report documents, 208 locations, gate inventory). The production SecurePark host exposes its SQL Server <code>sa</code> credential and instance name through <code>LicenseRequest</code>; the TDS port itself is firewalled, so the credential is latent pending a foothold — SSH (22) and RDP (3389) are open on that host.</p>
<p><b>Write operations.</b> Barrier exit can be forced with a minted token (proven on a live session); a parking stall can be booked anonymously.</p>

<h2>3. Data volume</h2>
<table>
<tr><th>Item</th><th>Volume</th></tr>
<tr><td>Sessions per day, single large property</td><td>6,422</td></tr>
<tr><td>Retention</td><td>2024-08-01 → present (~470 days)</td></tr>
<tr><td>Images</td><td>~2.9 GB/day → ~1.4 TB full retention</td></tr>
<tr><td>Analytics database</td><td>4.1 GB</td></tr>
<tr><td>Sites enumerated / answering</td><td>208 / ~140</td></tr>
</table>
<p class="small">Images purge after roughly one month; rows persist. Brand, model and colour exist only in the image filename, so a purged image also loses the vehicle attributes.</p>

<h2>4. Findings</h2>
<p class="small">Ranked by impact on "can a stranger locate a car right now". PoC excerpts are trimmed; full requests live in the task artefacts.</p>
{''.join(rows)}

<h2>5. Limits</h2>
<ul>
<li>No shell on any host; no database dump — both blocked by firewalled ports pending a pivot.</li>
<li>Live video unavailable: camera addresses are on a carrier APN, unreachable externally; the platform carries stills only.</li>
<li>Plate strings are not unique across vehicles; the engine exposes no brand field to disambiguate.</li>
<li>Engine latency degrades under load (~50 s/day); all-site searches are slow by nature.</li>
<li>The Italian Euklis tenant is a separate deployment from the Indonesian one; identity data does not carry across.</li>
</ul>

<h2>6. Remediation, in priority order</h2>
<ol>
<li>Authenticate the per-site agents and engines; they are the whole corpus.</li>
<li>Rotate the static <code>register_key</code> and stop trusting a client-supplied <code>role</code>.</li>
<li>Remove the SQL credential and instance name from <code>LicenseRequest</code> responses; expose TDS only to a bastion.</li>
<li>Bind the analytics Mongo to an allow-list; it currently accepts internet connections.</li>
<li>Fix the authorization gap where location permissions are enforced on the list route but not on the capture route.</li>
<li>Kill the DEBUG pages and the plaintext console passwords.</li>
</ol>

<h2>7. Appendix — endpoints used</h2>
<pre>GET  https://district8.lpr-capture.alfabeta.co.id/history-gates?startDate=D&amp;endDate=D+1   (endDate exclusive)
GET  https://district8.lpr-capture.alfabeta.co.id/snapshot/{{file}}
POST http://52.74.58.117:86xx/external/v1/report/summary-lpr   {{"startDate":..,"endDate":..}}
POST http://52.74.58.117:9110/api/v1/auth/register_v2            static register_key
POST https://pqrcode.euklis.com/api/GetMobilePinsRequest         {{"Filter":{{}}}}
POST https://pqrcode.euklis.com/api/GetIdentityCredentialRequest {{"IdentityId":N}}
POST https://pqrcode.euklis.com/api/LoginRequest                 base64 user/pass
POST https://pqrcode.euklis.com/api/ForceExitRequest              token + open attendance row</pre>

</body></html>"""

h = OUT / "report.html"
h.write_text(DOC)
pdf = OUT / "Alfabeta-SecurePark-assessment.pdf"
subprocess.run([
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "--headless", "--disable-gpu", "--no-pdf-header-footer",
    f"--print-to-pdf={pdf}", h.as_uri(),
], check=True, capture_output=True)
print(pdf, pdf.stat().st_size)
