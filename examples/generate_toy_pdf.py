from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

def generate_pdf():
    c = canvas.Canvas("ATLAS_toy_report.pdf", pagesize=letter)
    
    # Page 1: Summary Page
    c.drawString(100, 750, "Johns Hopkins University Sponsored Financial Report")
    c.drawString(100, 730, "Grant: 200001 - ATLAS PI For")
    c.drawString(100, 710, "Sponsored Program: 987654 - AWD0001")
    c.drawString(100, 690, "Expenditures Budget September 2025")
    
    # Category lines (cumulative)
    c.drawString(100, 650, "Salaries & Wages 20,000.00 80,000.00 4,000.00")
    c.drawString(100, 630, "Fringe Benefits 4,000.00 16,000.00 800.00")
    c.drawString(100, 610, "Tuition & Fees 5,000.00 20,000.00 0.00")
    c.drawString(100, 590, "Total Student Health 1,000.00 4,000.00 0.00")
    c.drawString(100, 570, "Total Service Center 0.00 0.00 0.00")
    c.drawString(100, 550, "Travel Domestic 2,000.00 8,000.00 0.00")
    c.drawString(100, 530, "Other Expenses 3,000.00 12,000.00 200.00")
    
    # Totals
    # Budget, Monthly, Cumulative Spent, Committed, Spent+Committed
    c.drawString(100, 490, "Total Expenditures 1,000,000.00 50,000.00 200,000.00 5,000.00 205,000.00")
    c.drawString(100, 470, "Total Indirect Costs 0.00 15,000.00 60,000.00 3,000.00 63,000.00")
    c.drawString(100, 450, "Budget Utilized: 20.8%")
    c.drawString(100, 430, "Sponsored Revenue 1,000,000.00")
    c.showPage()

    # Page 2: Personnel Page (Salary Report)
    c.drawString(100, 750, "Grant: 200001")
    c.drawString(100, 730, "Salary Report September 2025")
    
    # Personnel records (with GL account lines backwards from total lines)
    c.drawString(100, 690, "G/L 600010 - FACULTY SALARIES")
    c.drawString(100, 670, "Total for Smith, Jane 1,404.28")
    
    c.drawString(100, 640, "G/L 600020 - POSTDOC SALARIES")
    c.drawString(100, 620, "Total for Chen, Wei 7,500.00")
    
    c.drawString(100, 590, "G/L 600030 - STUDENT GRAD STIPEND")
    c.drawString(100, 570, "Total for Student, Grad1 4,000.00")
    c.drawString(100, 550, "Total for Student, Grad2 4,000.00")
    
    c.drawString(100, 520, "G/L 600040 - STAFF SALARIES")
    c.drawString(100, 500, "Total for Johnson, Alex 1,010.24")
    
    c.showPage()
    c.save()
    print("Successfully generated ATLAS_toy_report.pdf")

if __name__ == "__main__":
    generate_pdf()
