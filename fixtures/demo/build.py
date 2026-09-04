"""Builds the offline demo corpus. Synthetic pages that reproduce real-web traps:
manufacturer page (JSON-LD), spec aggregator, three retailers sharing one copied spec block with an error,
a sibling model page (GSR 12V-35 without FC), a PDF datasheet, and a forum post found only by a hole-driven query.
Values are illustrative, not verified product facts."""
import json
from pathlib import Path

HERE = Path(__file__).parent

manufacturer = """<html><head><title>GSR 12V-35 FC Professional | Bosch Professional</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"GSR 12V-35 FC Professional",
"brand":{"@type":"Brand","name":"Bosch"},"manufacturer":{"@type":"Organization","name":"Robert Bosch Power Tools GmbH"},
"mpn":"06019H3002","gtin13":"3165140876643","sku":"06019H3002","image":["https://www.bosch-professional.example/img/gsr12v35fc.jpg"],
"weight":{"@type":"QuantitativeValue","value":"0.59","unitCode":"kg"}}</script></head>
<body><h1>GSR 12V-35 FC Professional</h1><p>Cordless drill/driver, FlexiClick system. Solo version: without battery and charger.</p>
<table><tr><th>Battery voltage</th><td>12 V</td></tr><tr><th>Max. torque (hard/soft)</th><td>35 / 20 Nm</td></tr>
<tr><th>No-load speed</th><td>0 – 1,750 rpm</td></tr><tr><th>Chuck type</th><td>FlexiClick</td></tr>
<tr><th>Weight excl. battery</th><td>0.59 kg</td></tr><tr><th>Motor type</th><td>Brushless</td></tr></table>
<p>Order number 0 601 9H3 002</p></body></html>"""

icecat = """<html><head><title>Bosch GSR 12V-35 FC Cordless drill 1750 RPM 590 g - Icecat</title></head><body>
<h1>Bosch GSR 12V-35 FC</h1><dl><dt>Brand</dt><dd>Bosch</dd><dt>EAN</dt><dd>3165140876643</dd><dt>Weight</dt><dd>590 g</dd>
<dt>Battery voltage</dt><dd>12 V</dd><dt>Maximum torque</dt><dd>35 Nm</dd><dt>No-load speed</dt><dd>1750 RPM</dd>
<dt>Motor type</dt><dd>Brushless</dd></dl></body></html>"""

def shop(domain, price):
    return f"""<html><head><title>Bosch GSR 12V-35 FC Professional - buy at {domain}</title>
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Product","name":"Bosch GSR 12V-35 FC Professional",
"brand":"Bosch","offers":{{"@type":"Offer","price":"{price}","priceCurrency":"UAH","availability":"https://schema.org/InStock"}}}}</script></head>
<body><h1>Bosch GSR 12V-35 FC Professional</h1><button>Add to cart</button>
<table><tr><td>Voltage</td><td>12 V</td></tr><tr><td>Max torque</td><td>30 Nm</td></tr><tr><td>Weight</td><td>0.8 kg</td></tr>
<tr><td>Warranty</td><td>24 months</td></tr><tr><td>Color</td><td>Blue</td></tr><tr><td>No-load speed</td><td>1750 rpm</td></tr></table>
<p>Also see: Bosch GSR 12V-35, Bosch GSB 12V-35.</p></body></html>"""

sibling = """<html><head><title>Bosch GSR 12V-35 Professional cordless drill - shop-d</title></head><body>
<h1>Bosch GSR 12V-35 Professional</h1><button>Add to cart</button>
<table><tr><td>Voltage</td><td>12 V</td></tr><tr><td>Max torque</td><td>30 Nm</td></tr><tr><td>Weight</td><td>0.6 kg</td></tr>
<tr><td>Warranty</td><td>12 months</td></tr></table></body></html>"""

forum = """<html><head><title>GSR 12V-35 FC warranty question - Tool Forum</title></head><body>
<h1>GSR 12V-35 FC warranty question</h1><p>Posted by user123</p>
<p>I registered my Bosch GSR 12V-35 FC on the Bosch site. Warranty: 3 years after registration, otherwise 1 year.</p>
<p>Reply: yes, that's the Pro warranty scheme.</p></body></html>"""

def pdf(path: Path):
    from fpdf import FPDF
    doc = FPDF()
    doc.add_page()
    doc.set_font("Helvetica", size=11)
    for line in ["GSR 12V-35 FC Professional", "Cordless Drill/Driver - Technical data", "Battery voltage: 12 V",
                 "Max. torque (hard/soft): 35 / 20 Nm", "No-load speed: 0 - 1,750 rpm", "Chuck capacity: 1 - 10 mm",
                 "Weight excl. battery: 0.59 kg", "Motor type: Brushless (EC)", "Order number: 0 601 9H3 002"]:
        doc.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    doc.output(str(path))

files = {
    "manufacturer.html": manufacturer, "icecat.html": icecat, "shop-a.html": shop("shop-a.example", 4999),
    "shop-b.html": shop("shop-b.example", 5099), "shop-c.html": shop("shop-c.example", 4899), "sibling.html": sibling, "forum.html": forum,
}
for name, content in files.items():
    (HERE / name).write_text(content)
pdf(HERE / "datasheet.pdf")

index = {"leads": [
    {"url": "https://www.bosch-professional.example/gb/en/gsr-12v-35-fc-professional", "file": "manufacturer.html", "tier": "A",
     "title": "GSR 12V-35 FC Professional | Bosch Professional", "match_any": ["gsr12v35fc"], "ids": ["06019H3002", "3165140876643"]},
    {"url": "https://www.bosch-professional.example/media/gsr-12v-35-fc-datasheet.pdf", "file": "datasheet.pdf", "tier": "A",
     "title": "GSR 12V-35 FC datasheet (PDF)", "match_any": ["datasheet", "technicaldata", "technischedaten", "specifications"], "require_all": ["gsr12v35fc"]},
    {"url": "https://icecat.example/en/p/bosch/gsr-12v-35-fc", "file": "icecat.html", "tier": "B", "title": "Bosch GSR 12V-35 FC - Icecat",
     "match_any": ["gsr12v35fc"], "ids": ["3165140876643"]},
    {"url": "https://shop-a.example/p/bosch-gsr-12v-35-fc", "file": "shop-a.html", "tier": "C", "match_any": ["gsr12v35"]},
    {"url": "https://shop-b.example/product/12345-bosch-gsr-12v-35-fc", "file": "shop-b.html", "tier": "C", "match_any": ["gsr12v35"]},
    {"url": "https://shop-c.example/bosch/gsr-12v-35-fc", "file": "shop-c.html", "tier": "C", "match_any": ["gsr12v35"]},
    {"url": "https://shop-d.example/bosch-gsr-12v-35", "file": "sibling.html", "tier": "C", "match_any": ["gsr12v35"]},
    {"url": "https://forum.example/t/gsr-12v-35-fc-warranty", "file": "forum.html", "tier": "D",
     "match_any": ["warranty", "гарантія", "garantie"], "require_all": ["gsr12v35fc"]},
]}
(HERE / "index.json").write_text(json.dumps(index, indent=2))
print("built", len(files) + 1, "files")
