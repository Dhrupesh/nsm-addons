# -*- coding: utf-8 -*-
from odoo.addons.report_xlsx.report.report_xlsx import ReportXlsx
from odoo import api, fields, models, _
import datetime
from odoo.exceptions import UserError

class NSMDeliveryListReport(ReportXlsx):

    def generate_xlsx_report(self, workbook, data, orderLines):

        def _get_title(orderLine):
            title = []
            for advtitle in orderLine.title_ids:
                if advtitle.product_attribute_value_id:
                    title.append(advtitle.product_attribute_value_id.name)
            if orderLine.title.product_attribute_value_id:
                title.append(orderLine.title.product_attribute_value_id.name)
            title = ",".join(list(set(title))) if title else ' '
            return title

        def _prepare_data(customer, orderLine):
            records = []
            parent = customer.parent_id
            records.append(_get_title(orderLine))
            records.append(parent.name if parent else customer.name)
            if parent and not parent.is_company:
                records.append(parent.initials or '')
                records.append(parent.infix or '')
                records.append(parent.lastname or '')
            elif not parent and not customer.is_company:
                records.append(customer.initials or '')
                records.append(customer.infix or '')
                records.append(customer.lastname or '')
            else:
                records.append('')
                records.append('')
                records.append('')
            records.append(customer.country_id.code or parent.country_id.code or '')
            records.append(customer.zip or parent.zip or '')
            records.append(customer.street_number or parent.street_number or '')
            records.append('')
            records.append(customer.street_name or parent.street_name or '')
            records.append(customer.city or parent.city or '')

            amount = 0
            if customer.id in orderLine.proof_number_adv_customer.ids:
                amount = orderLine.proof_number_amt_adv_customer
            elif orderLine.proof_number_payer and orderLine.proof_number_payer.id == customer.id:
                amount = orderLine.proof_number_amt_payer
            records.append(amount)
            records.append(customer.name if parent else '')
            return records

        def _form_data(orderLines):
            row_datas = []
            for orderLine in orderLines:
                partners = orderLine.proof_number_adv_customer | orderLine.proof_number_payer
                for part in partners:
                    row_datas.append(_prepare_data(part, orderLine))
            return row_datas

        header = ['PAPERCODE', 'CUSTOMER NAME', 'VOORLETTERS', 'TUSSENVOEGSEL', 'ACHTERNAAM', 'COUNTRY CODE', 'ADDRESS ZIP',
                  'HUISNUMMER', 'AANVULLING', 'ADDRESS STREET', 'ADDRESS CITY', 'AANTAL', 'CONTACT PERSOON']

        row_datas = _form_data(orderLines)

        if row_datas:
            bold_format = workbook.add_format({'bold': True})
            report_name = 'PNDL_{date:%Y-%m-%d %H:%M:%S}'.format(date=datetime.datetime.now())
            sheet = workbook.add_worksheet(report_name[:31])
            for i, title in enumerate(header):
                sheet.write(0, i, title, bold_format)
            for row_index, row in enumerate(row_datas):
                for cell_index, cell_value in enumerate(row):
                    sheet.write(row_index + 1, cell_index, cell_value)
            workbook.close()
        else:
            raise UserError(_('No record found to print!'))



NSMDeliveryListReport('report.report_pndl_delivery_list.xlsx', 'sale.order.line')