import os
from datetime import date
import pdb
import logging
from datetime import datetime
import fitz  # install using: pip install PyMuPDF

# Setup logging
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s')


# Ask for the year to work on
year_to_work = input("Enter the year to work on: ")

# Check if the input year is a valid directory
if not os.path.isdir(year_to_work):
    print(f"The folder for the year {year_to_work} does not exist.")
    exit(1)

total_hours = 0
no_shelter_hours = 0

def list_pdf_files(folder_path):
    return [f for f in os.listdir(folder_path) if f.endswith('.pdf')]

def is_new_guso_format(page):
    v2_title_position = fitz.Rect(122, 2, 460, 20)
    result = page.get_textbox(v2_title_position) == "Déclaration unique et simplifiée"
    logging.debug(f"Checking format, result: {result}")
    return result


# List contracts in the specified year's folder
contracts_path = os.path.join(year_to_work)
pdf_files = list_pdf_files(contracts_path)
current_year = date.today().year

for contract in pdf_files:
    if not contract.startswith('20'):
        contract_date = contract.split(" ")[3]

        with fitz.open(os.path.join(contracts_path, contract)) as doc:
            page = doc[0]

            print(contract)
            pdf_words = doc[0].get_text().split('\n')

            if pdf_words == ['']:
                print('No text in PDF', contract)
                continue

            if is_new_guso_format(page):
                salary_brut_euros = page.get_textbox(fitz.Rect(154, 503, 167, 514))
                salary_brut_cents = page.get_textbox(fitz.Rect(176, 504, 185, 515))
                salary_brut = float(salary_brut_euros + '.' + salary_brut_cents)
                salary_net_euros = page.get_textbox(fitz.Rect(238, 624, 252, 635))
                salary_net_cents = page.get_textbox(fitz.Rect(266, 605, 275, 616))
                salary_net = float(salary_net_euros + '.' + salary_net_cents)
                begin_date = page.get_textbox(fitz.Rect(99, 364, 139, 375))
                end_date = page.get_textbox(fitz.Rect(192, 364, 232, 375))
                place = page.get_textbox(fitz.Rect(382, 484, 460, 495))
                event = page.get_textbox(fitz.Rect(117, 484, 270, 495))
                contract_hours = page.get_textbox(fitz.Rect(150, 420, 170, 440)).strip()
                secu = page.get_textbox(fitz.Rect(385, 250.08998107910156, 500, 266.8900146484375)).replace("\n", "")
            else:
                text_box_salary = page.get_textbox(fitz.Rect(500, 450, 595, 680)).split('\n ')
                text_box_salary_without_spaces = [s.replace(" ", "") for s in text_box_salary]
                salary_net = text_box_salary_without_spaces[9][:-2] + "." + text_box_salary_without_spaces[9][-2:]
                salary_brut = text_box_salary_without_spaces[1][:-2] + "." + text_box_salary_without_spaces[1][-2:]
                begin_date_small= page.get_textbox(fitz.Rect(90, 542, 340, 545)).split('\n')[6].replace("  ", "/").replace("//", "/").replace(" ", "")
                parsed_date = datetime.strptime(begin_date_small, "%d/%m/%y")
                begin_date = parsed_date.strftime("%d/%m/%Y")
                end_date_small = page.get_textbox(fitz.Rect(90, 542, 340, 545)).split('\n')[7].replace("  ", "/").replace("//", "/").replace(" ", "")
                place = page.get_textbox(fitz.Rect(125.49600219726562, 492, 230, 507.0252685546875))
                event = page.get_textbox(fitz.Rect(125, 485, 233, 490))
                secu = page.get_textbox(fitz.Rect(190.40597534179688, 250.08998107910156, 400, 266.8900146484375)).replace(" ", "").replace("\n", "")
                contract_hours = "8"
            year = begin_date.split("/")[2]
            month = begin_date.split("/")[1]
            day = begin_date.split("/")[0]

            new_name = year + month + day + ' - ' + place + ' - ' + contract_hours + 'H.pdf'

        os.rename(os.path.join(contracts_path, contract), os.path.join(contracts_path, new_name))
        total_hours += int(new_name.split(" -")[-1].split("H")[0])
    
    else:
        try:
            contract_hours = contract.split(" -")[-1].split("H")[0].strip()
            total_hours += int(contract_hours)
        except ValueError:
            pdb.set_trace()
        if not "SHELTER" in contract:
            no_shelter_hours += int(contract_hours)

print(f"Total hours : {total_hours}")
print(f"Total hours (without SHELTER) : {no_shelter_hours}")
