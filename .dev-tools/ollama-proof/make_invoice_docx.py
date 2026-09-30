"""Generate the Word invoice (with a real table) used by the invoice proof."""

from pathlib import Path

import docx

OUT = Path(__file__).parent / "inputs" / "invoice" / "03-hardware-nakuru.docx"


def main() -> None:
    d = docx.Document()
    d.add_heading("MWANGI & SONS HARDWARE", level=1)
    d.add_paragraph("Kenyatta Avenue, Nakuru  |  0711 222 333  |  KRA PIN P051998877M")
    d.add_paragraph("INVOICE  No. MSH-2026-114")
    d.add_paragraph("Date: 22 September 2026")
    d.add_paragraph("Customer: Kariuki Logistics - Nakuru Depot (attn: Otieno)")
    t = d.add_table(rows=1, cols=4)
    t.style = "Table Grid"
    for c, h in zip(t.rows[0].cells, ["Description", "Qty", "Unit Price (KES)", "Amount (KES)"]):
        c.text = h
    for row in [
        ("Cement 50kg (Bamburi)", "20", "780.00", "15,600.00"),
        ("Iron sheets gauge 30, 3m", "15", "1,150.00", "17,250.00"),
        ("Roofing nails 5kg", "4", "850.00", "3,400.00"),
        ("Transport to depot", "1", "4,000.00", "4,000.00"),
    ]:
        cells = t.add_row().cells
        for c, v in zip(cells, row):
            c.text = v
    d.add_paragraph("Subtotal: KES 40,250.00")
    d.add_paragraph("VAT 16%: KES 6,440.00")
    d.add_paragraph("TOTAL: KES 46,960.00")
    d.add_paragraph("Payment terms: cash/M-Pesa on delivery. Goods once sold are not returnable!!")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    d.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()